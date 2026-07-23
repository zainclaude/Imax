"""Tests for the hourly horizon check-in and interval config parsing."""

import time

from amc_monitor.config import Config, _optional_hours
from amc_monitor.monitor import _fresh_state, _maybe_heartbeat
from tests.test_auth import env


class FakeNotifier:
    def __init__(self):
        self.bodies = []

    def send(self, body, subject=None):
        self.bodies.append(body)
        return ["ok"]


def _cfg(hours):
    cfg = Config()
    cfg.heartbeat_hours = hours
    return cfg


def test_optional_hours_parsing():
    with env(HEARTBEAT_HOURS=None):
        assert _optional_hours("HEARTBEAT_HOURS", 1.0) == 1.0  # unset -> default
    with env(HEARTBEAT_HOURS=""):
        assert _optional_hours("HEARTBEAT_HOURS", 1.0) is None  # empty -> disabled
    with env(HEARTBEAT_HOURS="2"):
        assert _optional_hours("HEARTBEAT_HOURS", 1.0) == 2.0
    with env(HEARTBEAT_HOURS="0.01"):
        assert _optional_hours("HEARTBEAT_HOURS", 1.0) == 0.25  # floor


def test_heartbeat_disabled():
    state = _fresh_state()
    notifier = FakeNotifier()
    assert _maybe_heartbeat(_cfg(None), notifier, state) is False
    assert notifier.bodies == []


def test_first_heartbeat_fires_immediately():
    state = _fresh_state()
    state["seen_dates"] = ["2026-08-16", "2026-08-17"]
    notifier = FakeNotifier()
    assert _maybe_heartbeat(_cfg(1.0), notifier, state) is True
    assert "furthest bookable date is Mon Aug 17" in notifier.bodies[0]


def test_heartbeat_suppressed_within_interval_then_fires():
    state = _fresh_state()
    state["seen_dates"] = ["2026-08-17"]
    notifier = FakeNotifier()
    cfg = _cfg(1.0)

    assert _maybe_heartbeat(cfg, notifier, state) is True
    assert _maybe_heartbeat(cfg, notifier, state) is False  # too soon

    state["last_heartbeat_epoch"] = time.time() - 3700  # >1h ago
    state["polls_since_heartbeat"] = 20
    assert _maybe_heartbeat(cfg, notifier, state) is True

    assert len(notifier.bodies) == 2
    assert "still Mon Aug 17" in notifier.bodies[1]  # unchanged horizon says "still"
    assert "20 polls" in notifier.bodies[1]
    assert state["polls_since_heartbeat"] == 0


def test_heartbeat_reports_horizon_change():
    state = _fresh_state()
    state["seen_dates"] = ["2026-08-16"]
    notifier = FakeNotifier()
    cfg = _cfg(1.0)
    _maybe_heartbeat(cfg, notifier, state)

    state["seen_dates"].append("2026-08-17")
    state["last_heartbeat_epoch"] = time.time() - 3700
    _maybe_heartbeat(cfg, notifier, state)

    assert "now Mon Aug 17 (was Sun Aug 16)" in notifier.bodies[1]


def test_heartbeat_before_any_showtimes():
    state = _fresh_state()
    notifier = FakeNotifier()
    assert _maybe_heartbeat(_cfg(1.0), notifier, state) is True
    assert "no booking horizon" in notifier.bodies[0]
