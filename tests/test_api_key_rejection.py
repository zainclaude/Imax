"""Tests distinguishing vendor-key rejection from anti-bot challenges."""

from unittest import mock

import pytest

from amc_monitor.amc_client import AmcClient, AntiBotChallenge, ApiKeyUnauthorized


def _resp(status, text, headers=None):
    r = mock.Mock()
    r.status_code = status
    r.text = text
    r.headers = headers or {}
    return r


def _client():
    return AmcClient("key", "123")


def test_unauthorized_vendor_key_is_not_a_bot_challenge():
    # AMC's real 403 body for an inactive key, behind a cloudflare Server header.
    body = '{"errors":[{"id":"x","code":12005,"exceptionMessage":"Unauthorized VendorKey."}]}'
    client = _client()
    with mock.patch.object(client.session, "get", return_value=_resp(403, body, {"Server": "cloudflare"})):
        with pytest.raises(ApiKeyUnauthorized):
            client._get("https://api.amctheatres.com/v2/theatres")


def test_cloudflare_interstitial_still_detected():
    client = _client()
    resp = _resp(403, "<html>Just a moment...</html>", {"Server": "cloudflare"})
    with mock.patch.object(client.session, "get", return_value=resp):
        with pytest.raises(AntiBotChallenge):
            client._get("https://www.amctheatres.com/whatever")


def test_check_once_falls_back_to_dated_pages(tmp_path):
    from amc_monitor.config import Config
    from amc_monitor.monitor import _fresh_state, check_once

    cfg = Config()
    cfg.amc_api_key = "inactive-key"
    cfg.movie_query = "Odyssey"
    cfg.format_match = "70"
    cfg.alert_modes = ["new_date"]
    cfg.sightings_path = str(tmp_path / "s.jsonl")

    client = mock.Mock()
    client.api_key = "inactive-key"
    state = _fresh_state()
    state["dates_seeded"] = True
    state["seen_dates"] = ["2026-08-16"]
    client.fetch_dated.return_value = []  # page path: nothing new

    with mock.patch("amc_monitor.monitor.polite_fetch", side_effect=ApiKeyUnauthorized("nope")), mock.patch(
        "time.sleep"
    ):
        sent, _ = check_once(cfg, client, None, state)

    assert sent == 0
    assert cfg.amc_api_key is None  # switched off for the rest of the run
    client.fetch_dated.assert_called_once_with("2026-08-17")  # page path took over
