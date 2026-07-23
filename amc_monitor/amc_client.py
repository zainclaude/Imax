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

import re
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


DEFAULT_SHOWTIMES_URL = (
    "https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13/showtimes"
)


class AmcClient:
    def __init__(self, api_key: str | None, theatre_id: str | None, showtimes_url: str | None = None):
        self.api_key = api_key
        self.theatre_id = theatre_id
        self.showtimes_url = (showtimes_url or DEFAULT_SHOWTIMES_URL).rstrip("/").split("?")[0]
        # The theatre slug as it appears in showtime anchor classes.
        self.theatre_slug = self.showtimes_url.rstrip("/").rsplit("/", 2)[-2]
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

    # --- dated public page (no API key needed; no evasion) ------------------

    def fetch_dated(self, date_iso: str) -> list[Showtime]:
        """Fetch one date's showtimes from the public page.

        The dated page (?date=YYYY-MM-DD) is fully server-rendered: every
        showtime is an anchor like
          <a class="…the-odyssey-76238-amc-lincoln-square-13-imax70mm-0…"
             href="/showtimes/144316365"><time dateTime="2026-08-05T13:00:00.000Z">…
        so movie, theatre, format, time, and booking link are all in plain HTML.
        If this path starts returning challenges, the signal is to switch to the
        official API — not to evade.
        """
        url = f"{self.showtimes_url}?date={date_iso}"
        self.session.headers.update({"Accept": "text/html"})
        try:
            resp = self._get(url)
        finally:
            self.session.headers.update({"Accept": "application/json"})
        return parse_dated_page(resp.text, self.theatre_slug)

    # --- orchestration ------------------------------------------------------

    def fetch_showtimes(self, movie_query: str) -> list[Showtime]:
        if not self.api_key:
            raise RuntimeError("fetch_showtimes requires AMC_API_KEY; use fetch_dated for the page path")
        return self._fetch_via_api(movie_query)


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


ANCHOR_RE = re.compile(r'<a\b[^>]*href="/showtimes/(\d+)"[^>]*>.*?</a>', re.DOTALL)
CLASS_RE = re.compile(r'class="([^"]*)"')
DATETIME_RE = re.compile(r'dateTime="([^"]+)"')


def parse_dated_page(html: str, theatre_slug: str) -> list[Showtime]:
    """Extract showtimes from a server-rendered dated showtimes page.

    Structure (verified against the live page, 2026-07): each showtime is an
    anchor whose class tokens encode `{movie-slug}-{theatre-slug}-{format}-{n}`,
    with the booking href `/showtimes/<id>` and a `<time dateTime="…Z">` inside.
    """
    results: list[Showtime] = []
    seen: set[str] = set()

    movie_fmt_re = re.compile(
        r"(?:^|\s)([a-z0-9][a-z0-9\-]*?)-" + re.escape(theatre_slug) + r"-([a-z0-9]+)-\d+(?:\s|$|-)"
    )

    for m in ANCHOR_RE.finditer(html):
        sid = m.group(1)
        if sid in seen:
            continue
        tag = m.group(0)
        cls = CLASS_RE.search(tag)
        dt = DATETIME_RE.search(tag)
        movie_slug, fmt = "", ""
        if cls:
            mf = movie_fmt_re.search(cls.group(1))
            if mf:
                movie_slug, fmt = mf.group(1), mf.group(2)
        seen.add(sid)
        results.append(
            Showtime(
                id=sid,
                movie_title=movie_slug,  # slug form, e.g. "the-odyssey-76238"
                format_label=fmt,  # e.g. "imax70mm"
                when_iso=dt.group(1) if dt else "",
                seatmap_url=None,
                purchase_url=f"https://www.amctheatres.com/showtimes/{sid}",
            )
        )
    return results
