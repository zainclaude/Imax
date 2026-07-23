"""Tests for Twilio auth-style selection and validation."""

import os
from contextlib import contextmanager

from amc_monitor.config import Config


@contextmanager
def env(**kwargs):
    old = {k: os.environ.get(k) for k in kwargs}
    try:
        for k, v in kwargs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_api_key_auth_recognized():
    with env(
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_API_KEY_SID="SK123",
        TWILIO_API_KEY_SECRET="secret",
        TWILIO_AUTH_TOKEN=None,
    ):
        cfg = Config()
        assert cfg.has_api_key_auth() is True
        assert cfg.has_auth_token_auth() is False


def test_auth_token_auth_recognized():
    with env(
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_AUTH_TOKEN="tok",
        TWILIO_API_KEY_SID=None,
        TWILIO_API_KEY_SECRET=None,
    ):
        cfg = Config()
        assert cfg.has_auth_token_auth() is True
        assert cfg.has_api_key_auth() is False


def test_api_key_without_account_sid_is_incomplete():
    with env(
        TWILIO_ACCOUNT_SID=None,
        TWILIO_API_KEY_SID="SK123",
        TWILIO_API_KEY_SECRET="secret",
        TWILIO_AUTH_TOKEN=None,
    ):
        cfg = Config()
        assert cfg.has_api_key_auth() is False


def test_validate_flags_no_channel_at_all():
    with env(
        AMC_THEATRE_ID="362",
        ALERT_NUMBERS="+15138862571,+16155870370",
        TWILIO_ACCOUNT_SID=None,
        TWILIO_AUTH_TOKEN=None,
        TWILIO_API_KEY_SID=None,
        TWILIO_API_KEY_SECRET=None,
        TWILIO_FROM=None,
        TWILIO_MESSAGING_SERVICE_SID=None,
        SMTP_USER=None,
        SMTP_PASS=None,
        ALERT_EMAILS=None,
    ):
        cfg = Config()
        problems = cfg.validate_for_alerts()
        assert any("No alert channel configured" in p for p in problems)


def test_validate_passes_with_api_key_and_sender():
    with env(
        AMC_THEATRE_ID="362",
        ALERT_NUMBERS="+15138862571,+16155870370",
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_API_KEY_SID="SK123",
        TWILIO_API_KEY_SECRET="secret",
        TWILIO_AUTH_TOKEN=None,
        TWILIO_FROM="+15550001111",
        TWILIO_MESSAGING_SERVICE_SID=None,
    ):
        cfg = Config()
        assert cfg.validate_for_alerts() == []
