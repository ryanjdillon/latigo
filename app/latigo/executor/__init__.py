import datetime
import time
import traceback
import typing
import logging
import pprint
from latigo.types import (
    Task,
    SensorDataSpec,
    SensorDataSet,
    TimeRange,
    PredictionDataSet,
    LatigoSensorTag,
)
from latigo.sensor_data import sensor_data_provider_factory

from latigo.prediction_execution import prediction_execution_provider_factory
from latigo.prediction_storage import prediction_storage_provider_factory
from latigo.task_queue import task_queue_receiver_factory
from latigo.model_info import model_info_provider_factory
from latigo.utils import sleep, human_delta
from latigo.auth import AuthVerifier

logger = logging.getLogger(__name__)


class PredictionExecutor:
    def __init__(self, config: dict):
        self.good_to_go = True
        self.config = config
        self._prepare_task_queue()
        self._prepare_sensor_data_provider()
        self._prepare_prediction_storage_provider()
        self._prepare_model_info()
        self._prepare_prediction_executor_provider()
        self._prepare_executor()
        self._perform_auth_check()

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
        self.task_queue = task_queue_receiver_factory(self.task_queue_config)
        self.idle_time = datetime.datetime.now()
        self.idle_number = 0
        if not self.task_queue:
            self._fail("No task queue configured")

    # Inflate sensor data provider from config
    def _prepare_sensor_data_provider(self):
        self.sensor_data_provider_config = self.config.get("sensor_data", None)
        if not self.sensor_data_provider_config:
            self._fail("No sensor_data_config specified")
        self.sensor_data_provider = sensor_data_provider_factory(
            self.sensor_data_provider_config
        )
        if not self.sensor_data_provider:
            self._fail(f"No sensor data configured: {err}, cannot continue...")

    # Inflate prediction storage provider from config
    def _prepare_prediction_storage_provider(self):
        self.prediction_storage_provider_config = self.config.get(
            "prediction_storage", None
        )
        if not self.prediction_storage_provider_config:
            self._fail("No prediction_storage_config specified")
        self.prediction_storage_provider = prediction_storage_provider_factory(
            self.prediction_storage_provider_config
        )
        if not self.prediction_storage_provider:
            self._fail(f"No prediction storage configured: {err}, cannot continue...")

    # Inflate prediction executor provider from config
    def _prepare_prediction_executor_provider(self):
        self.prediction_executor_provider_config = self.config.get("predictor", None)
        if not self.prediction_executor_provider_config:
            self._fail("No prediction_executor_provider_config specified")
        prediction_executor_provider_type = self.prediction_executor_provider_config.get(
            "type", None
        )
        self.prediction_executor_provider_connection_string = self.prediction_executor_provider_config.get(
            "connection_string",
            "no connection string set for prediction execution prvider",
        )
        # NOTE: This is a hack. We need a project appended to the URL for it to be valid, but there is no guarantee that the project has been set up with lat-lit project
        self.prediction_executor_provider_connection_string += "/lat-lit/"
        self.prediction_executor_provider = prediction_execution_provider_factory(
            self.sensor_data_provider,
            self.prediction_storage_provider,
            self.prediction_executor_provider_config,
        )
        self.name = self.prediction_executor_provider_config.get("name", "executor")
        if not self.prediction_executor_provider:
            self._fail(
                f"No prediction_executor_provider configured: {err}, cannot continue..."
            )

    # Perform a basic authentication test up front to fail early with clear error output
    def _perform_auth_check(self):
        # fmt: off
        verifiers = [
            (self.model_info_connection_string, AuthVerifier(config=self.model_info_config.get("auth", {}))),
            (self.sensor_data_provider_config.get('base_url','no_base_url'), AuthVerifier(config=self.sensor_data_provider_config.get("auth", {}))),
            (self.prediction_storage_provider_config.get('base_url','no_base_url'), AuthVerifier(config=self.prediction_storage_provider_config.get("auth", {}))),
            (self.prediction_executor_provider_connection_string, AuthVerifier(config=self.prediction_executor_provider_config.get("auth", {}))),
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

    # Inflate executor from config
    def _prepare_executor(self):
        self.executor_config = self.config.get("executor", {})
        if not self.executor_config:
            self._fail("No executor config specified")
        self.instance_count = self.executor_config.get("instance_count", 1)
        if not self.instance_count:
            self._fail("No instance count configured")
        self.restart_interval_sec = self.executor_config.get(
            "restart_interval_sec", 60 * 60 * 6
        )
        if self.good_to_go:
            pass
            # Refraining from excessive logging
            # logger.info(f"Executor settings:")
            # logger.info("")
            # logger.info(f"  Restart interval: {self.restart_interval_sec} (safety)")

    def _fetch_spec(self, project_name: str, model_name: str):
        return self.model_info_provider.get_spec(
            project_name=project_name, model_name=model_name
        )

    def _fetch_task(self) -> typing.Optional[Task]:
        """
        The task describes what the executor is supposed to do. This internal helper fetches one task from event hub
        """
        task = None
        try:
            if self.task_queue:
                task = self.task_queue.get_task()
            else:
                logger.warning(f"No task queue")
        except Exception as e:
            logger.error(f"Could not fetch task: {e}")
            raise e
        return task

    def _fetch_sensor_data(self, task: Task) -> typing.Optional[SensorDataSet]:
        """
        Sensor data is input to prediction. This internal helper fetches one bulk of sensor data
        """
        sensor_data = None
        try:
            time_range: TimeRange = TimeRange(task.from_time, task.to_time)
            project_name: str = task.project_name
            model_name: str = task.model_name
            spec: SensorDataSpec = self._fetch_spec(project_name, model_name)
            if spec:
                sensor_data, err = self.sensor_data_provider.get_data_for_range(
                    spec, time_range
                )
                if not sensor_data:
                    logger.warning(f"Error getting sensor data: {err}")
                elif not sensor_data.ok():
                    logger.warning(f"Sensor data '{sensor_data}' was not ok")
            else:
                logger.warning(
                    f"Error getting spec for project={project_name} and model={model_name}"
                )
        except Exception as e:
            logger.error(
                f"Could not fetch sensor data for task '{task.project_name}.{task.model_name}': {e}"
            )
            traceback.print_exc()
        return sensor_data

    def _execute_prediction(
        self, task: Task, sensor_data: SensorDataSet
    ) -> typing.Optional[PredictionDataSet]:
        """
        This internal helper executes prediction on one bulk of data
        """
        prediction_data = None
        try:
            prediction_data = self.prediction_executor_provider.execute_prediction(
                project_name=task.project_name,
                model_name=task.model_name,
                sensor_data=sensor_data,
            )
        except Exception as e:
            logger.error(
                f"Could not execute prediction for task '{task.project_name}.{task.model_name}': {e}"
            )
            raise e
            # traceback.print_exc()
        return prediction_data

    def _store_prediction_data(self, task, prediction_data: PredictionDataSet):
        """
        Prediction data represents the result of performing predictions on sensor data. This internal helper stores one bulk of prediction data to the store
        """
        try:
            self.prediction_storage_provider.put_predictions(prediction_data)
        except Exception as e:
            logger.error(
                f"Could not store prediction data for task '{task.project_name}.{task.model_name}': {e}"
            )
            raise e
            # traceback.print_exc()

    def idle_count(self, has_task):
        if self.idle_number > 0:
            logger.info(
                f"Idle for {self.idle_number} cycles ({human_delta(datetime.datetime.now()-self.idle_time)})"
            )
            self.idle_number = 0
            self.idle_time = datetime.datetime.now()
        else:
            self.idle_number += 1

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
        if self.task_queue:
            # Refraining from excessive logging
            # logger.info("Executor started processing")
            done = False
            iteration_number = 0
            error_number = 0
            first_sleep: bool = True
            executor_start = datetime.datetime.now()
            while not done:
                iteration_number += 1
                try:
                    # logger.info("Fetching task...")
                    task_fetch_start = datetime.datetime.now()
                    task = self._fetch_task()
                    if task:
                        task_fetch_interval = datetime.datetime.now() - task_fetch_start
                        logger.info(
                            f"Processing task fetched after {human_delta(task_fetch_interval)} starting {task.from_time} lasting {task.to_time - task.from_time} for '{task.model_name}' in '{task.project_name}'"
                        )
                        sensor_data = self._fetch_sensor_data(task)
                        data_fetch_interval = datetime.datetime.now() - task_fetch_start
                        logger.info(
                            f"Got data after {human_delta(data_fetch_interval)}"
                        )
                        if sensor_data and sensor_data.ok():
                            prediction_data = self._execute_prediction(
                                task, sensor_data
                            )
                            prediction_execution_interval = (
                                datetime.datetime.now() - task_fetch_start
                            )
                            logger.info(
                                f"Prediction completed after {human_delta(prediction_execution_interval)}"
                            )
                            if prediction_data and prediction_data.ok():
                                self._store_prediction_data(task, prediction_data)
                                prediction_storage_interval = (
                                    datetime.datetime.now() - task_fetch_start
                                )
                                logger.info(
                                    f"Prediction stored after {human_delta(prediction_storage_interval)}"
                                )
                                self.idle_count(True)
                            else:
                                logger.warning(
                                    f"Skipping store due to bad prediction: {prediction_data.data}"
                                )
                        else:
                            logger.warning(
                                f"Skipping prediciton due to bad data: {sensor_data}"
                            )
                    else:
                        logger.warning(f"No task")
                        self.idle_count(False)
                        sleep(1)
                except Exception as e:
                    error_number += 1
                    logger.error("-----------------------------------")
                    logger.error(f"Error occurred in executor: {e}")
                    traceback.print_exc()
                    logger.error("")
                    logger.error("-----------------------------------")
                    sleep(1)
            executor_interval = datetime.datetime.now() - executor_start
            if (
                self.restart_interval_sec > 0
                and executor_interval.total_seconds() > self.restart_interval_sec
            ):
                logger.info("Terminating executor for teraputic restart")
                done = True
            # logger.info("Executor stopped processing")
        else:
            logger.error("No task queue")
