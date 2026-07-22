"""Tests for adjacent-pair detection and the seat-map parser."""

from amc_monitor.seatmap import Seat, _parse_seatmap, find_adjacent_pairs, has_adjacent_pair


def _row(name, cols_open):
    return [Seat(row=name, col=c, available=c in cols_open) for c in range(1, 11)]


def test_finds_adjacent_pair():
    seats = _row("F", {4, 5})
    assert has_adjacent_pair(seats)
    pairs = find_adjacent_pairs(seats)
    assert len(pairs) == 1
    a, b = pairs[0]
    assert (a.col, b.col) == (4, 5)


def test_no_pair_when_gap():
    seats = _row("F", {2, 4, 6})  # all isolated
    assert not has_adjacent_pair(seats)


def test_pair_only_within_same_row():
    seats = _row("F", {10}) + _row("G", {1})  # adjacent numbers, different rows
    assert not has_adjacent_pair(seats)


def test_three_in_a_row_reports_two_pairs():
    seats = _row("H", {3, 4, 5})
    assert len(find_adjacent_pairs(seats)) == 2


def test_parse_seatmap_available_flags():
    data = {
        "rows": [
            {
                "rowName": "F",
                "seats": [
                    {"column": 1, "status": "available"},
                    {"column": 2, "status": "sold"},
                    {"column": 3, "available": True},
                ],
            }
        ]
    }
    seats = _parse_seatmap(data)
    avail = {s.col: s.available for s in seats}
    assert avail == {1: True, 2: False, 3: True}
