import latigo.clock
import datetime
import time
import typing
import logging

logger = logging.getLogger(__name__)


def test_clock():
    start_time = datetime.time(8, 0, 0)
    interval = datetime.timedelta(minutes=15)
    clock = latigo.clock.OnTheClockTimer(start_time=start_time, interval=interval)
    now = datetime.datetime.combine(datetime.date.today(), datetime.time(8, 5, 0))
    closest = clock.closest_start_time(now=now)
    logger.info(f"CLOSEST: {closest}")
    expected = datetime.datetime.combine(datetime.date.today(), start_time) + interval
    assert closest == expected
