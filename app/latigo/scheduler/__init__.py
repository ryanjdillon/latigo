import traceback
import logging
import pprint
import typing
import pandas as pd
import datetime
from os import environ
from latigo.types import Task
from latigo.task_queue import task_queue_sender_factory
from latigo.model_info import model_info_provider_factory
from latigo.clock import OnTheClockTimer
from latigo.utils import human_delta, sleep
from latigo.auth import AuthVerifier
from latigo.gordo import GordoModelInfoProvider


logger = logging.getLogger(__name__)


class Scheduler:
    def _fail(self, message: str):
        self.good_to_go = False
        logger.error(message)
        if False:
            logger.warning(f"NOTE: Using config:")
            logger.warning(f"")
            for line in str(pprint.pformat(self.config)).split("\n"):
                logger.warning(line)
        logger.warning(f"")

    # Inflate model info connection from config
    def _prepare_model_info(self):
        self.model_info_config = self.config.get("model_info", None)
        if not self.model_info_config:
            self._fail("No model info config specified")
        self.model_info_connection_string = self.model_info_config.get(
            "connection_string", "no connection string set for model info"
        )
        # NOTE: This is a hack. We need a project appended to the URL for it to be valid, but there is no guarantee that the project has been set up with lat-lit project
        self.model_info_connection_string += "/lat-lit/"
        self.model_info_provider = model_info_provider_factory(self.model_info_config)
        if not self.model_info_provider:
            self._fail("No model info configured")

    # Inflate task queue connection from config
    def _prepare_task_queue(self):
        self.task_queue_config = self.config.get("task_queue", None)
        if not self.task_queue_config:
            self._fail("No task queue config specified")
        self.task_queue = task_queue_sender_factory(self.task_queue_config)
        self.idle_time = datetime.datetime.now()
        self.idle_number = 0
        if not self.task_queue:
            self._fail("No task queue configured")

    # Perform a basic authentication test up front to fail early with clear error output
    def _perform_auth_check(self):
        # fmt: off
        verifiers = [
            (self.model_info_connection_string, AuthVerifier(config=self.model_info_config.get("auth", {}))),
            ]
        # fmt: on
        error_count = 0
        for url, verifier in verifiers:
            res, message = verifier.test_auth(url=url)
            if not res:
                logger.error(f"Auth test for '{url}' failed with: '{message}'")
                error_count += 1
        if error_count > 0:
            self._fail(
                f"Auth test failed for {error_count} of {len(verifiers)} configurations, see previous logs for details."
            )
        else:
            logger.info(f"Auth test succeedded for {len(verifiers)} configurations.")

    # Inflate scheduler from config
    def _prepare_scheduler(self):
        self.scheduler_config = self.config.get("scheduler", None)
        if not self.scheduler_config:
            self._fail("No scheduler config specified")
        self.name = self.scheduler_config.get("name", "unnamed_scheduler")
        self.restart_interval_sec = self.scheduler_config.get(
            "restart_interval_sec", 60 * 60 * 24 * 7
        )
        try:
            cpst = self.scheduler_config.get(
                "continuous_prediction_start_time", "08:00"
            )
            self.continuous_prediction_start_time = datetime.datetime.strptime(
                cpst, "%H:%M"
            ).time()
        except Exception as e:
            self._fail(
                f"Could not parse '{cpst}' into continuous_prediction_start_time: {e}"
            )
        try:
            cpsc = self.scheduler_config.get("continuous_prediction_interval", "30m")
            self.continuous_prediction_interval = pd.to_timedelta(cpsc)
        except Exception as e:
            self._fail(
                f"Could not parse '{cpsc}' into continuous_prediction_interval: {e}"
            )
        try:
            cpd = self.scheduler_config.get("continuous_prediction_delay", "1d")
            self.continuous_prediction_delay = pd.to_timedelta(cpd)
        except Exception as e:
            self._fail(f"Could not parse '{cpd}' into continuous_prediction_delay: {e}")
        self.continuous_prediction_timer = OnTheClockTimer(
            start_time=self.continuous_prediction_start_time,
            interval=self.continuous_prediction_interval,
        )
        try:
            p = self.scheduler_config.get("projects", "")
            self.projects = [x.strip(" ") for x in p.split(",")]
        except Exception as e:
            self._fail(f"Could not parse '{p}' into projects: {e}")
        self.run_at_once = self.scheduler_config.get("run_at_once", True)
        self.back_fill_max_interval = pd.to_timedelta(
            self.scheduler_config.get("back_fill_max_interval", "1d")
        )
        if not self.projects:
            self._fail("No projects specified")
        if self.good_to_go:
            next_start = f"{self.continuous_prediction_timer.closest_start_time()} (in {human_delta(self.continuous_prediction_timer.time_left())})"
            restart_interval_desc = (
                human_delta(datetime.timedelta(seconds=self.restart_interval_sec))
                if self.restart_interval_sec > 0
                else "Disabled"
            )
            logger.info(f"Scheduler settings:")
            logger.info("")
            logger.info(f"  Restart interval: {restart_interval_desc} (safety)")
            logger.info(f"  Run at once :     {self.run_at_once}")
            logger.info(f"  Start time :      {self.continuous_prediction_start_time}")
            logger.info(
                f"  Interval:         {human_delta(self.continuous_prediction_interval)}"
            )
            logger.info(
                f"  Data delay:       {human_delta(self.continuous_prediction_delay)}"
            )
            logger.info(
                f"  Backfill max:     {human_delta(self.back_fill_max_interval)}"
            )
            logger.info(f"  Next start:       {next_start}")
            logger.info(f"  Projects:         {', '.join(self.projects)}")
            logger.info("")

    def __init__(self, config: dict):
        self.good_to_go = True
        if not config:
            self._fail("No config specified")
        self.config = config
        self._prepare_task_queue()
        self._prepare_model_info()
        self._perform_auth_check()
        self._prepare_scheduler()
        self.task_serial = 0

    def update_model_info(self):
        stats_start_time = datetime.datetime.now()
        self.models = self.model_info_provider.get_all_models(projects=self.projects)
        if None == self.models:
            logger.error("Could not get models from model info")
        if len(self.models) < 1:
            logger.warning("No models found")
        else:
            stats_interval = datetime.datetime.now() - stats_start_time
            logger.info(
                f"Found {len(self.models)} models in {human_delta(stats_interval)}"
            )

    def perform_prediction_step(self):
        stats_projects_ok = {}
        stats_models_ok = {}
        stats_projects_bad = {}
        stats_models_bad = {}
        stats_start_time = datetime.datetime.now()
        prediction_start_time = (
            datetime.datetime.now() - self.continuous_prediction_delay
        )
        prediction_end_time = (
            prediction_start_time + self.continuous_prediction_interval
        )
        for model in self.models:
            project_name = model.project_name
            if not project_name:
                logger.warning("No project name found for model, skipping model")
                continue
            model_name = model.model_name
            if not model_name:
                logger.warning(
                    f"No model name found for model in project {project_name}, skipping model"
                )
                continue
            task = Task(
                project_name=project_name,
                model_name=model_name,
                from_time=prediction_start_time,
                to_time=prediction_end_time,
            )
            try:
                self.task_queue.put_task(task)
                self.task_serial += 1
                # logger.info(f"Enqueued '{model_name}' in '{project_name}'")
                stats_projects_ok[project_name] = (
                    stats_projects_ok.get(project_name, 0) + 1
                )
                stats_models_ok[model_name] = stats_models_ok.get(model_name, 0) + 1
            except Exception as e:
                # logger.error(f"Could not send task: {e}")
                # traceback.print_exc()
                stats_projects_bad[project_name] = (
                    stats_projects_bad.get(project_name, "") + f", {e}"
                )
                stats_models_bad[model_name] = (
                    stats_models_bad.get(model_name, "") + f", {e}"
                )
                raise e
        stats_interval = datetime.datetime.now() - stats_start_time
        logger.info(
            f"Scheduled {len(stats_models_ok)} models over {len(stats_projects_ok)} projects in {human_delta(stats_interval)}"
        )
        if len(stats_models_bad) > 0 or len(stats_projects_bad) > 0:
            logger.error(
                f"          {len(stats_models_bad)} models in {len(stats_projects_bad)} projects failed"
            )
            for name in stats_models_bad:
                logger.error(f"          + {name}({stats_models_bad[name]})")

    def on_time(self):
        try:
            start = datetime.datetime.now()
            self.update_model_info()
            self.perform_prediction_step()
            interval = datetime.datetime.now() - start
            logger.info(f"Scheduling took {human_delta(interval)}")
            if interval < datetime.timedelta(seconds=1):
                sleep(interval.total_seconds())
        except KeyboardInterrupt:
            logger.info("Keyboard abort triggered, shutting down")
            done = True
        except Exception as e:
            logger.error("-----------------------------------")
            logger.error(f"Error occurred in scheduler: {e}")
            traceback.print_exc()
            logger.error("")
            logger.error("-----------------------------------")

    def run(self):
        if not self.good_to_go:
            sleep_time = 20
            logger.error("")
            logger.error(" ### ### Latigo could not be started!")
            logger.error(
                f"         Will pause for {sleep_time} seconds before terminating."
            )
            logger.error("         Please see previous error messages for clues.")
            logger.error("")
            sleep(sleep_time)
            return
        logger.info("Scheduler started processing")
        done = False
        start = datetime.datetime.now()
        if self.run_at_once:
            self.on_time()
        while not done:
            logger.info(
                f"Next prediction will occur at {self.continuous_prediction_timer.closest_start_time()} (in {human_delta(self.continuous_prediction_timer.time_left())})"
            )
            if self.continuous_prediction_timer.wait_for_trigger(now=start):
                self.on_time()
            scheduler_interval = datetime.datetime.now() - start
            if (
                self.restart_interval_sec > 0
                and scheduler_interval.total_seconds() > self.restart_interval_sec
            ):
                logger.info("Terminating scheduler for teraputic restart")
                done = True
        interval = datetime.datetime.now() - start
        logger.info(f"Scheduler stopped processing after {human_delta(interval)}")
