"""
Polite AMC data client.

Design rules (read before changing):

* We identify ourselves honestly with a descriptive User-Agent. No fingerprint
  spoofing, no rotating identities to look like many browsers.
* We respect the server. `429`/`503` -> honor Retry-After and back off. If we hit
  a Cloudflare / anti-bot challenge, we DO NOT try to solve or evade it. We stop,
  surface it, and recommend the official API. Defeating that layer is exactly what
  this project refuses to do.
* Preferred path is the official AMC developer API (needs AMC_API_KEY). The HTML
  path is a best-effort read of the public page and is intentionally simple.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

# Honest, contactable identification. Edit the contact to your own.
USER_AGENT = "amc-70mm-odyssey-notifier/1.0 (personal seat-availability heads-up; contact: you@example.com)"

AMC_API_BASE = "https://api.amctheatres.com"


class AntiBotChallenge(RuntimeError):
    """Raised when the server returns an anti-bot challenge instead of data.

    We intentionally give up here rather than evading it.
    """


@dataclass
class Showtime:
    id: str
    movie_title: str
    format_label: str  # e.g. "IMAX 70mm"
    when_iso: str
    seatmap_url: str | None
    purchase_url: str | None

    def key(self) -> str:
        return f"{self.id}"


class AmcClient:
    def __init__(self, api_key: str | None, theatre_id: str | None):
        self.api_key = api_key
        self.theatre_id = theatre_id
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    # --- polite HTTP helper -------------------------------------------------

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=20, **kwargs)

        # Honor explicit slow-down signals.
        if resp.status_code in (429, 503):
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if (retry_after and retry_after.isdigit()) else 60
            raise _Backoff(wait)

        # Detect (but do NOT attempt to defeat) an anti-bot interstitial.
        server = resp.headers.get("Server", "").lower()
        looks_like_challenge = (
            resp.status_code in (403, 401)
            and ("cloudflare" in server or "cf-mitigated" in resp.headers or "just a moment" in resp.text[:2000].lower())
        )
        if looks_like_challenge:
            raise AntiBotChallenge(
                "AMC returned an anti-bot challenge. This tool will not evade it. "
                "Use the official AMC developer API (set AMC_API_KEY) or slow the poll rate."
            )

        resp.raise_for_status()
        return resp

    # --- public API path (preferred) ---------------------------------------

    def _fetch_via_api(self, movie_query: str) -> list[Showtime]:
        # AMC's developer API keys go in the X-AMC-Vendor-Key header.
        headers = {"X-AMC-Vendor-Key": self.api_key or ""}
        url = f"{AMC_API_BASE}/v2/theatres/{self.theatre_id}/showtimes"
        resp = self._get(url, headers=headers)
        data = resp.json()
        out: list[Showtime] = []
        for st in _iter_embedded(data, "showtimes"):
            title = (st.get("movieName") or "").strip()
            if movie_query.lower() not in title.lower():
                continue
            links = st.get("_links", {})
            out.append(
                Showtime(
                    id=str(st.get("id")),
                    movie_title=title,
                    format_label=(st.get("premiumFormat") or st.get("format", {}).get("name") or "").strip(),
                    when_iso=st.get("showDateTimeUtc") or st.get("showDateTimeLocal") or "",
                    seatmap_url=_href(links.get("seatmap")),
                    purchase_url=_href(links.get("dynamicPurchaseUrl")) or _href(links.get("purchase")),
                )
            )
        return out

    # --- HTML fallback (best-effort, no evasion) ----------------------------

    def _fetch_via_html(self, movie_query: str) -> list[Showtime]:
        # Public showtimes page. If this path starts returning challenges,
        # that's the signal to switch to the official API — not to evade.
        url = f"https://www.amctheatres.com/movie-theatres/showtimes/{self.theatre_id}"
        self.session.headers.update({"Accept": "text/html"})
        resp = self._get(url)
        self.session.headers.update({"Accept": "application/json"})
        return _parse_showtimes_html(resp.text, movie_query, self.theatre_id)

    # --- orchestration ------------------------------------------------------

    def fetch_showtimes(self, movie_query: str) -> list[Showtime]:
        if self.api_key:
            return self._fetch_via_api(movie_query)
        return self._fetch_via_html(movie_query)


class _Backoff(RuntimeError):
    def __init__(self, seconds: int):
        super().__init__(f"back off {seconds}s")
        self.seconds = seconds


def polite_fetch(client: AmcClient, movie_query: str, max_attempts: int = 4) -> list[Showtime]:
    """Fetch with exponential backoff on explicit slow-down signals."""
    attempt = 0
    while True:
        try:
            return client.fetch_showtimes(movie_query)
        except _Backoff as b:
            attempt += 1
            if attempt >= max_attempts:
                raise
            time.sleep(b.seconds * attempt)


# --- helpers ---------------------------------------------------------------


def _iter_embedded(data: dict, key: str):
    embedded = data.get("_embedded", {})
    items = embedded.get(key, [])
    return items if isinstance(items, list) else []


def _href(link) -> str | None:
    if isinstance(link, dict):
        return link.get("href")
    return None


def _parse_showtimes_html(html: str, movie_query: str, theatre_id: str | None) -> list[Showtime]:
    """
    Minimal, dependency-light extraction. AMC embeds showtime JSON in the page;
    this pulls the obvious title matches. Kept intentionally conservative — if the
    markup shifts, prefer wiring up AMC_API_KEY over fragile scraping heuristics.
    """
    import json
    import re

    results: list[Showtime] = []
    seen: set[str] = set()

    # AMC ships a __NEXT_DATA__ / embedded JSON blob; try to find showtime-ish objects.
    for match in re.finditer(r'\{"[^{}]*"showtimeId"[^{}]*\}', html):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        title = str(obj.get("movieName") or obj.get("title") or "")
        if movie_query.lower() not in title.lower():
            continue
        sid = str(obj.get("showtimeId") or obj.get("id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        results.append(
            Showtime(
                id=sid,
                movie_title=title,
                format_label=str(obj.get("premiumFormat") or obj.get("format") or ""),
                when_iso=str(obj.get("showDateTimeUtc") or obj.get("showtime") or ""),
                seatmap_url=obj.get("seatmapUrl"),
                purchase_url=obj.get("purchaseUrl"),
            )
        )
    return results
