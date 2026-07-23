"""
Diagnostic stage 5: load the showtimes page in a local real browser (Playwright)
and record which network responses actually carry the showtime data.

    pip3 install playwright
    python3 -m playwright install chromium
    python3 -m amc_monitor.probe5

One page load, from your own machine, watching the page's own traffic — the
automated equivalent of reading the DevTools Network tab. Prints the same
report style as probe4: URLs, methods, JSON field names, showtime-shaped
samples. No cookies or header values are printed.
"""

from __future__ import annotations

import json
import re
import sys

from .config import Config
from .probe4 import _find_showtime_samples, _json_keys

ASSET_RE = re.compile(r"\.(js|css|woff2?|png|jpe?g|svg|ico|webp)(\?|$)")


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright missing. Run:\n  pip3 install playwright\n  python3 -m playwright install chromium")
        sys.exit(1)

    cfg = Config()
    needle = cfg.movie_query.lower()
    url = "https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13/showtimes"

    captured = []  # (method, url, mime, body)

    print(f"Loading {url} in a local Chromium and recording responses…")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_response(resp):
            try:
                ctype = resp.headers.get("content-type", "")
                if ASSET_RE.search(resp.url) or any(
                    t in ctype for t in ("image/", "font/", "css")
                ):
                    return
                body = resp.text()
                captured.append((resp.request.method, resp.url, ctype, body))
            except Exception:
                pass  # bodies of redirects/aborted requests aren't readable

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(12000)  # let the app fetch its data
        # Nudge lazy content.
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(5000)
        visible = page.locator("body").inner_text()
        browser.close()

    print(f"Captured {len(captured)} non-asset responses.")
    on_screen = needle in visible.lower()
    print(f"Movie title visible on the rendered page: {'YES' if on_screen else 'NO'}")

    found = 0
    for method, u, mime, body in captured:
        if needle not in body.lower():
            continue
        found += 1
        print(f"\n== HIT {found}: {method} {u[:160]}")
        print(f"   response: {mime or '?'}, {len(body):,} bytes")
        stripped = body.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                print("   (JSON-ish but not parseable as a whole)")
                continue
            keys = sorted(_json_keys(obj))
            print(f"   JSON field names ({len(keys)}): {', '.join(keys[:25])}{' …' if len(keys) > 25 else ''}")
            for path, sample in _find_showtime_samples(obj):
                print(f"   showtime-shaped object at {path}:")
                print(f"     {json.dumps(sample, default=str)[:500]}")
        else:
            # Non-JSON (document / RSC stream): show context around first title hit.
            m = re.search(re.escape(cfg.movie_query), body, re.IGNORECASE)
            start = max(0, m.start() - 200)
            ctx = re.sub(r"\s+", " ", body[start : m.end() + 400])
            print(f"   context: …{ctx[:600]}…")
            # And any ISO datetimes near showtime-looking content.
            dates = sorted(set(re.findall(r"20\d\d-\d\d-\d\dT\d\d:\d\d[^\"'\\\s]{0,10}", body)))
            if dates:
                print(f"   ISO datetimes in this response ({len(dates)} unique): {', '.join(dates[:8])}")

    if not found:
        print(
            "\nNo captured response contained the title. If the title WAS visible on the\n"
            "rendered page (see above), the data hides in a response we couldn't read —\n"
            "paste this whole report anyway."
        )
    else:
        print("\nDone. Paste everything above back to the chat.")


if __name__ == "__main__":
    main()
