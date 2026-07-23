"""
Diagnostic stage 2: dissect the saved probe_*.html pages locally (no network)
and print the structural samples needed to write a correct parser.

    python -m amc_monitor.probe2

Prints, per file:
  - every <script type="application/ld+json"> block (truncated)
  - context around the first occurrences of the movie title
  - inventory of <script> tags (id/type), to locate embedded state blobs
  - sample ISO datetimes near the title

Output is text about page structure only — safe to paste back to the chat.
"""

from __future__ import annotations

import os
import re

from .config import Config

TRUNC = 1200


def _clean(s: str, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", s)[:limit]


def dissect(path: str, movie_query: str) -> None:
    print(f"\n########## {path}")
    if not os.path.exists(path):
        print("  (missing — run `python -m amc_monitor.probe` first)")
        return
    with open(path) as f:
        html = f.read()
    print(f"  size: {len(html):,} bytes")

    # 1. ld+json blocks
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    print(f"\n  -- ld+json blocks: {len(blocks)}")
    for i, b in enumerate(blocks):
        b = b.strip()
        print(f"  [ld+json #{i}] {len(b):,} bytes:")
        print(f"    {_clean(b, TRUNC)}")

    # 2. script tag inventory (skip plain src includes)
    tags = re.findall(r"<script([^>]*)>", html)
    inline = [t for t in tags if "src=" not in t]
    print(f"\n  -- script tags: {len(tags)} total, {len(inline)} inline")
    for t in sorted(set(_clean(t, 120) for t in inline)):
        print(f"    <script{t}>")

    # 3. contexts around the movie title
    print(f"\n  -- first 4 contexts around {movie_query!r}:")
    for i, m in enumerate(re.finditer(re.escape(movie_query), html, re.IGNORECASE)):
        if i >= 4:
            break
        start = max(0, m.start() - 250)
        print(f"  [ctx {i}] …{_clean(html[start : m.end() + 250], 520)}…")

    # 4. ISO datetimes near the title (showtime-shaped strings)
    dates = re.findall(r"20\d\d-\d\d-\d\dT\d\d:\d\d[^\"'<\s]*", html)
    uniq = sorted(set(dates))
    print(f"\n  -- ISO datetimes on page: {len(dates)} total, {len(uniq)} unique")
    for d in uniq[:10]:
        print(f"    {d}")


def main() -> None:
    cfg = Config()
    for path in ("probe_1.html", "probe_2.html"):
        dissect(path, cfg.movie_query)
    print("\nDone. Paste everything above back to the chat.")


if __name__ == "__main__":
    main()
