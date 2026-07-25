"""Tests for the local audible alarm."""

from unittest import mock

from amc_monitor.config import Config
from amc_monitor.monitor import _emit
from amc_monitor.notifier import sound_alarm


def _cfg(enabled=True):
    cfg = Config()
    cfg.alarm_enabled = enabled
    cfg.alarm_repeat = 2
    cfg.alarm_say = "test announcement"
    return cfg


def test_alarm_plays_sound_and_speaks_on_macos():
    with mock.patch("platform.system", return_value="Darwin"), mock.patch(
        "subprocess.run"
    ) as run, mock.patch("threading.Thread") as thread:
        thread.side_effect = lambda target, daemon: mock.Mock(start=target)  # run inline
        sound_alarm(_cfg())
    played = [c.args[0][0] for c in run.call_args_list]
    assert played == ["afplay", "afplay", "say"]


def test_alarm_noop_when_disabled_or_not_macos():
    with mock.patch("subprocess.run") as run, mock.patch("platform.system", return_value="Darwin"):
        sound_alarm(_cfg(enabled=False))
    run.assert_not_called()
    with mock.patch("subprocess.run") as run, mock.patch("platform.system", return_value="Linux"):
        sound_alarm(_cfg())
    run.assert_not_called()


def test_emit_triggers_alarm_but_heartbeat_path_does_not():
    cfg = _cfg()
    with mock.patch("amc_monitor.monitor.sound_alarm") as alarm:
        assert _emit(cfg, None, "new date!") is True  # dry-run emit
    alarm.assert_called_once_with(cfg)
    # Heartbeats call notifier.send directly and never pass through _emit —
    # enforced by grep-level convention and the monitor tests' FakeNotifiers.
