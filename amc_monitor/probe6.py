"""
Diagnostic stage 6: fetch dated pages the way the MONITOR does (plain requests)
and report how showtimes render — including sold-out ones.

    python3 -m amc_monitor.probe6                # tomorrow, +3 days, 2026-08-05
    python3 -m amc_monitor.probe6 2026-07-25 …   # explicit dates

Shows per date: HTTP status, page size, bookable anchors, every
movie/format class token for the theatre (sold out or not), 'sold out'
string count, and context around the first Odyssey token. Safe to paste.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date, timedelta

import requests

from .amc_client import DEFAULT_SHOWTIMES_URL, USER_AGENT
from .config import Config


def probe_date(base_url: str, theatre_slug: str, date_iso: str) -> None:
    url = f"{base_url}?date={date_iso}"
    print(f"\n=== {date_iso}  ({url})")
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, timeout=30)
    except Exception as e:
        print(f"  fetch failed: {e}")
        return
    html = resp.text
    print(f"  status {resp.status_code}, {len(html):,} bytes")
    if "just a moment" in html[:3000].lower():
        print("  !! challenge page")
        return

    anchors = re.findall(r'href="/showtimes/(\d+)"', html)
    print(f"  bookable anchors (/showtimes/<id>): {len(anchors)} ({len(set(anchors))} unique)")

    token_re = re.compile(r"([a-z0-9][a-z0-9\-]*?)-" + re.escape(theatre_slug) + r"-([a-z0-9]+)-\d+")
    tokens = Counter((m.group(1), m.group(2)) for m in token_re.finditer(html))
    print(f"  movie/format class tokens ({sum(tokens.values())} total):")
    for (movie, fmt), n in tokens.most_common(15):
        print(f"    {n:3d}x  {movie}  [{fmt}]")

    sold = len(re.findall(r"sold\s*out", html, re.IGNORECASE))
    print(f"  'sold out' strings: {sold}")

    m = re.search(r"the-odyssey[a-z0-9\-]*-" + re.escape(theatre_slug) + r"-[a-z0-9]+-\d+", html)
    if m:
        start = max(0, m.start() - 250)
        ctx = re.sub(r"\s+", " ", html[start : m.end() + 350])
        print(f"  first Odyssey token context:\n    …{ctx[:600]}…")
    else:
        print("  no Odyssey token anywhere on this date's page")


def main() -> None:
    cfg = Config()
    base_url = (cfg.showtimes_url or DEFAULT_SHOWTIMES_URL).rstrip("/").split("?")[0]
    theatre_slug = base_url.rstrip("/").rsplit("/", 2)[-2]

    if len(sys.argv) > 1:
        dates = sys.argv[1:]
    else:
        # The bookable frontier for a hot limited run sits ~a month out.
        t = date.today()
        dates = [(t + timedelta(days=n)).isoformat() for n in (29, 30, 31)] + ["2026-08-05"]

    print(f"Probing {theatre_slug} as the monitor fetches (plain requests, honest UA)…")
    for d in dates:
        probe_date(base_url, theatre_slug, d)
    print("\nDone. Paste everything above back to the chat.")


if __name__ == "__main__":
    main()
