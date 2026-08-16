"""
ingest.py
=========
Getting listings into the system. Four paths, in descending order of how much
of the work they do for you and ascending order of how much they actually
get used:

  1. `ingest_text`    — paste a listing. The workhorse.
  2. `ingest_url`     — fetch one page, robots-gated, and extract from it.
  3. `ingest_batch`   — paste several listings separated by a blank line.
  4. `discover_reddit`— the one genuinely automatable search channel.

`ingest_text` is the primary path and is not a fallback. A phone photo of a
broker's WhatsApp message, transcribed and pasted, goes through exactly the
same pipeline as a portal listing: extraction, dedup against everything seen
before, geolocation, scoring, price history. The system's value is downstream
of intake, so intake being manual costs nothing that matters.

Every path records where the text came from, and every fetch records the
robots.txt decision that permitted it — including the refusals. A discovery
log you can audit afterwards is the point; "the crawler got it" is not an
answer to "where did this come from".
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from findfarms.core import pipeline
from findfarms.discovery import robots, sources
from findfarms.store.db import DATA_DIR, _write, _read

DISCOVERY_LOG = DATA_DIR / "discovery_log.json"

# Below this, the text is too thin to be a listing. Extraction would produce
# a record with nothing in it, which is worse than no record: it occupies a
# row, pollutes the comparable set and looks like coverage.
MIN_LISTING_CHARS = 40


def _log(entry: dict) -> None:
    log = _read(DISCOVERY_LOG, [])
    entry["at"] = datetime.now().isoformat(timespec="seconds")
    log.append(entry)
    _write(DISCOVERY_LOG, log[-5000:])


def discovery_log(limit: int = 200) -> list:
    return list(reversed(_read(DISCOVERY_LOG, [])))[:limit]


def ingest_text(text: str, source: str = "manual", source_url: str = "",
                extra: dict | None = None,
                force_property_id: str | None = None) -> dict:
    """Take one pasted listing through the full pipeline."""
    text = (text or "").strip()
    if len(text) < MIN_LISTING_CHARS:
        return {"ok": False,
                "error": f"Too short to be a listing ({len(text)} characters). "
                         f"Paste the full text — price, size and location at "
                         f"minimum, and the description if there is one."}

    result = pipeline.ingest(text, source=source, source_url=source_url,
                             extra=extra, force_property_id=force_property_id)
    _log({"action": "ingest_text", "source": source, "url": source_url,
          "property_id": result["property_id"], "is_new": result["is_new"],
          "chars": len(text)})
    result["ok"] = True
    return result


def ingest_batch(blob: str, source: str = "manual") -> list[dict]:
    """Several listings in one paste, separated by blank lines.

    Splitting on blank lines rather than anything cleverer because that is
    how people actually paste a handful of listings out of a portal or a
    WhatsApp thread. Anything that does not look like a listing is reported
    and skipped, never silently dropped — a skipped listing the user thinks
    was imported is a gap they will not notice.
    """
    chunks = [c.strip() for c in re.split(r"\n\s*\n", blob or "") if c.strip()]
    out = []
    for chunk in chunks:
        if len(chunk) < MIN_LISTING_CHARS:
            out.append({"ok": False, "text": chunk[:80],
                        "error": "Too short — skipped."})
            continue
        # A bare URL on its own line is a fetch instruction, not a listing.
        if re.fullmatch(r"https?://\S+", chunk):
            out.append(ingest_url(chunk, source=source))
        else:
            out.append(ingest_text(chunk, source=source))
    # Comparables shift as the set grows, so scores are only meaningful after
    # the whole batch has landed.
    if any(r.get("ok") for r in out):
        pipeline.rescore_all()
    return out


def ingest_url(url: str, source: str = "") -> dict:
    """Fetch one page and extract from it — only if robots.txt permits.

    Refusals are returned as results with the reason, not raised, so a batch
    containing one disallowed URL still processes the rest and the user sees
    exactly which URL was skipped and why.
    """
    src = source or _source_name_for(url)
    policy = _policy_for(url)

    if policy == sources.MANUAL_ONLY:
        _log({"action": "fetch_refused", "url": url, "reason": "manual-only source"})
        return {"ok": False, "url": url, "refused": True,
                "error": (f"{src} is a manual-only source: its terms of use "
                          f"prohibit automated collection, or it requires a login. "
                          f"Open the page yourself and paste the listing text into "
                          f"the box instead — it goes through exactly the same "
                          f"pipeline.")}

    try:
        resp = robots.fetch(url)
    except robots.NotPermitted as e:
        _log({"action": "fetch_refused", "url": url, "reason": str(e)})
        return {"ok": False, "url": url, "refused": True, "error": str(e)}

    _log({"action": "fetch", "url": url, "status": resp.get("status"),
          "robots": resp.get("robots_note"), "ok": resp.get("ok")})

    if not resp.get("ok"):
        return {"ok": False, "url": url,
                "error": f"Fetch failed ({resp.get('status')}): {resp.get('error')}"
                         + (f" {resp.get('note')}" if resp.get("note") else "")}

    wall = robots.looks_like_access_wall(resp["body"])
    if wall:
        return {"ok": False, "url": url, "refused": True,
                "error": (f"The page returned a {wall} rather than content. Not "
                          f"attempting to work around it. Open the page in your "
                          f"browser and paste the listing text in.")}

    text = html_to_text(resp["body"])
    if len(text) < MIN_LISTING_CHARS:
        return {"ok": False, "url": url,
                "error": "Fetched, but no readable listing text was found — the "
                         "page is probably rendered by JavaScript."}
    return ingest_text(text, source=src, source_url=url)


def html_to_text(html: str) -> str:
    """Strip HTML to readable text.

    Deliberately crude — no parser dependency, and precision does not matter
    much because the extractor works on keywords and patterns rather than on
    document structure. Scripts and styles are removed first; leaving them in
    puts JSON payloads and CSS into the text where they generate phantom
    phone numbers and prices.
    """
    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&rsquo;", "'"),
                    ("&rupee;", "₹"), ("&#8377;", "₹")):
        s = s.replace(ent, ch)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def _source_name_for(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().replace("www.", "")
    for s in sources.SOURCES:
        if s["key"] in host:
            return s["name"]
    return host or "web"


def _policy_for(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().replace("www.", "")
    for s in sources.SOURCES:
        if s["key"] in host:
            return s["policy"]
    # An unknown host is not automatically fetchable. It gets the robots gate
    # (which fails closed), but the user should confirm the site's own terms
    # before treating a small broker site as open.
    return sources.OPEN


def discover_reddit(queries: list[str] | None = None, limit_per_query: int = 25,
                    auto_ingest: bool = False) -> dict:
    """Search Reddit's public JSON interface.

    The only search channel here that can run unattended. Volume for this
    niche is low — this is not going to find you a farm on its own — but it
    costs nothing to run and occasionally surfaces owner-direct posts and,
    more usefully, candid local discussion of specific corridors that no
    listing will ever contain.

    `auto_ingest` defaults to False on purpose: Reddit results are mostly
    discussion, not listings, and auto-ingesting them fills the database with
    non-properties. Review the hits, ingest the real ones.
    """
    queries = queries or [
        "agricultural land Mysore", "farm land Mysuru", "farmland near Mysore",
        "buying agricultural land Karnataka", "land Hunsur", "land Nanjangud",
    ]
    hits, errors = [], []
    for q in queries:
        url = sources.SOURCE_BY_KEY["reddit"]["json"].format(q=q.replace(" ", "+"))
        try:
            resp = robots.fetch(url)
        except robots.NotPermitted as e:
            errors.append({"query": q, "error": str(e)})
            _log({"action": "fetch_refused", "url": url, "reason": str(e)})
            continue
        _log({"action": "fetch", "url": url, "status": resp.get("status"),
              "robots": resp.get("robots_note"), "ok": resp.get("ok")})
        if not resp.get("ok"):
            errors.append({"query": q, "error": f"HTTP {resp.get('status')}"})
            continue
        try:
            data = json.loads(resp["body"])
        except ValueError:
            errors.append({"query": q, "error": "Response was not JSON."})
            continue
        for child in (data.get("data", {}).get("children") or [])[:limit_per_query]:
            d = child.get("data", {})
            body = f"{d.get('title', '')}\n{d.get('selftext', '')}".strip()
            if len(body) < MIN_LISTING_CHARS:
                continue
            hit = {"query": q, "title": d.get("title", ""),
                   "url": "https://www.reddit.com" + d.get("permalink", ""),
                   "subreddit": d.get("subreddit", ""), "text": body[:4000]}
            hits.append(hit)
            if auto_ingest:
                ingest_text(hit["text"], source="Reddit", source_url=hit["url"])
    if auto_ingest and hits:
        pipeline.rescore_all()
    return {"hits": hits, "errors": errors, "queries": queries,
            "auto_ingested": auto_ingest}


def worklist(limit_geo: int = 9, limit_property: int = 6) -> dict:
    """The manual search worklist: what to open, grouped by source.

    This is the practical output of the discovery layer. Twenty minutes
    clicking through these and pasting what looks relevant will populate the
    database faster than any crawler this system could legally run.
    """
    queries = sources.query_matrix(limit_geo=limit_geo,
                                   limit_property=limit_property)
    grouped = {}
    for s in sources.SOURCES:
        grouped[s["key"]] = {
            "name": s["name"], "policy": s["policy"], "note": s["note"],
            "urls": sources.search_urls(s["key"], queries),
        }
    return {"queries": queries, "sources": grouped,
            "coverage_note": sources.coverage_note(),
            "total_searches": len(queries) * len(sources.SOURCES)}
