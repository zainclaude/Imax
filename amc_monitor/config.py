"""Configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional at runtime
    pass


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _numbers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [n.strip() for n in raw.split(",") if n.strip()]


# Alert modes (choose one or more, comma-separated in ALERT_MODE):
#   new_date       -> text when a brand-new bookable calendar date appears
#                     (the booking horizon extends, e.g. Aug 16 was the max, now
#                     Aug 17 shows up). Usually the signal that matters most.
#   adjacent_pair  -> text when a showtime has two open seats next to each other.
#   any_showtime   -> text on any newly-seen showtime slot, regardless of the above.
VALID_MODES = {"new_date", "adjacent_pair", "any_showtime"}


def _alert_modes() -> list[str]:
    raw = os.getenv("ALERT_MODE")
    if raw:
        modes = [m.strip().lower() for m in raw.split(",") if m.strip()]
        modes = [m for m in modes if m in VALID_MODES]
        if modes:
            return modes
    # Back-compat: honor the old REQUIRE_ADJACENT_PAIR flag if ALERT_MODE is unset.
    if os.getenv("REQUIRE_ADJACENT_PAIR") is not None and _bool("REQUIRE_ADJACENT_PAIR", True):
        return ["adjacent_pair"]
    # Default: the horizon-extension alert the run really cares about.
    return ["new_date"]


@dataclass
class Config:
    # AMC data source
    amc_api_key: str | None = field(default_factory=lambda: os.getenv("AMC_API_KEY") or None)
    theatre_id: str | None = field(default_factory=lambda: os.getenv("AMC_THEATRE_ID") or None)

    # What to watch
    movie_query: str = field(default_factory=lambda: os.getenv("MOVIE_QUERY", "Odyssey"))
    format_match: str = field(default_factory=lambda: os.getenv("FORMAT_MATCH", "70"))
    alert_modes: list[str] = field(default_factory=_alert_modes)

    # Politeness
    poll_seconds: int = field(default_factory=lambda: int(os.getenv("POLL_SECONDS", "180")))

    # Twilio / alerting
    # Auth — two supported styles:
    #   1) Account SID (AC…) + Auth Token
    #   2) API Key SID (SK…) + API Key Secret, together with the Account SID
    # API keys are the recommended, revocable option.
    twilio_sid: str | None = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID") or None)
    twilio_token: str | None = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN") or None)
    twilio_api_key_sid: str | None = field(default_factory=lambda: os.getenv("TWILIO_API_KEY_SID") or None)
    twilio_api_key_secret: str | None = field(
        default_factory=lambda: os.getenv("TWILIO_API_KEY_SECRET") or None
    )
    # OAuth 2.0 client-credentials (GA). Still needs the Account SID for the Messages URL path.
    twilio_client_id: str | None = field(default_factory=lambda: os.getenv("TWILIO_CLIENT_ID") or None)
    twilio_client_secret: str | None = field(
        default_factory=lambda: os.getenv("TWILIO_CLIENT_SECRET") or None
    )
    twilio_from: str | None = field(default_factory=lambda: os.getenv("TWILIO_FROM") or None)
    messaging_service_sid: str | None = field(
        default_factory=lambda: os.getenv("TWILIO_MESSAGING_SERVICE_SID") or None
    )
    alert_numbers: list[str] = field(default_factory=lambda: _numbers(os.getenv("ALERT_NUMBERS")))

    # Email channel (works today while SMS awaits toll-free verification).
    # Recipients can be regular addresses AND/OR carrier email-to-SMS gateways
    # (e.g. 15551234567@vtext.com for Verizon, @tmomail.net for T-Mobile).
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str | None = field(default_factory=lambda: os.getenv("SMTP_USER") or None)
    smtp_pass: str | None = field(default_factory=lambda: os.getenv("SMTP_PASS") or None)
    alert_emails: list[str] = field(default_factory=lambda: _numbers(os.getenv("ALERT_EMAILS")))

    # State
    state_path: str = field(default_factory=lambda: os.getenv("STATE_PATH", ".amc_monitor_state.json"))
    # Append-only log of when each showtime slot was first seen (for cadence learning).
    sightings_path: str = field(
        default_factory=lambda: os.getenv("SIGHTINGS_PATH", ".amc_monitor_sightings.jsonl")
    )

    def humane_poll_seconds(self) -> int:
        """Enforce a polite floor. This monitor is a heads-up tool, not a scraper race."""
        return max(120, self.poll_seconds)

    def wants(self, mode: str) -> bool:
        return mode in self.alert_modes

    def has_api_key_auth(self) -> bool:
        return bool(self.twilio_api_key_sid and self.twilio_api_key_secret and self.twilio_sid)

    def has_auth_token_auth(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token)

    def has_oauth_auth(self) -> bool:
        return bool(self.twilio_client_id and self.twilio_client_secret and self.twilio_sid)

    def has_twilio_channel(self) -> bool:
        has_auth = self.has_api_key_auth() or self.has_auth_token_auth() or self.has_oauth_auth()
        has_sender = bool(self.twilio_from or self.messaging_service_sid)
        return has_auth and has_sender and bool(self.alert_numbers)

    def has_email_channel(self) -> bool:
        return bool(self.smtp_user and self.smtp_pass and self.alert_emails)

    def validate_for_alerts(self) -> list[str]:
        problems = []
        if not self.theatre_id:
            problems.append("AMC_THEATRE_ID is not set.")

        # At least one working alert channel is required; both is fine.
        if self.has_twilio_channel() or self.has_email_channel():
            return problems

        if self.twilio_client_id and self.twilio_client_secret and not self.twilio_sid:
            problems.append(
                "TWILIO_CLIENT_ID/SECRET found but TWILIO_ACCOUNT_SID is missing — OAuth "
                "replaces the auth token, but the Account SID (AC…) is still required "
                "for the Messages API URL. It's on your Twilio console dashboard."
            )
        elif self.smtp_user or self.smtp_pass or self.alert_emails:
            missing = [
                name
                for name, val in [
                    ("SMTP_USER", self.smtp_user),
                    ("SMTP_PASS", self.smtp_pass),
                    ("ALERT_EMAILS", self.alert_emails),
                ]
                if not val
            ]
            problems.append(f"Email channel incomplete — missing: {', '.join(missing)}.")
        else:
            problems.append(
                "No alert channel configured. Set up email (SMTP_USER + SMTP_PASS + ALERT_EMAILS) "
                "and/or Twilio SMS (auth + TWILIO_FROM + ALERT_NUMBERS)."
            )
        return problems
