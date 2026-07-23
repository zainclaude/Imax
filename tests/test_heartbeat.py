"""Tests for the daily heartbeat and heartbeat-hour config parsing."""

from unittest import mock

from amc_monitor.config import Config, _optional_hour
from amc_monitor.monitor import _fresh_state, _maybe_heartbeat
from tests.test_auth import env


class FakeNotifier:
    def __init__(self):
        self.bodies = []

    def send(self, body, subject=None):
        self.bodies.append(body)
        return ["ok"]


def _cfg(hour):
    cfg = Config()
    cfg.heartbeat_hour = hour
    return cfg


def _at_hour(hour):
    """Patch 'now' inside _maybe_heartbeat to a fixed ET datetime."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fixed = datetime(2026, 7, 23, hour, 30, tzinfo=ZoneInfo("America/New_York"))
    dt_mock = mock.Mock()
    dt_mock.now.return_value = fixed
    return mock.patch("datetime.datetime", dt_mock)


def test_optional_hour_parsing():
    with env(HEARTBEAT_HOUR=None):
        assert _optional_hour("HEARTBEAT_HOUR", 9) == 9  # unset -> default
    with env(HEARTBEAT_HOUR=""):
        assert _optional_hour("HEARTBEAT_HOUR", 9) is None  # empty -> disabled
    with env(HEARTBEAT_HOUR="14"):
        assert _optional_hour("HEARTBEAT_HOUR", 9) == 14
    with env(HEARTBEAT_HOUR="99"):
        assert _optional_hour("HEARTBEAT_HOUR", 9) == 23  # clamped


def test_heartbeat_disabled():
    state = _fresh_state()
    notifier = FakeNotifier()
    assert _maybe_heartbeat(_cfg(None), notifier, state) is False
    assert notifier.bodies == []


def test_heartbeat_fires_after_hour_once_per_day():
    state = _fresh_state()
    state["seen_dates"] = ["2026-08-15", "2026-08-16"]
    state["polls_since_heartbeat"] = 42
    notifier = FakeNotifier()

    with _at_hour(10):  # past 9am ET
        assert _maybe_heartbeat(_cfg(9), notifier, state) is True
        assert _maybe_heartbeat(_cfg(9), notifier, state) is False  # same day: no repeat

    assert len(notifier.bodies) == 1
    body = notifier.bodies[0]
    assert "2026-08-16" in body  # reports the horizon
    assert "42" in body  # reports poll count
    assert state["polls_since_heartbeat"] == 0  # counter reset


def test_heartbeat_waits_for_hour():
    state = _fresh_state()
    notifier = FakeNotifier()
    with _at_hour(7):  # before 9am ET
        assert _maybe_heartbeat(_cfg(9), notifier, state) is False
    assert notifier.bodies == []
