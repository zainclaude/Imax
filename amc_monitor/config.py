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
    twilio_sid: str | None = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID") or None)
    twilio_token: str | None = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN") or None)
    twilio_from: str | None = field(default_factory=lambda: os.getenv("TWILIO_FROM") or None)
    messaging_service_sid: str | None = field(
        default_factory=lambda: os.getenv("TWILIO_MESSAGING_SERVICE_SID") or None
    )
    alert_numbers: list[str] = field(default_factory=lambda: _numbers(os.getenv("ALERT_NUMBERS")))

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
