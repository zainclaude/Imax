"""Tests for local-date mapping and the 'new date bookable' alert mode."""

from amc_monitor.amc_client import Showtime
from amc_monitor.config import Config
from amc_monitor.dates import local_date_of, pretty_date
from amc_monitor.monitor import _alert_new_dates, _fresh_state


class FakeNotifier:
    def __init__(self):
        self.bodies = []

    def send(self, body):
        self.bodies.append(body)
        return ["SM_fake"]


def _show(sid, when_iso, fmt="IMAX 70mm"):
    return Showtime(
        id=sid,
        movie_title="The Odyssey",
        format_label=fmt,
        when_iso=when_iso,
        seatmap_url=None,
        purchase_url=f"https://amc.example/{sid}",
    )


def test_local_date_utc_overnight_maps_to_previous_eastern_day():
    # 02:00 UTC on the 25th is 22:00 EDT on the 24th.
    assert local_date_of("2026-07-25T02:00:00Z") == "2026-07-24"


def test_local_date_naive_taken_as_local():
    assert local_date_of("2026-08-17T19:30:00") == "2026-08-17"


def test_local_date_plain_date_prefix():
    assert local_date_of("2026-08-17") == "2026-08-17"


def test_local_date_unparseable_is_none():
    assert local_date_of("not-a-date") is None


def test_pretty_date():
    assert pretty_date("2026-08-17") == "Mon Aug 17"


def test_first_run_seeds_horizon_without_alerting():
    cfg = Config()
    state = _fresh_state()
    notifier = FakeNotifier()
    shows = [_show("a", "2026-08-15T19:00:00"), _show("b", "2026-08-16T19:00:00")]

    sent, changed = _alert_new_dates(cfg, notifier, state, shows)

    assert sent == 0
    assert changed is True
    assert notifier.bodies == []  # silent on the dates already for sale
    assert state["dates_seeded"] is True
    assert set(state["seen_dates"]) == {"2026-08-15", "2026-08-16"}


def test_new_date_after_seed_triggers_one_alert():
    cfg = Config()
    state = _fresh_state()
    notifier = FakeNotifier()
    seed = [_show("a", "2026-08-16T19:00:00")]
    _alert_new_dates(cfg, notifier, state, seed)  # seeds 08-16

    # Aug 17 shows up: two showtimes on the new day.
    later = seed + [_show("b", "2026-08-17T19:00:00"), _show("c", "2026-08-17T22:00:00")]
    sent, changed = _alert_new_dates(cfg, notifier, state, later)

    assert sent == 1  # one text for the new date, not one per showtime
    assert changed is True
    assert len(notifier.bodies) == 1
    body = notifier.bodies[0]
    assert "New date bookable" in body
    assert "Mon Aug 17" in body
    assert "2 showtimes" in body
    assert "2026-08-17" in state["seen_dates"]


def test_new_date_not_re_alerted():
    cfg = Config()
    state = _fresh_state()
    notifier = FakeNotifier()
    _alert_new_dates(cfg, notifier, state, [_show("a", "2026-08-16T19:00:00")])
    later = [_show("a", "2026-08-16T19:00:00"), _show("b", "2026-08-17T19:00:00")]
    _alert_new_dates(cfg, notifier, state, later)  # alerts once
    sent, _ = _alert_new_dates(cfg, notifier, state, later)  # same data again
    assert sent == 0
    assert len(notifier.bodies) == 1
