"""
Diagnostic: fetch AMC's showtimes page(s) and report what's actually in them.

    python -m amc_monitor.probe

Run this from the machine that runs the monitor. It fetches candidate URLs for
the configured theatre, and prints a short forensic report: HTTP status, page
size, whether it's a Cloudflare challenge, whether showtime data is embedded in
the HTML (and under which markers), and how often the movie title appears.
It also saves each fetched page to probe_<n>.html so the parser can be adapted
to the real structure. Read-only, single fetch per URL, no evasion.
"""

from __future__ import annotations

import re
import sys

import requests

from .amc_client import USER_AGENT
from .config import Config

MARKERS = [
    "__NEXT_DATA__",
    "showtimeId",
    "showtimes",
    "premiumFormat",
    "application/ld+json",
    "window.__data",
    "apollo_state",
]


def probe_url(url: str, movie_query: str, dump_path: str) -> None:
    print(f"\n=== {url}")
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=30,
        )
    except Exception as e:
        print(f"  fetch failed: {e}")
        return

    html = resp.text
    print(f"  status: {resp.status_code}   size: {len(html):,} bytes")

    lowered = html[:3000].lower()
    if "just a moment" in lowered or "cf-mitigated" in str(resp.headers).lower():
        print("  !! Looks like a Cloudflare challenge page — content is not real showtimes.")

    title_hits = len(re.findall(re.escape(movie_query), html, re.IGNORECASE))
    print(f"  occurrences of {movie_query!r}: {title_hits}")

    for marker in MARKERS:
        count = html.count(marker)
        if count:
            print(f"  marker {marker!r}: {count}x")

    # Show a small sample of JSON-ish keys near the movie title, if present.
    m = re.search(re.escape(movie_query), html, re.IGNORECASE)
    if m:
        start = max(0, m.start() - 300)
        snippet = html[start : m.start() + 300].replace("\n", " ")
        keys = sorted(set(re.findall(r'"([A-Za-z][A-Za-z0-9_]{2,30})"\s*:', snippet)))
        if keys:
            print(f"  JSON keys near first title hit: {', '.join(keys[:15])}")

    with open(dump_path, "w") as f:
        f.write(html)
    print(f"  saved page to {dump_path}")


def main() -> None:
    cfg = Config()
    slug = cfg.theatre_id or "amc-lincoln-square-13"
    urls = [
        f"https://www.amctheatres.com/movie-theatres/showtimes/{slug}",
        f"https://www.amctheatres.com/movie-theatres/new-york-city/{slug}/showtimes",
        f"https://www.amctheatres.com/movie-theatres/new-york-city/{slug}",
    ]
    print(f"Probing AMC pages for theatre {slug!r}, looking for {cfg.movie_query!r} …")
    for i, url in enumerate(urls, 1):
        probe_url(url, cfg.movie_query, f"probe_{i}.html")
    print(
        "\nDone. Paste the report above (not the .html files) back to the chat.\n"
        "If a page shows title hits but the monitor finds no showtimes, the\n"
        "parser needs adapting to that page's structure."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
