"""Tests for the Twilio OAuth client-credentials sender (HTTP mocked)."""

import time
from unittest import mock

import pytest

from amc_monitor.notifier import OAUTH_TOKEN_URL, OAuthTokenError, _OAuthSession


def _resp(status, payload):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload
    r.text = str(payload)
    return r


def test_fetches_token_with_client_credentials_grant():
    s = _OAuthSession("cid", "csecret", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.return_value = _resp(200, {"access_token": "tok1", "expires_in": 3600})
        assert s.token() == "tok1"

    call = post.call_args
    assert call.args[0] == OAUTH_TOKEN_URL
    assert call.kwargs["data"] == {
        "grant_type": "client_credentials",
        "client_id": "cid",
        "client_secret": "csecret",
    }


def test_token_cached_until_near_expiry():
    s = _OAuthSession("cid", "csecret", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.return_value = _resp(200, {"access_token": "tok1", "expires_in": 3600})
        s.token()
        s.token()
        assert post.call_count == 1  # cached

        s._expires_at = time.time() + 10  # inside the refresh margin
        post.return_value = _resp(200, {"access_token": "tok2", "expires_in": 3600})
        assert s.token() == "tok2"
        assert post.call_count == 2


def test_token_error_raises():
    s = _OAuthSession("cid", "bad", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.return_value = _resp(401, {"error": "invalid_client"})
        with pytest.raises(OAuthTokenError):
            s.token()


def test_send_uses_bearer_and_account_scoped_url():
    s = _OAuthSession("cid", "csecret", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.side_effect = [
            _resp(200, {"access_token": "tok1", "expires_in": 3600}),
            _resp(201, {"sid": "SM_abc"}),
        ]
        sid = s.send_message("+15138862571", "hello", "+15550001111", None)

    assert sid == "SM_abc"
    send_call = post.call_args_list[1]
    assert "/Accounts/AC123/Messages.json" in send_call.args[0]
    assert send_call.kwargs["headers"]["Authorization"] == "Bearer tok1"
    assert send_call.kwargs["data"] == {"To": "+15138862571", "Body": "hello", "From": "+15550001111"}


def test_send_retries_once_on_401():
    s = _OAuthSession("cid", "csecret", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.side_effect = [
            _resp(200, {"access_token": "stale", "expires_in": 3600}),
            _resp(401, {"error": "expired"}),  # first send rejected
            _resp(200, {"access_token": "fresh", "expires_in": 3600}),
            _resp(201, {"sid": "SM_retry"}),
        ]
        sid = s.send_message("+16155870370", "hi", "+15550001111", None)
    assert sid == "SM_retry"


def test_messaging_service_sid_preferred_over_from():
    s = _OAuthSession("cid", "csecret", "AC123")
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.side_effect = [
            _resp(200, {"access_token": "tok", "expires_in": 3600}),
            _resp(201, {"sid": "SM_ms"}),
        ]
        s.send_message("+15138862571", "yo", "+15550001111", "MG123")
    data = post.call_args_list[1].kwargs["data"]
    assert data["MessagingServiceSid"] == "MG123"
    assert "From" not in data
