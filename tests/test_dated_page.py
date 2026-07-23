"""Tests for the dated-page parser and the horizon-walking scan."""

from unittest import mock

from amc_monitor.amc_client import Showtime, parse_dated_page
from amc_monitor.config import Config
from amc_monitor.monitor import _fresh_state, _scan_dated_pages, check_once

THEATRE = "amc-lincoln-square-13"

# Markup shape verified against the live page via probe5 (2026-07).
ANCHOR = (
    '<a class="showtime-anchor {movie}-{theatre}-{fmt}-0 '
    '{movie}-{theatre}-{fmt}-0-attributes" id="{sid}" href="/showtimes/{sid}">'
    '<time dateTime="{dt}">9:00<!-- -->am</time> <span class="sr-only">UP TO 15% OFF</span></a>'
)


def _page(*entries):
    body = "".join(
        ANCHOR.format(movie=m, theatre=THEATRE, fmt=f, sid=s, dt=d) for (m, f, s, d) in entries
    )
    return f"<html><body><ul aria-label='Showtime Group Results'>{body}</ul></body></html>"


ODYSSEY = "the-odyssey-76238"
SPIDER = "spider-man-brand-new-day-78598"


def test_parse_extracts_movie_format_time_and_link():
    html = _page((ODYSSEY, "imax70mm", "144316365", "2026-08-05T13:00:00.000Z"))
    sts = parse_dated_page(html, THEATRE)
    assert len(sts) == 1
    st = sts[0]
    assert st.id == "144316365"
    assert st.movie_title == ODYSSEY
    assert st.format_label == "imax70mm"
    assert st.when_iso == "2026-08-05T13:00:00.000Z"
    assert st.purchase_url == "https://www.amctheatres.com/showtimes/144316365"


def test_parse_separates_movies_and_formats():
    html = _page(
        (ODYSSEY, "imax70mm", "1", "2026-08-05T13:00:00.000Z"),
        (SPIDER, "dolbycinemaatamcprime", "2", "2026-08-05T16:30:00.000Z"),
        (ODYSSEY, "digital", "3", "2026-08-05T20:00:00.000Z"),
    )
    sts = parse_dated_page(html, THEATRE)
    assert [(s.movie_title, s.format_label) for s in sts] == [
        (ODYSSEY, "imax70mm"),
        (SPIDER, "dolbycinemaatamcprime"),
        (ODYSSEY, "digital"),
    ]


def test_parse_dedupes_and_survives_missing_class():
    html = (
        _page((ODYSSEY, "imax70mm", "1", "2026-08-05T13:00:00.000Z"))
        + '<a href="/showtimes/1">dupe</a>'
        + '<a href="/showtimes/9"><time dateTime="2026-08-05T22:00:00.000Z">6:00pm</time></a>'
    )
    sts = parse_dated_page(html, THEATRE)
    assert len(sts) == 2
    assert sts[1].movie_title == ""  # classless anchor kept but unattributed


class FakeDatedClient:
    """Maps ISO date -> page HTML; counts fetches per date."""

    def __init__(self, pages):
        self.pages = pages
        self.fetches = []
        self.showtimes_url = "https://example.com/showtimes"

    def fetch_dated(self, date_iso):
        self.fetches.append(date_iso)
        return parse_dated_page(self.pages.get(date_iso, "<html></html>"), THEATRE)


def _cfg():
    cfg = Config()
    cfg.amc_api_key = None
    cfg.movie_query = "Odyssey"
    cfg.format_match = "70"
    cfg.alert_modes = ["new_date"]
    cfg.horizon_scan_days = 10
    return cfg


def _pages_through(*dates):
    return {
        d: _page((ODYSSEY, "imax70mm", str(i), f"{d}T18:00:00.000Z"))
        for i, d in enumerate(dates)
    }


@mock.patch("time.sleep")  # no real pacing in tests
def test_seed_scan_walks_until_horizon(_sleep, tmp_path):
    cfg = _cfg()
    cfg.sightings_path = str(tmp_path / "s.jsonl")
    client = FakeDatedClient(_pages_through("2026-07-23", "2026-07-24", "2026-07-25"))
    state = _fresh_state()

    _scan_dated_pages(cfg, client, state)
    # The walk starts at the real today and must terminate: either after 3
    # consecutive empty days or at the horizon_scan_days cap.
    assert 3 <= len(client.fetches) <= 10


@mock.patch("time.sleep")
def test_poll_checks_only_day_after_horizon(_sleep, tmp_path):
    cfg = _cfg()
    cfg.sightings_path = str(tmp_path / "s.jsonl")
    state = _fresh_state()
    state["dates_seeded"] = True
    state["seen_dates"] = ["2026-08-16"]

    client = FakeDatedClient({})  # nothing new
    out = _scan_dated_pages(cfg, client, state)
    assert out == []
    assert client.fetches == ["2026-08-17"]  # exactly one request, at the edge


@mock.patch("time.sleep")
def test_new_date_dropping_alerts_once_and_extends_horizon(_sleep, tmp_path):
    cfg = _cfg()
    cfg.sightings_path = str(tmp_path / "s.jsonl")
    state = _fresh_state()
    state["dates_seeded"] = True
    state["seen_dates"] = ["2026-08-16"]

    client = FakeDatedClient(_pages_through("2026-08-17"))

    class FakeNotifier:
        def __init__(self):
            self.bodies = []

        def send(self, body, subject=None):
            self.bodies.append(body)
            return ["ok"]

    notifier = FakeNotifier()
    sent, changed = check_once(cfg, client, notifier, state)

    assert sent == 1
    assert changed is True
    assert "New date bookable" in notifier.bodies[0]
    assert "2026-08-17" in state["seen_dates"]
    # It probed 8/17 (found) then 8/18 (empty) to chase consecutive drops.
    assert client.fetches == ["2026-08-17", "2026-08-18"]

    # Next poll: horizon moved, so it checks 8/18 only, quietly.
    client.fetches.clear()
    sent2, _ = check_once(cfg, client, notifier, state)
    assert sent2 == 0
    assert client.fetches == ["2026-08-18"]
