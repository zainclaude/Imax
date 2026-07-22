"""
Adjacent-seat detection.

Given a showtime's seat map, find whether there are two open seats next to each
other in the same row. This is a read-only convenience filter so we only ping you
when a genuinely bookable pair exists — it does not reserve or hold anything.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .amc_client import USER_AGENT, AntiBotChallenge


@dataclass
class Seat:
    row: str
    col: int
    available: bool


def fetch_seatmap(seatmap_url: str, api_key: str | None = None) -> list[Seat]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["X-AMC-Vendor-Key"] = api_key
    resp = requests.get(seatmap_url, headers=headers, timeout=20)
    if resp.status_code in (401, 403) and "just a moment" in resp.text[:2000].lower():
        raise AntiBotChallenge("Seat map returned an anti-bot challenge; not evading.")
    resp.raise_for_status()
    return _parse_seatmap(resp.json())


def _parse_seatmap(data: dict) -> list[Seat]:
    seats: list[Seat] = []
    # AMC seat maps expose rows -> seats with a status/availability flag.
    embedded = data.get("_embedded", data)
    rows = embedded.get("rows") or data.get("rows") or []
    for row in rows:
        row_name = str(row.get("rowName") or row.get("name") or "")
        for seat in row.get("seats", []):
            status = str(seat.get("status") or seat.get("seatStatus") or "").lower()
            available = status in {"available", "open", "empty", "0"} or seat.get("available") is True
            col_raw = seat.get("column") or seat.get("seatNumber") or seat.get("col")
            try:
                col = int(col_raw)
            except (TypeError, ValueError):
                continue
            seats.append(Seat(row=row_name, col=col, available=available))
    return seats


def has_adjacent_pair(seats: list[Seat]) -> bool:
    """True if any row has two open seats in consecutive columns."""
    return bool(find_adjacent_pairs(seats))


def find_adjacent_pairs(seats: list[Seat]) -> list[tuple[Seat, Seat]]:
    by_row: dict[str, list[Seat]] = {}
    for s in seats:
        by_row.setdefault(s.row, []).append(s)

    pairs: list[tuple[Seat, Seat]] = []
    for row_seats in by_row.values():
        row_seats.sort(key=lambda s: s.col)
        for a, b in zip(row_seats, row_seats[1:]):
            if a.available and b.available and b.col - a.col == 1:
                pairs.append((a, b))
    return pairs
