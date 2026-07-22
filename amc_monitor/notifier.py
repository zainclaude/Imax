"""
Group-text alerting via Twilio.

Two modes:
  * Messaging Service / Group MMS  -> one shared thread for both recipients.
  * Plain SMS                       -> same message sent to each number (1:1).
"""

from __future__ import annotations

from .config import Config


class Notifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = None

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

    def send(self, body: str) -> list[str]:
        """Send `body` to everyone in ALERT_NUMBERS. Returns message SIDs."""
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
