import typing
import pprint
import logging
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass
import latigo.utils


from latigo.types import SensorDataSet, TimeRange, SensorDataSpec, LatigoSensorTag
from latigo.intermediate import IntermediateFormat


logger = logging.getLogger(__name__)


class SensorDataProviderInterface:
    def supports_tag(self, tag: LatigoSensorTag) -> bool:
        pass

    def get_data_for_range(
        self, spec: SensorDataSpec, time_range: TimeRange
    ) -> typing.Tuple[typing.Optional[SensorDataSet], typing.Optional[str]]:
        """
        return the actual data as per the range specified
        """
        pass


class DevNullSensorDataProvider(SensorDataProviderInterface):
    def __init__(self, config: dict):
        self.config = config

    def get_data_for_range(
        self, spec: SensorDataSpec, time_range: TimeRange
    ) -> typing.Tuple[typing.Optional[SensorDataSet], typing.Optional[str]]:
        """
        return the actual data as per the range specified
        """
        return None, "No data"


def sensor_data_provider_factory(sensor_data_provider_config):
    sensor_data_provider_type = sensor_data_provider_config.get("type", None)
    sensor_data_provider = None

    if "time_series_api" == sensor_data_provider_type:
        from latigo.time_series_api import TimeSeriesAPISensorDataProvider

        sensor_data_provider = TimeSeriesAPISensorDataProvider(
            sensor_data_provider_config
        )
    else:
        sensor_data_provider = DevNullSensorDataProvider(sensor_data_provider_config)
    return sensor_data_provider
