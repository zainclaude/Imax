"""
Helper: look up AMC theatre ids by name (requires AMC_API_KEY).

    python -m amc_monitor.find_theatre "Lincoln Square"

Prints matching theatres and their ids so you can set AMC_THEATRE_ID correctly.
"""

from __future__ import annotations

import sys

import requests

from .amc_client import AMC_API_BASE, USER_AGENT
from .config import Config


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('Usage: python -m amc_monitor.find_theatre "<name>"', file=sys.stderr)
        sys.exit(1)
    query = " ".join(argv).lower()

    cfg = Config()
    if not cfg.amc_api_key:
        print("AMC_API_KEY is required for theatre lookup.", file=sys.stderr)
        print("Get one at https://developers.amc.com/ — the sanctioned way to read AMC data.", file=sys.stderr)
        sys.exit(1)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "X-AMC-Vendor-Key": cfg.amc_api_key}
    resp = requests.get(f"{AMC_API_BASE}/v2/theatres?pageSize=500", headers=headers, timeout=20)
    resp.raise_for_status()
    theatres = resp.json().get("_embedded", {}).get("theatres", [])

    hits = [t for t in theatres if query in (t.get("name") or "").lower()]
    if not hits:
        print(f"No theatre matched {query!r}.")
        return
    for t in hits:
        print(f"{t.get('id')}\t{t.get('name')}\t{t.get('city', '')}, {t.get('state', '')}")


if __name__ == "__main__":
    main()
