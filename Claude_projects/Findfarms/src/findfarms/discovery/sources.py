"""
sources.py
==========
The source registry and the keyword matrix, plus an honest statement of what
each channel can and cannot be collected from automatically.

Read this before expecting the system to fill itself
----------------------------------------------------
The brief asks for discovery across property portals, YouTube, Instagram,
Facebook, Reddit, broker sites and search engines. Those channels are not
equally accessible, and pretending otherwise would produce a tool that
appears to be scanning everything while actually returning nothing. So each
source carries an explicit `policy`:

    OPEN            Publicly readable, robots-permitting. The crawler may
                    fetch it, subject to the robots gate.
    API_REQUIRED    Has an official API. Use it, with the user's own key.
                    No key configured means this source is simply off.
    MANUAL_ONLY     Technically reachable but restricted by terms of service,
                    login walls or anti-automation measures. The system will
                    NOT fetch these. It generates the search URLs for you to
                    open yourself, and you paste back what you find.
    OFF             Not used at all.

The large Indian property portals and the social platforms are almost all
MANUAL_ONLY, and that is a deliberate, considered setting rather than a
technical limitation:

  * MagicBricks, 99acres, Housing.com and OLX all prohibit automated
    collection in their terms of use. Their robots.txt is not the binding
    constraint; the terms are.
  * Instagram and Facebook require authentication for essentially all
    content. Fetching them means either logging in with credentials — which
    this system holds none of, structurally — or using the Graph API, which
    does not expose the marketplace and group content this use case wants.
  * YouTube has a proper Data API. That is genuinely usable and is wired as
    API_REQUIRED, needing the user's own key.
  * Reddit has a documented public JSON interface with a stated rate limit,
    usable with a descriptive user agent.

The result is that **the primary intake path for this system is
human-assisted, not autonomous** — and that is the right shape for the task
anyway. Land discovery around Mysuru genuinely runs through brokers,
WhatsApp forwards, village contacts and driving around, none of which a
crawler reaches. The system's value was never in fetching the listing; it is
in what happens to the listing afterwards: dedup against everything seen
before, independent geolocation, evidence-weighted scoring, price history
across months. Those work identically whether the text arrived by crawler or
by paste.

`search_urls()` therefore produces the full keyword × geography matrix as
ready-to-open links. Twenty minutes with those, pasting what looks relevant
into the ingest box, populates the database faster than any scraper would —
and it is the part of the workflow that stays legal as terms change.
"""

from __future__ import annotations

import itertools
from urllib.parse import quote_plus

OPEN = "OPEN"
API_REQUIRED = "API_REQUIRED"
MANUAL_ONLY = "MANUAL_ONLY"
OFF = "OFF"

# ------------------------------------------------------------ keywords ----

GEO_KEYWORDS = [
    "Mysore", "Mysuru", "Hunsur", "Nanjangud", "Bannur", "T Narasipura",
    "H D Kote", "K R Nagar", "Srirangapatna",
    # Corridor and village terms that surface listings the taluk names miss.
    "Hunsur Road Mysore", "Nanjangud Road Mysore", "Bannur Road Mysore",
    "T Narasipura Road Mysore", "H D Kote Road Mysore", "Bogadi Mysore",
    "Ilwala", "Yelwal", "Bilikere", "Varuna Mysore", "Kadakola",
    "Jayapura Mysore", "Kalale", "Sindhuvalli", "Hadinaru",
]

PROPERTY_KEYWORDS = [
    "agricultural land", "agriculture land", "farmland", "farm land",
    "farm property", "plantation", "land for sale", "acre land",
    "owner selling", "direct owner", "urgent sale", "family property",
    "distress sale", "motivated seller",
]

# Terms that surface the specific things this buyer cares about. Paired with
# a geography, these find listings the generic terms bury.
QUALIFIER_KEYWORDS = [
    "borewell", "canal water", "coconut plantation", "arecanut", "farm house",
    "road facing", "converted", "RTC", "water source",
]

# ------------------------------------------------------------- sources ----

SOURCES = [
    # -- usable automatically ---------------------------------------------
    {"key": "reddit", "name": "Reddit", "policy": OPEN,
     "search": "https://www.reddit.com/search/?q={q}",
     "json": "https://www.reddit.com/search.json?q={q}&limit=50",
     "note": "Public JSON interface. NOTE: as checked on 2026-08-14, Reddit's "
             "robots.txt disallows generic crawlers, so the robots gate refuses "
             "these fetches and discover_reddit() returns refusals rather than "
             "results — which is the gate working correctly, not a bug. Left as "
             "OPEN because the policy is Reddit's to change and the gate reads it "
             "live each hour; if you want this channel, use Reddit's official API "
             "with your own credentials, or search it manually. Low volume for "
             "this niche either way, though r/bangalore and r/india threads "
             "occasionally carry owner-direct posts and candid local commentary "
             "on specific corridors."},

    {"key": "youtube", "name": "YouTube", "policy": API_REQUIRED,
     "search": "https://www.youtube.com/results?search_query={q}",
     "api_env": "YOUTUBE_API_KEY",
     "note": "YouTube Data API v3 with your own key. Genuinely valuable here — "
             "Karnataka land brokers post walkthrough videos with far more "
             "detail than any text listing, and the video often shows the "
             "borewell running, the road surface and the actual crop. Without "
             "a key this stays a manual search."},

    # -- manual only, and why ----------------------------------------------
    {"key": "magicbricks", "name": "MagicBricks", "policy": MANUAL_ONLY,
     "search": "https://www.magicbricks.com/property-for-sale/agricultural-land-real-estate-mysore?q={q}",
     "note": "Terms of use prohibit automated collection. Open the search "
             "yourself and paste listings in."},
    {"key": "99acres", "name": "99acres", "policy": MANUAL_ONLY,
     "search": "https://www.99acres.com/search/property/buy/mysore?keyword={q}",
     "note": "Terms of use prohibit automated collection."},
    {"key": "olx", "name": "OLX India", "policy": MANUAL_ONLY,
     "search": "https://www.olx.in/items/q-{q}",
     "note": "Terms prohibit scraping. Often the best source for owner-direct "
             "rural listings, so worth checking manually and regularly."},
    {"key": "housing", "name": "Housing.com", "policy": MANUAL_ONLY,
     "search": "https://housing.com/in/buy/searches/{q}",
     "note": "Terms prohibit automated collection."},
    {"key": "quikr", "name": "Quikr", "policy": MANUAL_ONLY,
     "search": "https://www.quikr.com/search?q={q}",
     "note": "Terms prohibit automated collection."},
    {"key": "facebook", "name": "Facebook groups / Marketplace", "policy": MANUAL_ONLY,
     "search": "https://www.facebook.com/marketplace/mysore/search?query={q}",
     "note": "Requires authentication for essentially everything. This system "
             "holds no credentials and does not log in. Local Kannada-language "
             "land groups are among the richest sources that exist for this "
             "search — join them yourself and paste posts in."},
    {"key": "instagram", "name": "Instagram", "policy": MANUAL_ONLY,
     "search": "https://www.instagram.com/explore/tags/{tag}/",
     "note": "Authentication required; automated access prohibited. Several "
             "Mysuru land brokers post reels with location and price."},
    {"key": "google", "name": "Search engine", "policy": MANUAL_ONLY,
     "search": "https://www.google.com/search?q={q}",
     "note": "Automated querying is against the terms. The generated links are "
             "for you to open. This is the highest-yield manual channel — it "
             "surfaces small local broker sites that no portal indexes."},
    {"key": "indiaproperty", "name": "Local broker sites", "policy": MANUAL_ONLY,
     "search": "https://www.google.com/search?q={q}+site%3A.in+broker+contact",
     "note": "Small Mysuru broker sites vary in their terms and most have no "
             "robots.txt at all. Check each site's own terms before treating "
             "it as OPEN — an absent robots.txt is not permission."},
]

SOURCE_BY_KEY = {s["key"]: s for s in SOURCES}


def automatable() -> list[dict]:
    return [s for s in SOURCES if s["policy"] in (OPEN, API_REQUIRED)]


def manual_sources() -> list[dict]:
    return [s for s in SOURCES if s["policy"] == MANUAL_ONLY]


# ------------------------------------------------------------- queries ----

def query_matrix(limit_geo: int | None = None,
                 limit_property: int | None = None,
                 include_qualifiers: bool = False) -> list[str]:
    """Every geography × property-keyword combination, as search strings.

    The full matrix is large (24 geographies × 14 property terms = 336, plus
    qualifiers). That is intentional — the point of a matrix is coverage, and
    the terms surface genuinely different listing sets. Sellers who write
    "farm land" do not write "agricultural land", and the owner-direct
    listings this buyer most wants cluster in the informal phrasings.
    """
    geos = GEO_KEYWORDS[:limit_geo] if limit_geo else GEO_KEYWORDS
    props = PROPERTY_KEYWORDS[:limit_property] if limit_property else PROPERTY_KEYWORDS
    out = [f"{p} {g}" for g, p in itertools.product(geos, props)]
    if include_qualifiers:
        out += [f"{q} land {g}" for g, q in
                itertools.product(geos[:9], QUALIFIER_KEYWORDS)]
    return out


def search_urls(source_key: str, queries: list[str] | None = None) -> list[dict]:
    """Ready-to-open search URLs for one source.

    For MANUAL_ONLY sources this is the actual deliverable: a worklist to
    click through. Each entry says plainly whether the system may fetch it or
    whether a human must.
    """
    src = SOURCE_BY_KEY.get(source_key)
    if not src:
        return []
    queries = queries or query_matrix(limit_geo=9, limit_property=6)
    out = []
    for q in queries:
        tmpl = src["search"]
        url = (tmpl.replace("{tag}", quote_plus(q.replace(" ", "")))
               if "{tag}" in tmpl else tmpl.replace("{q}", quote_plus(q)))
        out.append({"source": src["name"], "key": src["key"],
                    "policy": src["policy"], "query": q, "url": url,
                    "fetchable": src["policy"] in (OPEN, API_REQUIRED)})
    return out


def all_search_urls(queries: list[str] | None = None) -> list[dict]:
    out = []
    for s in SOURCES:
        out.extend(search_urls(s["key"], queries))
    return out


def coverage_note() -> str:
    """The honest summary, shown on the Discovery page.

    Stated up front rather than buried, because a user who believes the
    system is crawling everything will stop doing the manual work and the
    database will quietly stop growing — the worst possible failure mode for
    a tool whose entire value is accumulated history.
    """
    manual = len(manual_sources())
    return (
        f"In practice, autonomous collection covers almost nothing here, and it "
        f"is worth being blunt about that. {manual} of {len(SOURCES)} sources — "
        f"every major property portal, Facebook, Instagram and search engines — "
        f"prohibit automated collection in their terms of use, require a login, "
        f"or both. This system does not scrape them, hold credentials, or work "
        f"around access controls. Of the two remaining, YouTube needs your own "
        f"API key, and Reddit's robots.txt currently disallows generic crawlers, "
        f"so the gate refuses those fetches too.\n\n"
        f"For those, it generates the full keyword × geography search matrix as "
        f"links for you to open, and gives you a paste box for anything worth "
        f"keeping. That intake is not a workaround — around Mysuru the best "
        f"listings reach you through brokers, WhatsApp and village contacts "
        f"anyway, and no crawler was ever going to see them. Everything this "
        f"system is actually for — deduplication across sources, independent "
        f"distance estimation, evidence-weighted scoring, and price history "
        f"tracked over months — works the same whether the text arrived by "
        f"crawler or by paste."
    )
