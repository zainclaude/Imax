"""
Group-text alerting via Twilio.

Delivery modes:
  * Messaging Service / Group MMS  -> one shared thread for both recipients.
  * Plain SMS                       -> same message sent to each number (1:1).

Auth styles (picked automatically from config):
  * OAuth 2.0 client credentials (TWILIO_CLIENT_ID/SECRET + Account SID):
    fetch a short-lived Bearer token from https://oauth.twilio.com/v2/token and
    call the Messages API over HTTP directly. Token is cached and refreshed
    before expiry.
  * API Key (SK… + secret + Account SID) or Account SID + Auth Token:
    standard Twilio SDK basic-auth client.
"""

from __future__ import annotations

import time

import requests

from .config import Config

OAUTH_TOKEN_URL = "https://oauth.twilio.com/v2/token"
MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

# Refresh the token this many seconds before it actually expires.
TOKEN_REFRESH_MARGIN = 120


class OAuthTokenError(RuntimeError):
    pass


class _OAuthSession:
    """Client-credentials token cache + Bearer-auth message sender."""

    def __init__(self, client_id: str, client_secret: str, account_sid: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_sid = account_sid
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _fetch_token(self) -> None:
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise OAuthTokenError(
                f"Twilio OAuth token request failed ({resp.status_code}): {resp.text[:300]}"
            )
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise OAuthTokenError(f"No access_token in Twilio OAuth response: {payload}")
        self._token = token
        self._expires_at = time.time() + float(payload.get("expires_in", 3600))

    def token(self) -> str:
        if self._token is None or time.time() >= self._expires_at - TOKEN_REFRESH_MARGIN:
            self._fetch_token()
        assert self._token is not None
        return self._token

    def send_message(self, to: str, body: str, from_: str | None, messaging_service_sid: str | None) -> str:
        data = {"To": to, "Body": body}
        if messaging_service_sid:
            data["MessagingServiceSid"] = messaging_service_sid
        else:
            data["From"] = from_ or ""
        resp = requests.post(
            MESSAGES_URL.format(sid=self.account_sid),
            data=data,
            headers={"Authorization": f"Bearer {self.token()}"},
            timeout=20,
        )
        if resp.status_code == 401:
            # Token may have been revoked early; refresh once and retry.
            self._token = None
            resp = requests.post(
                MESSAGES_URL.format(sid=self.account_sid),
                data=data,
                headers={"Authorization": f"Bearer {self.token()}"},
                timeout=20,
            )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Twilio send failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json().get("sid", "")


def _send_email(cfg: Config, subject: str, body: str) -> list[str]:
    """Send `body` to every ALERT_EMAILS recipient over SMTP (STARTTLS).

    Recipients may be normal inboxes or carrier email-to-SMS gateway addresses.
    Returns the list of recipients accepted by the server.
    """
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = cfg.smtp_user
    msg["To"] = ", ".join(cfg.alert_emails)
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(cfg.smtp_user, cfg.smtp_pass)
        refused = server.send_message(msg)
    return [addr for addr in cfg.alert_emails if addr not in refused]


def _send_ntfy(cfg: Config, title: str, body: str) -> str:
    """Publish a high-priority push to the configured ntfy topic.

    Anyone subscribed to the topic in the ntfy app gets an instant notification.
    Returns the topic URL as the delivery id.
    """
    url = f"{cfg.ntfy_server.rstrip('/')}/{cfg.ntfy_topic}"
    resp = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": "high",
            "Tags": "clapper",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return url


def sound_alarm(cfg: Config) -> None:
    """Audible local alarm (macOS): repeated sound + spoken announcement.

    Runs in a daemon thread so the poll loop is never blocked. No-op on other
    platforms or when LOCAL_ALARM=false. Plays at current system volume — an
    unmuted Mac is part of the deal.
    """
    import platform
    import subprocess
    import threading

    if not cfg.alarm_enabled or platform.system() != "Darwin":
        return

    def _play():
        try:
            for _ in range(max(1, cfg.alarm_repeat)):
                subprocess.run(["afplay", "-v", "2", cfg.alarm_sound], check=False, timeout=15)
            if cfg.alarm_say:
                subprocess.run(["say", cfg.alarm_say], check=False, timeout=30)
        except Exception:
            pass  # a broken alarm must never take down the monitor

    threading.Thread(target=_play, daemon=True).start()


class Notifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = None
        self._oauth: _OAuthSession | None = None

    def _oauth_session(self) -> _OAuthSession:
        if self._oauth is None:
            self._oauth = _OAuthSession(
                self.cfg.twilio_client_id,  # type: ignore[arg-type]
                self.cfg.twilio_client_secret,  # type: ignore[arg-type]
                self.cfg.twilio_sid,  # type: ignore[arg-type]
            )
        return self._oauth

    def _twilio(self):
        if self._client is None:
            from twilio.rest import Client

            if self.cfg.has_api_key_auth():
                # API Key SID + Secret authenticate; Account SID scopes the account.
                self._client = Client(
                    self.cfg.twilio_api_key_sid,
                    self.cfg.twilio_api_key_secret,
                    self.cfg.twilio_sid,
                )
            else:
                self._client = Client(self.cfg.twilio_sid, self.cfg.twilio_token)
        return self._client

    def _send_sms(self, body: str) -> list[str]:
        if self.cfg.has_oauth_auth():
            session = self._oauth_session()
            return [
                session.send_message(
                    number, body, self.cfg.twilio_from, self.cfg.messaging_service_sid
                )
                for number in self.cfg.alert_numbers
            ]

        client = self._twilio()
        sids: list[str] = []
        for number in self.cfg.alert_numbers:
            kwargs = {"to": number, "body": body}
            if self.cfg.messaging_service_sid:
                kwargs["messaging_service_sid"] = self.cfg.messaging_service_sid
            else:
                kwargs["from_"] = self.cfg.twilio_from
            msg = client.messages.create(**kwargs)
            sids.append(msg.sid)
        return sids

    def send(self, body: str, subject: str = "🎬 Odyssey 70mm alert") -> list[str]:
        """Send `body` over every configured channel (SMS and/or email).

        Returns delivery ids (message SIDs / accepted email addresses). Raises
        only if every configured channel fails, so one broken channel can't
        silence the other.
        """
        ids: list[str] = []
        errors: list[str] = []

        if self.cfg.has_twilio_channel():
            try:
                ids.extend(self._send_sms(body))
            except Exception as e:
                errors.append(f"sms: {e}")

        if self.cfg.has_email_channel():
            try:
                ids.extend(_send_email(self.cfg, subject, body))
            except Exception as e:
                errors.append(f"email: {e}")

        if self.cfg.has_ntfy_channel():
            try:
                ids.append(_send_ntfy(self.cfg, subject, body))
            except Exception as e:
                errors.append(f"ntfy: {e}")

        if errors and not ids:
            raise RuntimeError("all alert channels failed — " + "; ".join(errors))
        for err in errors:
            print(f"[warn] alert channel failed ({err}) but another succeeded")
        return ids


def format_new_date_alert(movie: str, fmt: str, pretty_date: str, count: int, link: str | None) -> str:
    shows = "showtime" if count == 1 else "showtimes"
    lines = [
        f"🆕 New date bookable: {pretty_date}",
        f"{movie} — {fmt} @ AMC Lincoln Square",
        f"{count} {shows} just opened.",
    ]
    if link:
        lines.append(link)
    lines.append("Fresh seats — go grab them.")
    return "\n".join(lines)


def format_alert(movie: str, fmt: str, when: str, link: str | None, has_pair: bool) -> str:
    pair_note = "✅ adjacent pair open" if has_pair else "seats live"
    lines = [
        f"🎬 {movie} — {fmt}",
        f"AMC Lincoln Square · {when}",
        pair_note,
    ]
    if link:
        lines.append(link)
    lines.append("Go book — this won't last.")
    return "\n".join(lines)
