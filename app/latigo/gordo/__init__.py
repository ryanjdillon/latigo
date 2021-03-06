import typing
import random
import logging
import pprint
import numpy as np
import pandas as pd
import requests
import json
from datetime import datetime
import latigo.utils
from latigo.prediction_execution import PredictionExecutionProviderInterface

from latigo.types import TimeRange, SensorDataSpec, SensorData, PredictionData
from latigo.sensor_data import SensorDataProviderInterface

from latigo.model_info import ModelInfoProviderInterface, Model
from latigo.auth import create_auth_session

from latigo.gordo.client import Client

# from gordo_components.client.client import Client

from gordo_components.data_provider.base import GordoBaseDataProvider, capture_args
from gordo_components.client.utils import EndpointMetadata
from gordo_components.dataset.sensor_tag import SensorTag


logger = logging.getLogger(__name__)
# logging.getLogger().setLevel(logging.WARNING)

gordo_client_instances_by_hash: dict = {}
gordo_client_instances_by_project: dict = {}
gordo_client_auth_session: typing.Optional[requests.Session] = None
gordo_client_config = None

# Defeat dependency on gordo
def _gordo_to_latigo_tag_list(gordo_tag_list):
    return gordo_tag_list


class PredictionForwarder:
    def __call__(self, *, predictions: pd.DataFrame = None, endpoint: EndpointMetadata = None, metadata: dict = dict(), resampled_sensor_data: pd.DataFrame = None) -> typing.Awaitable[None]:
        ...


class LatigoDataProvider(GordoBaseDataProvider):
    """
    A GordoBaseDataProvider that wraps Latigo spesific data providers
    """

    @capture_args
    def __init__(self, sensor_data_provider: typing.Optional[SensorDataProviderInterface], config: dict):
        super().__init__()
        self.config = config
        if not self.config:
            raise Exception("No data_provider_config specified")
        self.sensor_data_provider = sensor_data_provider

    def load_series(self, from_ts: datetime, to_ts: datetime, tag_list: typing.List[SensorTag], dry_run: typing.Optional[bool] = False) -> typing.Iterable[pd.Series]:
        if self.sensor_data_provider:
            if isinstance(self.sensor_data_provider, str):
                raise Exception(f"IS STR: '{self.sensor_data_provider}'")
            spec: SensorDataSpec = SensorDataSpec(tag_list=_gordo_to_latigo_tag_list(tag_list))
            time_range = TimeRange(from_ts, to_ts)
            sensor_data, err = self.sensor_data_provider.get_data_for_range(spec, time_range)
            if sensor_data and sensor_data.ok():
                logger.info(f"Providing data: ")
                logger.info(pprint.pformat(sensor_data.data))
                for item in sensor_data.data:
                    yield item
            else:
                logger.warning(f"Could not load series: {err}")

    def can_handle_tag(self, tag: SensorTag) -> bool:
        if self.sensor_data_provider:
            # TODO: Actually implement this
            return True
        return False


class LatigoPredictionForwarder(PredictionForwarder):
    """
    A Gordo PredictionForwarder that wraps Latigo spesific prediction forwarders
    """

    def __init__(self, prediction_storage, config):
        super().__init__()
        self.config = config
        if not self.config:
            raise Exception("No prediction_forwarder_config specified")
        self.prediction_storage = prediction_storage


def gordo_config_hash(config: dict):
    key = "gordo"
    # fmt: off
    parts = [
        "scheme",
        "host",
        "port",
        "project",
        "target",
        "gordo_version",
        "batch_size",
        "parallelism",
        "forward_resampled_sensors",
        "ignore_unhealthy_targets",
        "n_retries"
    ]
    # fmt: on
    if config:
        for part in parts:
            key += part + str(config.get(part, ""))
    return key


def clean_gordo_client_args(raw: dict):
    # fmt: off
    whitelist = [
        "project",
        "target",
        "host",
        "port",
        "scheme",
        "gordo_version",
        "metadata",
        "data_provider",
        "prediction_forwarder",
        "batch_size",
        "parallelism",
        "forward_resampled_sensors",
        "ignore_unhealthy_targets",
        "n_retries",
        "session"
    ]
    # fmt: on
    args = {}
    for w in whitelist:
        args[w] = raw.get(w)
    return args


def get_auth_session(auth_config: dict):
    global gordo_client_auth_session
    if not gordo_client_auth_session:
        # logger.info("CREATING SESSION:")
        gordo_client_auth_session = create_auth_session(auth_config)
    return gordo_client_auth_session


def expand_gordo_connection_string(config: dict):
    if "connection_string" in config:
        connection_string = config.pop("connection_string")
        parts = latigo.utils.parse_gordo_connection_string(connection_string)
        if parts:
            config.update(parts)
        else:
            raise Exception(f"Could not parse gordo connection string: {connection_string}")


def expand_gordo_data_provider(config: dict, sensor_data: typing.Optional[SensorDataProviderInterface]):
    data_provider_config = config.get("data_provider", {})
    config["data_provider"] = LatigoDataProvider(sensor_data, data_provider_config)


def expand_gordo_prediction_forwarder(config: dict, prediction_storage):
    prediction_forwarder_config = config.get("prediction_forwarder", {})
    config["prediction_forwarder"] = LatigoPredictionForwarder(prediction_storage, prediction_forwarder_config)


def allocate_gordo_client_instance(raw_config: dict, project: str):
    client = gordo_client_instances_by_project.get(project, None)
    if not client:
        auth_config = raw_config.get("auth", dict())
        session = get_auth_session(auth_config)
        config = {**raw_config}
        config["project"] = project
        config["session"] = session
        key = gordo_config_hash(config)
        # logger.info(f" + Instanciating Gordo Client: {key}")
        client = gordo_client_instances_by_hash.get(key, None)
        if not client:
            clean_config = clean_gordo_client_args(config)
            try:
                client = Client(**clean_config)
                gordo_client_instances_by_hash[key] = client
                gordo_client_instances_by_project[project] = client
            except requests.exceptions.HTTPError as http_error:
                if 404 == http_error.response.status_code:
                    logger.warning(f"Skipping client allocation for {project}, project not found")
                else:
                    logger.error(f"Skipping client allocation for {project} due to HTTP error '{http_error}'")
            except Exception as error:
                logger.error(f"Skipping client allocation for {project} due to unknown error '{error}'")
                logger.error(f"NOTE: Using config {pprint.pformat(clean_config)}")
    return client


def allocate_gordo_client_instances(raw_config: dict):
    global gordo_client_config
    gordo_client_config = raw_config
    projects = raw_config.get("projects", [])
    if not isinstance(projects, list):
        projects = [projects]
    for project in projects:
        allocate_gordo_client_instance(raw_config, project)


def _get_model_meta(model: dict):
    meta = model.get("endpoint-metadata", {}).get("metadata", {})
    # logger.info("MODEL META:"+pprint.pformat(meta))
    return meta


def _get_model_tag_list(model: dict):
    meta = _get_model_meta(model)
    tag_list = meta.get("dataset", {}).get("tag_list", {})
    # logger.info("MODEL 0 META TAG_LIST:"+pprint.pformat(tag_list))
    return tag_list


def _get_model_target_tag_list(model: dict):
    meta = _get_model_meta(model)
    target_tag_list = meta.get("dataset", {}).get("target_tag_list", {})
    # logger.info("MODEL 0 META TAG_LIST:"+pprint.pformat(tag_list))
    return target_tag_list


def _get_model_name(model: dict):
    model_name = model.get("name", "")
    # logger.info(f"MODEL NAME: {name}")
    return model_name


def _get_project_name(model: dict):
    project_name = model.get("project", "")
    # logger.info(f"MODEL NAME: {name}")
    return project_name


class GordoModelInfoProvider(ModelInfoProviderInterface):
    def _prepare_auth(self):
        self.auth_config = self.config.get("auth")
        if not self.auth_config:
            raise Exception("No auth_config specified")

    def __init__(self, config):
        self.config = config
        if not self.config:
            raise Exception("No model_info_config specified")
        self._prepare_auth()
        expand_gordo_connection_string(self.config)

    def get_models_data(self, projects: typing.Optional[typing.List] = None, model_names: typing.Optional[typing.List] = None):
        models = []
        if not projects:
            projects = self.config.get("projects", [])
            if not isinstance(projects, list):
                projects = [projects]
        for project_name in projects:
            # logger.info(f"LOOKING AT PROJECT {project_name}")
            client = allocate_gordo_client_instance(self.config, project_name)
            if client:
                meta_data = client.get_metadata()
                for model_name, model_data in meta_data.items():
                    if model_names and model_name not in model_names:
                        continue
                    model_data["model_name"] = model_name
                    model_data["project_name"] = project_name
                    models.append(model_data)
            else:
                logger.error(f"No client found for project '{project_name}', skipping")
        return models

    def get_all_models(self, projects: typing.List):
        models_data = self.get_models_data(projects)
        models = []
        for model_data in models_data:
            model = Model(project_name=model_data.get("project_name", "unnamed"), model_name=model_data.get("model_name", "unnamed"), tag_list=_get_model_tag_list(model_data), target_tag_list=_get_model_target_tag_list(model_data))
            models.append(model)
        return models

    def get_model_by_key(self, project_name: str, model_name: str):
        models_data = self.get_models_data(projects=[project_name], model_names=[model_name])
        if not models_data:
            return None
        model = None
        model_data = models_data[0]
        if model_data:
            model = Model(project_name=model_data.get("project_name", "unnamed"), model_name=model_data.get("model_name", "unnamed"), tag_list=_get_model_tag_list(model_data), target_tag_list=_get_model_target_tag_list(model_data))
        return model

    def get_spec(self, project_name: str, model_name: str) -> typing.Optional[SensorDataSpec]:
        model = self.get_model_by_key(project_name=project_name, model_name=model_name)
        if not model:
            return None
        spec = SensorDataSpec(tag_list=model.tag_list)
        return spec


def print_client(client):
    if not client:
        logger.info("Client: None")
        return
    logger.info("Client:----------------")
    # fmt: off
    data = {
    "base_url": client.base_url,
    "watchman_endpoint": client.watchman_endpoint,
    "metadata": client.metadata,
    "prediction_forwarder": client.prediction_forwarder,
    "data_provider": client.data_provider,
    "use_parquet": client.use_parquet,
    "session": client.session,
    "prediction_path": client.prediction_path,
    "batch_size": client.batch_size,
    "parallelism": client.parallelism,
    "forward_resampled_sensors": client.forward_resampled_sensors,
    "n_retries": client.n_retries,
    "query": client.query,
    "target": client.target,
    "ignore_unhealthy_targets": client.ignore_unhealthy_targets,
    #"endpoints": client.endpoints
    }
    # fmt: on
    logger.info(pprint.pformat(data))
    logger.info("-----------------------")


class GordoPredictionExecutionProvider(PredictionExecutionProviderInterface):
    def _prepare_projects(self):
        self.projects = self.config.get("projects", [])
        if not isinstance(self.projects, list):
            self.projects = [self.projects]

    def __init__(self, sensor_data, prediction_storage, config):
        self.config = config
        if not self.config:
            raise Exception("No predictor_config specified")
        expand_gordo_connection_string(self.config)
        expand_gordo_data_provider(config, sensor_data)
        expand_gordo_prediction_forwarder(config, prediction_storage)
        self._prepare_projects()

    def execute_prediction(self, project_name: str, model_name: str, sensor_data: SensorData) -> PredictionData:
        if not project_name:
            raise Exception("No project_name in gordo.execute_prediction()")
        if not model_name:
            raise Exception("No model_name in gordo.execute_prediction()")
        if not sensor_data:
            raise Exception("No sensor_data in gordo.execute_prediction()")
        client = allocate_gordo_client_instance(self.config, project_name)
        if not client:
            raise Exception(f"No gordo client found for project '{project_name}' in gordo.execute_prediction()")
        logger.info("STARTING PREDICTION WITH CLIENT: ------")
        # logger.info(pprint.pformat(client.__dict__))
        print_client(client)
        logger.info(f"PREDICTION: start={sensor_data.time_range.from_time}  end={sensor_data.time_range.to_time}")

        result = client.predict(start=sensor_data.time_range.from_time, end=sensor_data.time_range.to_time)
        if not result:
            raise Exception("No result in gordo.execute_prediction()")
        return PredictionData(name=model_name, time_range=sensor_data.time_range, data=result)
