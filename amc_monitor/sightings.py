"""
Append-only log of when each showtime slot was FIRST seen.

The point: AMC adds new dates/showtimes for the Odyssey 70mm run in irregular
batches (see README). By stamping the moment each slot first appears, we can later
learn the actual drop cadence for *this* theatre — which weekday, which hour of the
night — instead of guessing. Purely observational; nothing here contacts AMC.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass


@dataclass
class Sighting:
    showtime_id: str
    movie_title: str
    format_label: str
    show_when_iso: str
    first_seen_epoch: float


def record_sighting(path: str, sighting: Sighting) -> None:
    line = json.dumps(
        {
            "showtime_id": sighting.showtime_id,
            "movie_title": sighting.movie_title,
            "format_label": sighting.format_label,
            "show_when_iso": sighting.show_when_iso,
            "first_seen_epoch": round(sighting.first_seen_epoch, 3),
        }
    )
    with open(path, "a") as f:
        f.write(line + "\n")


def new_sighting(showtime_id: str, movie_title: str, format_label: str, show_when_iso: str) -> Sighting:
    return Sighting(
        showtime_id=showtime_id,
        movie_title=movie_title,
        format_label=format_label,
        show_when_iso=show_when_iso,
        first_seen_epoch=time.time(),
    )


def load_sightings(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []
    return out
