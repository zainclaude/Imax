"""
Map a showtime's timestamp to the theatre's local calendar date (America/New_York).

Why this matters: a 2 a.m. show stored as UTC (`...T02:00:00Z`) is actually the
*previous* evening in New York. To reason about "which day is bookable", we need
the Eastern calendar date, not the raw UTC date. If the timestamp is naive (no
zone), we assume it's already theatre-local and take it as-is.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def local_date_of(when_iso: str) -> str | None:
    """Return 'YYYY-MM-DD' in Eastern time, or None if unparseable."""
    if not when_iso:
        return None
    raw = when_iso.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # Fall back to a plain date prefix like "2026-08-17".
        head = when_iso.strip()[:10]
        try:
            datetime.strptime(head, "%Y-%m-%d")
            return head
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(ET)
    return dt.date().isoformat()


def pretty_date(iso_date: str) -> str:
    """'2026-08-17' -> 'Mon Aug 17'. Passes through anything unparseable."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    return d.strftime("%a %b %-d")
