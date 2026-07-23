"""Tests for the email alert channel and multi-channel send logic."""

from unittest import mock

import pytest

from amc_monitor.config import Config
from amc_monitor.notifier import Notifier
from tests.test_auth import env

EMAIL_ENV = dict(
    SMTP_USER="zain@example.com",
    SMTP_PASS="app-password",
    ALERT_EMAILS="5138862571@vtext.com,wife@example.com",
    TWILIO_ACCOUNT_SID=None,
    TWILIO_AUTH_TOKEN=None,
    TWILIO_API_KEY_SID=None,
    TWILIO_API_KEY_SECRET=None,
    TWILIO_CLIENT_ID=None,
    TWILIO_CLIENT_SECRET=None,
    TWILIO_FROM=None,
    TWILIO_MESSAGING_SERVICE_SID=None,
    ALERT_NUMBERS=None,
)


def test_email_channel_detected():
    with env(**EMAIL_ENV):
        cfg = Config()
        assert cfg.has_email_channel() is True
        assert cfg.has_twilio_channel() is False


def test_email_only_config_validates():
    with env(AMC_THEATRE_ID="amc-lincoln-square-13", **EMAIL_ENV):
        cfg = Config()
        assert cfg.validate_for_alerts() == []


def test_partial_email_config_reports_missing():
    partial = dict(EMAIL_ENV, ALERT_EMAILS=None)
    with env(AMC_THEATRE_ID="x", **partial):
        cfg = Config()
        problems = cfg.validate_for_alerts()
        assert any("ALERT_EMAILS" in p for p in problems)


def test_send_via_smtp():
    with env(**EMAIL_ENV):
        cfg = Config()
    notifier = Notifier(cfg)
    with mock.patch("smtplib.SMTP") as smtp_cls:
        server = smtp_cls.return_value.__enter__.return_value
        server.send_message.return_value = {}  # nobody refused
        ids = notifier.send("hello", subject="test")

    assert ids == ["5138862571@vtext.com", "wife@example.com"]
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("zain@example.com", "app-password")
    msg = server.send_message.call_args.args[0]
    assert msg["To"] == "5138862571@vtext.com, wife@example.com"
    assert msg["Subject"] == "test"


def test_sms_failure_does_not_block_email():
    both = dict(
        EMAIL_ENV,
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_API_KEY_SID="SK123",
        TWILIO_API_KEY_SECRET="secret",
        TWILIO_FROM="+15550001111",
        ALERT_NUMBERS="+15138862571",
    )
    with env(**both):
        cfg = Config()
    notifier = Notifier(cfg)
    with mock.patch.object(notifier, "_send_sms", side_effect=RuntimeError("30032")), mock.patch(
        "smtplib.SMTP"
    ) as smtp_cls:
        smtp_cls.return_value.__enter__.return_value.send_message.return_value = {}
        ids = notifier.send("hello")
    assert ids == ["5138862571@vtext.com", "wife@example.com"]


def test_all_channels_failing_raises():
    with env(**EMAIL_ENV):
        cfg = Config()
    notifier = Notifier(cfg)
    with mock.patch("smtplib.SMTP", side_effect=OSError("smtp down")):
        with pytest.raises(RuntimeError, match="all alert channels failed"):
            notifier.send("hello")
