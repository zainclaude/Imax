"""Tests for the ntfy push channel."""

from unittest import mock

from amc_monitor.config import Config
from amc_monitor.notifier import Notifier
from tests.test_auth import env

NTFY_ONLY = dict(
    NTFY_TOPIC="odyssey-secret-topic-x8k2",
    SMTP_USER=None,
    SMTP_PASS=None,
    ALERT_EMAILS=None,
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


def _resp(status=200):
    r = mock.Mock()
    r.status_code = status
    r.raise_for_status.return_value = None
    return r


def test_ntfy_only_config_validates():
    with env(AMC_THEATRE_ID="amc-lincoln-square-13", **NTFY_ONLY):
        cfg = Config()
        assert cfg.has_ntfy_channel() is True
        assert cfg.validate_for_alerts() == []


def test_ntfy_publish_posts_to_topic():
    with env(**NTFY_ONLY):
        cfg = Config()
    notifier = Notifier(cfg)
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.return_value = _resp()
        ids = notifier.send("seats open!", subject="🎬 Odyssey alert")

    assert ids == ["https://ntfy.sh/odyssey-secret-topic-x8k2"]
    call = post.call_args
    assert call.args[0] == "https://ntfy.sh/odyssey-secret-topic-x8k2"
    assert call.kwargs["data"] == "seats open!".encode()
    assert call.kwargs["headers"]["Priority"] == "high"


def test_custom_server_used():
    with env(NTFY_SERVER="https://push.example.com/", **NTFY_ONLY):
        cfg = Config()
    notifier = Notifier(cfg)
    with mock.patch("amc_monitor.notifier.requests.post") as post:
        post.return_value = _resp()
        ids = notifier.send("hi")
    assert ids == ["https://push.example.com/odyssey-secret-topic-x8k2"]
