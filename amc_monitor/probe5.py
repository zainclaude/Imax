"""
Diagnostic stage 5 (v2): load the showtimes page in a local Playwright browser,
record all traffic, and hunt for showtime data by MANY signals — title, movie
id, showtime-shaped keys, booking links, 2026 timestamps — plus read the
rendered DOM itself for showtime buttons.

    python3 -m amc_monitor.probe5

Prints no cookies or header values. Safe to paste.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

from .config import Config

ASSET_RE = re.compile(r"\.(js|css|woff2?|png|jpe?g|svg|ico|webp)(\?|$)")
URL_TRIM = 150


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright missing. Run:\n  pip3 install playwright\n  python3 -m playwright install chromium")
        sys.exit(1)

    cfg = Config()
    title = cfg.movie_query
    # Late at night "today" has zero remaining showtimes and renders only
    # "Try Tomorrow" panels — so probe a date that actually has listings.
    # Optionally pass a date: python3 -m amc_monitor.probe5 2026-08-05
    date = sys.argv[1] if len(sys.argv) > 1 else "tomorrow"
    url = (
        "https://www.amctheatres.com/movie-theatres/new-york-city/"
        f"amc-lincoln-square-13/showtimes?date={date}"
    )

    captured = []  # (method, url, mime, body)

    print(f"Loading {url} …")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_response(resp):
            try:
                ctype = resp.headers.get("content-type", "")
                if ASSET_RE.search(resp.url) or any(t in ctype for t in ("image/", "font/", "css")):
                    return
                captured.append((resp.request.method, resp.url, ctype, resp.text()))
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(12000)
        page.mouse.wheel(0, 6000)
        page.wait_for_timeout(6000)

        visible_text = page.locator("body").inner_text()
        # Rendered-DOM extraction: anything that looks like a showtime button.
        dom_links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.getAttribute('href'), text: (e.innerText||'').trim().slice(0,60)}))"
            ".filter(l => /showtime|ticket|seat/i.test(l.href) || /^\\d{1,2}:\\d{2}\\s*[ap]m$/i.test(l.text))",
        )
        buttons = page.eval_on_selector_all(
            "button",
            "els => els.map(e => (e.innerText||'').trim()).filter(t => /^\\d{1,2}:\\d{2}\\s*[ap]m$/i.test(t)).slice(0,30)",
        )
        browser.close()

    print(f"\nCaptured {len(captured)} non-asset responses.")
    print(f"Title visible in rendered page text: {'YES' if title.lower() in visible_text.lower() else 'NO'}")
    clock_times = re.findall(r"\b\d{1,2}:\d{2}\s*[ap]m\b", visible_text, re.IGNORECASE)
    print(f"Clock-time strings visible on page: {len(clock_times)} (sample: {clock_times[:6]})")

    # Derive the movie's numeric id from any response (slug like the-odyssey-76238).
    movie_id = None
    for _, _, _, body in captured:
        m = re.search(r"the-odyssey-(\d+)", body, re.IGNORECASE)
        if m:
            movie_id = m.group(1)
            break
    print(f"Movie id derived from slug: {movie_id}")

    needles = {
        f"title '{title}'": re.compile(re.escape(title), re.IGNORECASE),
        "movie id": re.compile(re.escape(movie_id)) if movie_id else None,
        "showtime keys": re.compile(r"showDateTime|sessionDate|showtimeId|performanceNumber", re.IGNORECASE),
        "booking links": re.compile(r"/showtimes/\d{5,}"),
        "2026 timestamps": re.compile(r"2026-\d\d-\d\dT\d\d:(?!00:00\.000Z)"),
    }

    print("\n-- response inventory (top 25 by size), with signal flags:")
    rows = sorted(captured, key=lambda r: -len(r[3]))[:25]
    for method, u, mime, body in rows:
        flags = [name for name, rx in needles.items() if rx and rx.search(body)]
        mime_short = (mime or "?").split(";")[0]
        print(f"   {len(body):>9,}B  {method:4} {mime_short:28} {u[:URL_TRIM]}")
        if flags:
            print(f"              signals: {', '.join(flags)}")

    print("\n-- rendered-DOM showtime candidates:")
    print(f"   links (href matches showtime/ticket/seat or text is a clock time): {len(dom_links)}")
    for l in dom_links[:15]:
        print(f"     {l.get('text','')!r} -> {l.get('href','')[:120]}")
    print(f"   buttons with clock-time text: {len(buttons)}")
    for b in buttons[:15]:
        print(f"     {b!r}")

    # Deep dive: any response with showtime keys or booking links gets sampled.
    print("\n-- deep dive on responses with showtime signals:")
    dove = 0
    for method, u, mime, body in captured:
        hits = [
            name
            for name, rx in needles.items()
            if rx and name not in (f"title '{title}'",) and rx.search(body)
        ]
        if not hits:
            continue
        dove += 1
        print(f"\n   == {method} {u[:URL_TRIM]}")
        print(f"      {mime.split(';')[0] if mime else '?'}, {len(body):,}B, signals: {', '.join(hits)}")
        for name in hits:
            m = needles[name].search(body)
            start = max(0, m.start() - 200)
            ctx = re.sub(r"\s+", " ", body[start : m.end() + 300])
            print(f"      [{name}] …{ctx[:450]}…")
    if not dove:
        print("   none")

    # Where do visible clock times come from? Show counts of clock times per response.
    print("\n-- clock-time density per response (top 5):")
    density = Counter()
    for i, (_, u, _, body) in enumerate(captured):
        n = len(re.findall(r"\b\d{1,2}:\d{2}\s*[ap]m\b", body, re.IGNORECASE))
        if n:
            density[u[:URL_TRIM]] = n
    for u, n in density.most_common(5):
        print(f"   {n:4d}x  {u}")
    if not density:
        print("   no response contains clock-time strings at all")

    print("\nDone. Paste everything above back to the chat.")


if __name__ == "__main__":
    main()
