"""
Main loop.

Polls politely, remembers what it has already alerted on, and texts you + your
wife when a new 70mm Odyssey showtime (optionally: with an adjacent open pair)
appears at Lincoln Square. You do the booking.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from .amc_client import AmcClient, AntiBotChallenge, Showtime, polite_fetch
from .config import Config
from .notifier import Notifier, format_alert
from .seatmap import fetch_seatmap, find_adjacent_pairs
from .sightings import new_sighting, record_sighting


def _load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"alerted": {}, "seen": {}}
    try:
        with open(path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"alerted": {}, "seen": {}}
    state.setdefault("alerted", {})
    state.setdefault("seen", {})  # showtime_id -> first_seen epoch
    return state


def _save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _matches_format(st: Showtime, needle: str) -> bool:
    return needle.lower() in (st.format_label or "").lower()


def check_once(cfg: Config, client: AmcClient, notifier: Notifier | None, state: dict) -> tuple[int, bool]:
    """One poll. Returns (alerts_sent, state_changed)."""
    showtimes = polite_fetch(client, cfg.movie_query)
    candidates = [st for st in showtimes if _matches_format(st, cfg.format_match)]

    sent = 0
    changed = False
    for st in candidates:
        # Cadence learning: the first time we ever see this slot, stamp it. This is
        # what lets `python -m amc_monitor.patterns` reveal when AMC actually drops
        # new showtimes — independent of seat availability or whether we alert.
        if st.id not in state["seen"]:
            sighting = new_sighting(st.id, st.movie_title, st.format_label, st.when_iso)
            record_sighting(cfg.sightings_path, sighting)
            state["seen"][st.id] = sighting.first_seen_epoch
            changed = True
            print(f"[new] first sighting of showtime {st.id} ({st.format_label} {st.when_iso})")

        # Signature captures whether the adjacent-pair condition flipped, so a
        # showtime that opens up a pair later can re-alert once.
        has_pair = False
        pair_label = ""
        if st.seatmap_url:
            try:
                seats = fetch_seatmap(st.seatmap_url, cfg.amc_api_key)
                pairs = find_adjacent_pairs(seats)
                has_pair = bool(pairs)
                if pairs:
                    a, b = pairs[0]
                    pair_label = f"{a.row}{a.col}-{b.col}"
            except AntiBotChallenge:
                raise
            except Exception as e:  # seat map is best-effort; don't let it kill the loop
                print(f"[warn] seat map read failed for {st.id}: {e}", file=sys.stderr)

        if cfg.require_adjacent_pair and st.seatmap_url and not has_pair:
            continue

        sig = f"{st.key()}::{'pair' if has_pair else 'live'}"
        if sig in state["alerted"]:
            continue

        link = st.purchase_url or st.seatmap_url
        when = st.when_iso or "showtime"
        fmt = st.format_label or "70mm"
        if pair_label:
            fmt = f"{fmt} (seats {pair_label})"

        body = format_alert(st.movie_title, fmt, when, link, has_pair)
        print(f"[alert] {body!r}")
        if notifier:
            try:
                notifier.send(body)
            except Exception as e:
                print(f"[error] failed to send text: {e}", file=sys.stderr)
                continue

        state["alerted"][sig] = int(time.time())
        changed = True
        sent += 1

    return sent, changed


def run(cfg: Config, once: bool = False, dry_run: bool = False) -> None:
    problems = [] if dry_run else cfg.validate_for_alerts()
    if problems:
        print("Cannot start — configuration problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    client = AmcClient(cfg.amc_api_key, cfg.theatre_id)
    notifier = None if dry_run else Notifier(cfg)
    state = _load_state(cfg.state_path)

    source = "official API" if cfg.amc_api_key else "public page (best-effort)"
    print(f"Watching '{cfg.movie_query}' [{cfg.format_match}] at theatre {cfg.theatre_id} via {source}.")
    print(f"Poll every ~{cfg.humane_poll_seconds()}s. Adjacent-pair required: {cfg.require_adjacent_pair}.")

    while True:
        try:
            n, changed = check_once(cfg, client, notifier, state)
            if changed:
                _save_state(cfg.state_path, state)
        except AntiBotChallenge as e:
            # We hit the wall on purpose-respecting terms. Stop hammering.
            print(f"[stop] {e}", file=sys.stderr)
            print("Backing off for 30 minutes. Consider setting AMC_API_KEY.", file=sys.stderr)
            if once:
                sys.exit(2)
            time.sleep(30 * 60)
            continue
        except Exception as e:
            print(f"[warn] poll failed: {e}", file=sys.stderr)

        if once:
            break

        base = cfg.humane_poll_seconds()
        # Jitter avoids a robotic fixed cadence and spreads load.
        time.sleep(base + random.uniform(0, base * 0.25))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Polite 70mm Odyssey seat-availability notifier.")
    parser.add_argument("--once", action="store_true", help="Run a single poll and exit (good for cron).")
    parser.add_argument("--dry-run", action="store_true", help="Poll and print alerts without sending texts.")
    args = parser.parse_args(argv)

    cfg = Config()
    run(cfg, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
