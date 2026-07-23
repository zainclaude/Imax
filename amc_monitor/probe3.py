"""
Diagnostic stage 3: hunt for showtime-shaped structures in the saved
showtimes page (probe_2.html).

    python -m amc_monitor.probe3

Looks for the things an actual showtime listing must contain — booking links,
clock times, premium-format labels — and prints their contexts so the parser
can be built against the real markup. Local file only, no network.
"""

from __future__ import annotations

import os
import re

TARGET = "probe_2.html"
PATTERNS = {
    "booking links (/showtimes/<id>)": r"/showtimes/\d{6,}",
    "clock times (7:00pm style)": r"\b\d{1,2}:\d{2}\s*[apAP]\.?[mM]\.?\b",
    "'70mm' label": r"70\s?mm",
    "'IMAX' label": r"IMAX[A-Za-z0-9 ]{0,20}",
    "ticket/seat URLs": r"https?://[^\"'\\\s]*(?:ticket|seat|purchase)[^\"'\\\s]*",
    "showtime-ish JSON keys": r'"(showDateTime[A-Za-z]*|sessionDateTimeLocal|performanceNumber|showtimeId|formatName)"',
}


def _clean(s: str, limit: int = 420) -> str:
    return re.sub(r"\s+", " ", s)[:limit]


def main() -> None:
    if not os.path.exists(TARGET):
        print(f"{TARGET} missing — run `python -m amc_monitor.probe` first.")
        return
    with open(TARGET) as f:
        html = f.read()
    print(f"Dissecting {TARGET} ({len(html):,} bytes) for showtime structures…")

    for label, pattern in PATTERNS.items():
        matches = list(re.finditer(pattern, html))
        uniq = sorted(set(m.group(0) for m in matches))
        print(f"\n== {label}: {len(matches)} matches, {len(uniq)} unique")
        for u in uniq[:8]:
            print(f"   {u}")
        # Context around the first two matches, to reveal surrounding structure.
        for i, m in enumerate(matches[:2]):
            start = max(0, m.start() - 260)
            print(f"   [ctx {i}] …{_clean(html[start : m.end() + 260])}…")

    print("\nDone. Paste everything above back to the chat.")


if __name__ == "__main__":
    main()
