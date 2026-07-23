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
from .dates import local_date_of, pretty_date
from .notifier import Notifier, format_alert, format_new_date_alert
from .seatmap import fetch_seatmap, find_adjacent_pairs
from .sightings import new_sighting, record_sighting


def _fresh_state() -> dict:
    return {"alerted": {}, "seen": {}, "seen_dates": [], "dates_seeded": False}


def _load_state(path: str) -> dict:
    if not os.path.exists(path):
        return _fresh_state()
    try:
        with open(path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _fresh_state()
    state.setdefault("alerted", {})
    state.setdefault("seen", {})  # showtime_id -> first_seen epoch
    state.setdefault("seen_dates", [])  # list of 'YYYY-MM-DD' bookable dates we've observed
    state.setdefault("dates_seeded", False)  # have we captured the initial horizon yet?
    return state


def _save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _matches_format(st: Showtime, needle: str) -> bool:
    return needle.lower() in (st.format_label or "").lower()


def _emit(notifier: Notifier | None, body: str) -> bool:
    """Print an alert and, if configured, send the text. True if it 'went out'."""
    print(f"[alert] {body!r}")
    if notifier is None:
        return True  # dry-run: treat as delivered so state advances
    try:
        notifier.send(body)
        return True
    except Exception as e:
        print(f"[error] failed to send text: {e}", file=sys.stderr)
        return False


def _record_sightings(cfg: Config, state: dict, candidates: list[Showtime]) -> tuple[set[str], bool]:
    """Stamp first-sightings for cadence learning. Returns (newly_seen_ids, changed)."""
    newly_seen: set[str] = set()
    changed = False
    for st in candidates:
        if st.id not in state["seen"]:
            sighting = new_sighting(st.id, st.movie_title, st.format_label, st.when_iso)
            record_sighting(cfg.sightings_path, sighting)
            state["seen"][st.id] = sighting.first_seen_epoch
            newly_seen.add(st.id)
            changed = True
            print(f"[new] first sighting of showtime {st.id} ({st.format_label} {st.when_iso})")
    return newly_seen, changed


def _alert_new_dates(cfg: Config, notifier, state: dict, candidates: list[Showtime]) -> tuple[int, bool]:
    """Text once per brand-new bookable calendar date (the horizon extending)."""
    by_date: dict[str, list[Showtime]] = {}
    for st in candidates:
        d = local_date_of(st.when_iso)
        if d:
            by_date.setdefault(d, []).append(st)

    seen_dates = set(state["seen_dates"])

    # First run: capture the current horizon silently. We only want to hear about
    # dates that appear *after* we start watching, not every date already for sale.
    if not state["dates_seeded"]:
        state["seen_dates"] = sorted(seen_dates | set(by_date))
        state["dates_seeded"] = True
        if by_date:
            print(f"[seed] current booking horizon captured: {max(by_date)} (no alert on initial dates)")
        return 0, True

    sent = 0
    changed = False
    for d in sorted(by_date):
        if d in seen_dates:
            continue
        shows = by_date[d]
        link = next((s.purchase_url or s.seatmap_url for s in shows), None)
        fmt = shows[0].format_label or "70mm"
        body = format_new_date_alert(shows[0].movie_title, fmt, pretty_date(d), len(shows), link)
        if _emit(notifier, body):
            state["seen_dates"] = sorted(set(state["seen_dates"]) | {d})
            seen_dates.add(d)
            sent += 1
            changed = True
    return sent, changed


def _alert_adjacent_pairs(cfg: Config, notifier, state: dict, candidates: list[Showtime]) -> tuple[int, bool]:
    """Text when a showtime has two open seats next to each other."""
    sent = 0
    changed = False
    for st in candidates:
        if not st.seatmap_url:
            continue
        try:
            seats = fetch_seatmap(st.seatmap_url, cfg.amc_api_key)
            pairs = find_adjacent_pairs(seats)
        except AntiBotChallenge:
            raise
        except Exception as e:  # seat map is best-effort; don't let it kill the loop
            print(f"[warn] seat map read failed for {st.id}: {e}", file=sys.stderr)
            continue
        if not pairs:
            continue

        a, b = pairs[0]
        sig = f"{st.key()}::pair"
        if sig in state["alerted"]:
            continue
        fmt = f"{st.format_label or '70mm'} (seats {a.row}{a.col}-{b.col})"
        link = st.purchase_url or st.seatmap_url
        body = format_alert(st.movie_title, fmt, st.when_iso or "showtime", link, True)
        if _emit(notifier, body):
            state["alerted"][sig] = int(time.time())
            sent += 1
            changed = True
    return sent, changed


def _alert_any_showtime(cfg: Config, notifier, state: dict, candidates: list[Showtime], newly_seen: set[str]) -> tuple[int, bool]:
    """Text on any newly-seen showtime slot."""
    sent = 0
    changed = False
    for st in candidates:
        if st.id not in newly_seen:
            continue
        sig = f"{st.key()}::live"
        if sig in state["alerted"]:
            continue
        link = st.purchase_url or st.seatmap_url
        body = format_alert(st.movie_title, st.format_label or "70mm", st.when_iso or "showtime", link, False)
        if _emit(notifier, body):
            state["alerted"][sig] = int(time.time())
            sent += 1
            changed = True
    return sent, changed


def check_once(cfg: Config, client: AmcClient, notifier: Notifier | None, state: dict) -> tuple[int, bool]:
    """One poll. Returns (alerts_sent, state_changed)."""
    showtimes = polite_fetch(client, cfg.movie_query)
    candidates = [st for st in showtimes if _matches_format(st, cfg.format_match)]

    newly_seen, changed = _record_sightings(cfg, state, candidates)
    sent = 0

    if cfg.wants("new_date"):
        n, c = _alert_new_dates(cfg, notifier, state, candidates)
        sent += n
        changed = changed or c
    if cfg.wants("adjacent_pair"):
        n, c = _alert_adjacent_pairs(cfg, notifier, state, candidates)
        sent += n
        changed = changed or c
    if cfg.wants("any_showtime"):
        n, c = _alert_any_showtime(cfg, notifier, state, candidates, newly_seen)
        sent += n
        changed = changed or c

    return sent, changed


def send_test_text(cfg: Config) -> None:
    """Send a one-off hello to every configured recipient to verify Twilio works."""
    problems = cfg.validate_for_alerts()
    # AMC settings aren't needed just to test texting.
    problems = [p for p in problems if not p.startswith("AMC_THEATRE_ID")]
    if problems:
        print("Cannot send test — configuration problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    body = (
        "🎬 Test from your Odyssey 70mm bot!\n"
        "This is the number that will text you when new AMC Lincoln Square "
        "dates or seats open up. You're all set."
    )
    notifier = Notifier(cfg)
    recipients = cfg.alert_numbers * cfg.has_twilio_channel() + cfg.alert_emails * cfg.has_email_channel()
    print(f"Sending test alert to: {', '.join(recipients)} …")
    try:
        ids = notifier.send(body, subject="🎬 Odyssey 70mm bot — test alert")
    except Exception as e:
        print(f"[error] send failed: {e}", file=sys.stderr)
        sys.exit(1)
    for i in ids:
        print(f"  ✓ {i}")
    print("Done — alerts should arrive within a few seconds.")


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
    print(f"Poll every ~{cfg.humane_poll_seconds()}s. Alert modes: {', '.join(cfg.alert_modes)}.")

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
    parser.add_argument(
        "--test-text", action="store_true", help="Send a one-off test text to ALERT_NUMBERS and exit."
    )
    args = parser.parse_args(argv)

    cfg = Config()
    if args.test_text:
        send_test_text(cfg)
        return
    run(cfg, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
