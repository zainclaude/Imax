"""
Analyze first-sighting timestamps to reveal when AMC actually drops new
Odyssey 70mm showtimes at Lincoln Square.

    python -m amc_monitor.patterns

Buckets every "first seen" moment by weekday and hour in America/New_York (the
theatre's local time) and prints where the drops cluster, so you know when to be
ready. Needs a few days of collected data to be meaningful.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config
from .sightings import load_sightings

ET = ZoneInfo("America/New_York")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def bucket_by_weekday_hour(epochs: list[float], tz: ZoneInfo = ET) -> tuple[Counter, Counter]:
    """Return (weekday_counts, hour_counts) in the given timezone.

    weekday_counts is keyed 0=Mon..6=Sun; hour_counts is keyed 0..23.
    Pure and deterministic given the inputs — easy to test.
    """
    weekday_counts: Counter = Counter()
    hour_counts: Counter = Counter()
    for epoch in epochs:
        dt = datetime.fromtimestamp(epoch, tz)
        weekday_counts[dt.weekday()] += 1
        hour_counts[dt.hour] += 1
    return weekday_counts, hour_counts


def _bar(n: int, peak: int, width: int = 30) -> str:
    if peak <= 0:
        return ""
    return "█" * max(1, round(n / peak * width)) if n else ""


def summarize(epochs: list[float], tz: ZoneInfo = ET) -> str:
    if not epochs:
        return (
            "No sightings logged yet. Let the monitor run for a few days, then "
            "check back — this needs data to find a pattern."
        )

    weekday_counts, hour_counts = bucket_by_weekday_hour(epochs, tz)
    lines: list[str] = []
    lines.append(f"{len(epochs)} new-showtime sightings logged (times in America/New_York).\n")

    lines.append("By weekday:")
    wpeak = max(weekday_counts.values(), default=0)
    for i, name in enumerate(WEEKDAYS):
        c = weekday_counts.get(i, 0)
        lines.append(f"  {name}  {c:3d}  {_bar(c, wpeak)}")

    lines.append("\nBy hour (ET):")
    hpeak = max(hour_counts.values(), default=0)
    for h in range(24):
        c = hour_counts.get(h, 0)
        lines.append(f"  {h:02d}:00  {c:3d}  {_bar(c, hpeak)}")

    # Simple guidance from the peaks.
    if weekday_counts:
        best_day = WEEKDAYS[max(weekday_counts, key=weekday_counts.get)]
        top_hours = [f"{h:02d}:00" for h, _ in sorted(hour_counts.items(), key=lambda kv: -kv[1])[:3]]
        lines.append(
            f"\nLikely drop window: around {best_day}, "
            f"hours {', '.join(top_hours)} ET. "
            "Be ready then; keep polls polite the rest of the time."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    cfg = Config()
    rows = load_sightings(cfg.sightings_path)
    epochs = [float(r["first_seen_epoch"]) for r in rows if "first_seen_epoch" in r]
    print(summarize(epochs))
    if not epochs:
        sys.exit(0)


if __name__ == "__main__":
    main()
