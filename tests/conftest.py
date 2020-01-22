# This setup is necessary as "tests/" folder is not inside "app/"

import os
import sys

import pandas as pd
import pytest

from .mock_classes import MockSensorDataProvider

latigo_path: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/"))


sys.path.insert(0, latigo_path)
sys.path.insert(0, "/private/lroll/Desktop/ioc_client/latigo/app/latigo")
sys.path.insert(0, "/private/lroll/Desktop/ioc_client/latigo/app")


@pytest.fixture
def auth_config():
    return {
        "resource": "dummy-resource",
        "tenant": "dummy-tenant",
        "authority_host_url": "dummy-authority",
        "client_id": "dummy-client",
        "client_secret": "dummy-secret",
    }


@pytest.fixture
def config(auth_config):
    return {
        "executor": {"instance_count": 1},
        "task_queue": {
            "type": "mock",
            "connection_string": "dummy",
            "security.protocol": "SASL_SSL",
            "ssl.ca.location": "/etc/ssl/certs/ca-certificates.crt",
            "sasl.mechanism": "PLAIN",
            "group.id": "1",
            "client.id": "executor",
            "request.timeout.ms": 10000,
            "session.timeout.ms": 10000,
            "default.topic.config": {"auto.offset.reset": "smallest"},
            "debug": "fetch",
            "topic": "latigo_topic",
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 1000,
        },
        "sensor_data": {
            "type": "mock",
            "base_url": "dummy",
            "async": False,
            "auth": auth_config,
            "mock_data": [pd.Series(data=[1, 2, 3, 4, 5])],
        },
        "prediction_storage": {
            "type": "mock",
            "base_url": "dummy",
            "async": False,
            "auth": auth_config,
            "mock_data": [pd.Series(data=[1, 2, 3, 4, 5])],
        },
        "model_info": {
            "type": "mock",
            "connection_string": "dummy",
            "projects": ["project-1", "project-2"],
            "target": None,
            "metadata": None,
            "batch_size": 1000,
            "parallelism": 10,
            "forward_resampled_sensors": False,
            "ignore_unhealthy_targets": True,
            "n_retries": 5,
            "data_provider": {"debug": True, "n_retries": 5},
            "prediction_forwarder": {"debug": False, "n_retries": 5},
            "auth": auth_config,
        },
        "predictor": {
            "type": "mock",
            "connection_string": "dummy",
            "target": None,
            "metadata": None,
            "batch_size": 1000,
            "parallelism": 10,
            "forward_resampled_sensors": False,
            "ignore_unhealthy_targets": True,
            "n_retries": 5,
            "data_provider": {"debug": True, "n_retries": 5},
            "prediction_forwarder": {"debug": False, "n_retries": 5},
            "auth": auth_config,
        },
    }


@pytest.fixture
def sensor_data_provider(config):
    return MockSensorDataProvider(config.get("sensor_data"))


@pytest.fixture
def prediction_forwarder(MockPredictionStorageProvider):
    return MockPredictionStorageProvider(config.get("prediction_storage"))
