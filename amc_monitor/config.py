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


@dataclass
class Config:
    # AMC data source
    amc_api_key: str | None = field(default_factory=lambda: os.getenv("AMC_API_KEY") or None)
    theatre_id: str | None = field(default_factory=lambda: os.getenv("AMC_THEATRE_ID") or None)

    # What to watch
    movie_query: str = field(default_factory=lambda: os.getenv("MOVIE_QUERY", "Odyssey"))
    format_match: str = field(default_factory=lambda: os.getenv("FORMAT_MATCH", "70"))
    require_adjacent_pair: bool = field(default_factory=lambda: _bool("REQUIRE_ADJACENT_PAIR", True))

    # Politeness
    poll_seconds: int = field(default_factory=lambda: int(os.getenv("POLL_SECONDS", "180")))

    # Twilio / alerting
    twilio_sid: str | None = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID") or None)
    twilio_token: str | None = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN") or None)
    twilio_from: str | None = field(default_factory=lambda: os.getenv("TWILIO_FROM") or None)
    messaging_service_sid: str | None = field(
        default_factory=lambda: os.getenv("TWILIO_MESSAGING_SERVICE_SID") or None
    )
    alert_numbers: list[str] = field(default_factory=lambda: _numbers(os.getenv("ALERT_NUMBERS")))

    # State
    state_path: str = field(default_factory=lambda: os.getenv("STATE_PATH", ".amc_monitor_state.json"))

    def humane_poll_seconds(self) -> int:
        """Enforce a polite floor. This monitor is a heads-up tool, not a scraper race."""
        return max(120, self.poll_seconds)

    def validate_for_alerts(self) -> list[str]:
        problems = []
        if not self.theatre_id:
            problems.append("AMC_THEATRE_ID is not set.")
        if not self.alert_numbers:
            problems.append("ALERT_NUMBERS is empty (need you + your wife).")
        using_service = bool(self.messaging_service_sid)
        if not (self.twilio_sid and self.twilio_token):
            problems.append("Twilio credentials missing.")
        if not using_service and not self.twilio_from:
            problems.append("TWILIO_FROM missing (or set TWILIO_MESSAGING_SERVICE_SID).")
        return problems
