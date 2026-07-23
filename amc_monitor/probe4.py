"""
Diagnostic stage 4: find the showtimes data endpoint inside a HAR capture.

    python -m amc_monitor.probe4 [path-to.har]     (default: showtimes.har)

Reads the HAR locally and reports, for every response mentioning the movie:
method, URL, content type, size, and (for JSON) the field names and a
showtime-shaped sample. Prints NO cookies and NO header values — the output is
safe to paste; the HAR file itself is not, so keep it local (it's gitignored).
"""

from __future__ import annotations

import json
import re
import sys

from .config import Config

MAX_KEYS = 25


def _json_keys(obj, depth=0, out=None):
    if out is None:
        out = set()
    if depth > 4 or len(out) > 200:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _json_keys(v, depth + 1, out)
    elif isinstance(obj, list):
        for v in obj[:5]:
            _json_keys(v, depth + 1, out)
    return out


def _find_showtime_samples(obj, path="$", hits=None):
    """Collect small dicts that look like individual showtimes."""
    if hits is None:
        hits = []
    if len(hits) >= 3:
        return hits
    if isinstance(obj, dict):
        keys_lower = {k.lower() for k in obj}
        if any("showtime" in k or "showdatetime" in k or "sessiondate" in k for k in keys_lower) or (
            {"movieName", "showDateTimeLocal"} & set(obj)
        ):
            hits.append((path, {k: obj[k] for k in list(obj)[:12]}))
        for k, v in obj.items():
            _find_showtime_samples(v, f"{path}.{k}", hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:10]):
            _find_showtime_samples(v, f"{path}[{i}]", hits)
    return hits


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "showtimes.har"
    cfg = Config()
    needle = cfg.movie_query.lower()

    try:
        with open(path) as f:
            har = json.load(f)
    except FileNotFoundError:
        print(f"{path} not found — export the HAR from Chrome into this folder first.")
        return
    except json.JSONDecodeError as e:
        print(f"{path} isn't valid JSON/HAR: {e}")
        return

    entries = har.get("log", {}).get("entries", [])
    print(f"HAR has {len(entries)} requests. Searching responses for {cfg.movie_query!r} …")

    found = 0
    for e in entries:
        req = e.get("request", {})
        resp = e.get("response", {})
        content = resp.get("content", {}) or {}
        text = content.get("text") or ""
        if needle not in text.lower():
            continue
        url = req.get("url", "")
        if re.search(r"\.(js|css|woff2?|png|jpe?g|svg)(\?|$)", url):
            continue  # code/assets, not data

        found += 1
        mime = content.get("mimeType", "?")
        print(f"\n== HIT {found}: {req.get('method', '?')} {url}")
        print(f"   response: {mime}, {len(text):,} bytes, HTTP {resp.get('status')}")
        header_names = sorted({h.get('name', '').lower() for h in req.get('headers', [])})
        interesting = [h for h in header_names if h in ("authorization", "x-api-key", "apikey", "x-amc-vendor-key", "x-csrf-token")]
        print(f"   auth-ish request headers present: {interesting or 'none'}")
        if req.get("method") == "POST":
            post = (req.get("postData", {}) or {}).get("text", "")
            post_sample = re.sub(r"\s+", " ", post)[:400]
            print(f"   POST body sample: {post_sample}")

        if "json" in mime or text.lstrip().startswith(("{", "[")):
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                print("   (response is not clean JSON — likely a streamed/HTML doc)")
                continue
            keys = sorted(_json_keys(obj))
            print(f"   JSON field names ({len(keys)}): {', '.join(keys[:MAX_KEYS])}{' …' if len(keys) > MAX_KEYS else ''}")
            for p, sample in _find_showtime_samples(obj):
                print(f"   showtime-shaped object at {p}:")
                print(f"     {json.dumps(sample, default=str)[:500]}")
        else:
            print("   (non-JSON response — probably the page document itself)")

    if not found:
        print(
            "\nNo non-asset responses contained the movie title. Either the "
            "showtimes hadn't loaded before the HAR was exported (reload and "
            "re-export after the times are visible), or the title only appears "
            "inside .js bundles (tell me — different approach needed)."
        )
    else:
        print("\nDone. Paste everything above back to the chat (NOT the .har file).")


if __name__ == "__main__":
    main()
