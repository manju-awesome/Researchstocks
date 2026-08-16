"""
dedup.py
========
Deciding whether two sightings are the same parcel.

This is the module that turns a scraper into a research system. The same 2.4
acres near Hunsur Road appears as a MagicBricks listing, a broker's own site,
a YouTube walkthrough, three Facebook group posts and a Reddit question — and
if each becomes its own record, the database says there are eight properties
near Hunsur Road, the comparables engine treats seven of them as independent
evidence of the price, and the one genuinely useful signal (this parcel has
been on the market for eleven months and the price has come down twice) is
invisible.

Matching without a unique identifier
------------------------------------
Indian land listings carry no parcel ID. Survey number is the closest thing
and is usually withheld until you call. So matching is done on a weighted
combination of the identifiers that do appear, with two tiers:

  **Strong keys** — a match on one of these alone is enough. A published
  phone number plus a village, or a survey number plus a village, is not a
  coincidence.

  **Weak keys** — village, acreage, price, description similarity. Several
  must agree, and crucially, *acreage is checked with a tolerance* because
  the same parcel is advertised as "2.5 acres", "2 acre 20 gunta" and "2.4
  acres" by three different people rounding differently.

The scoring is deliberately conservative on the merge side. A false merge is
much worse than a false split: it fuses two parcels' claims into one
incoherent record, and the resulting property has one parcel's water and the
other's price. A false split is visible (two near-identical rows next to each
other in the dashboard) and reversible by hand. So the threshold is set high
and near-misses are surfaced as "possible duplicate" for a human to confirm
rather than merged automatically.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from findfarms.core.claims import ClaimSet
from findfarms.core.geo import haversine_km, normalise_place

# A pair scoring at or above MERGE is treated as the same parcel. Between
# SUGGEST and MERGE it is flagged for human confirmation and left separate.
MERGE_THRESHOLD = 0.80
SUGGEST_THRESHOLD = 0.55

# Acreage agreement tolerance. 8% covers the rounding people actually do
# (2.5 vs 2.4 vs "2 acre 20 gunta") without letting 2 acres match 3.
ACRE_TOLERANCE = 0.08

# Price agreement tolerance. Wider than acreage: the same parcel is quoted
# at different prices by different brokers on the same day, and the price
# genuinely moves over the months a parcel sits on the market.
PRICE_TOLERANCE = 0.15

# Two coordinate sets this close are the same parcel for our purposes. Land
# parcels of 1-5 acres are roughly 60-140 m across.
COORD_SAME_KM = 0.25


def _s(cs: ClaimSet, key):
    v = cs.value(key)
    return None if v is None else str(v).strip().lower()


def _n(cs: ClaimSet, key):
    v = cs.value(key)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def normalise_phone(phone) -> str | None:
    """Last 10 digits of an Indian mobile number.

    Strips +91, 0 prefixes, spaces and hyphens so the same number written
    five ways collapses to one key. This is the strongest identifier
    available in this domain — brokers list many parcels, but a given phone
    number plus a given village plus a similar acreage is one parcel.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) < 10:
        return None
    last10 = digits[-10:]
    return last10 if last10[0] in "6789" else None


def _text_similarity(a, b) -> float:
    """Similarity of two listing descriptions, on their content words.

    Listing text gets copied between portals with light edits, so a high
    ratio is meaningful. Stopwords and the boilerplate every listing shares
    ("agricultural land for sale", "contact for more details") are stripped
    first, otherwise every pair scores 0.6 on boilerplate alone.
    """
    if not a or not b:
        return 0.0
    boiler = ("agricultural", "agriculture", "land", "sale", "for", "property",
              "contact", "details", "more", "call", "price", "acre", "acres",
              "please", "interested", "buyers", "genuine", "near", "mysore",
              "mysuru", "the", "and", "with", "is", "in", "at", "of", "a", "to")
    def toks(s):
        words = re.findall(r"[a-z]{3,}", str(s).lower())
        return [w for w in words if w not in boiler]
    ta, tb = toks(a), toks(b)
    if len(ta) < 4 or len(tb) < 4:
        return 0.0
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


def match_score(a: ClaimSet, b: ClaimSet) -> tuple[float, list[str]]:
    """How likely two sightings are the same parcel, with the reasons.

    Returns (score 0-1, reasons). The reasons list is not decoration — when
    the dashboard asks a human to confirm a possible duplicate, "same phone
    number, same village, acreage within 4%" is what makes that a two-second
    decision instead of a re-read of both listings.
    """
    reasons: list[str] = []

    # -- disqualifiers ----------------------------------------------------
    # Checked before anything else: these say "definitely not the same"
    # regardless of how much else agrees, and letting a strong phone match
    # override a 3-acre size gap is how a broker's two parcels get fused.
    acre_a, acre_b = _n(a, "acres"), _n(b, "acres")
    acres_agree = None
    if acre_a and acre_b:
        diff = abs(acre_a - acre_b) / max(acre_a, acre_b)
        acres_agree = diff <= ACRE_TOLERANCE
        if not acres_agree and diff > 0.35:
            return 0.0, [f"Different size: {acre_a} ac vs {acre_b} ac"]

    lat_a, lon_a = _n(a, "latitude"), _n(a, "longitude")
    lat_b, lon_b = _n(b, "latitude"), _n(b, "longitude")
    coord_km = None
    if None not in (lat_a, lon_a, lat_b, lon_b):
        coord_km = haversine_km(lat_a, lon_a, lat_b, lon_b)
        if coord_km is not None and coord_km > 3.0:
            return 0.0, [f"Coordinates {coord_km:.1f} km apart"]

    village_a = normalise_place(_s(a, "village"))
    village_b = normalise_place(_s(b, "village"))
    villages_agree = bool(village_a and village_b and village_a == village_b)
    if village_a and village_b and not villages_agree:
        # Different named villages is strong evidence against, but not
        # conclusive — a parcel on a boundary gets described by either
        # neighbouring village. Not a hard disqualifier, a heavy penalty.
        reasons.append(f"Different villages named ({village_a} vs {village_b})")

    # -- strong keys ------------------------------------------------------
    score = 0.0

    phone_a = normalise_phone(a.value("phone"))
    phone_b = normalise_phone(b.value("phone"))
    if phone_a and phone_b and phone_a == phone_b:
        # Same contact is strong, but a broker lists many parcels — so it
        # only reaches the merge threshold with size or place agreeing too.
        score += 0.55
        reasons.append(f"Same published phone (...{phone_a[-4:]})")

    sy_a, sy_b = _s(a, "survey_number"), _s(b, "survey_number")
    if sy_a and sy_b and sy_a == sy_b and villages_agree:
        score += 0.85
        reasons.append(f"Same survey number ({sy_a}) in the same village")

    url_a, url_b = _s(a, "source_url"), _s(b, "source_url")
    if url_a and url_b and url_a == url_b:
        score += 0.95
        reasons.append("Identical source URL")

    if coord_km is not None and coord_km <= COORD_SAME_KM:
        score += 0.50
        reasons.append(f"Coordinates {coord_km * 1000:.0f} m apart")

    # -- weak keys --------------------------------------------------------
    if villages_agree:
        score += 0.15
        reasons.append(f"Same village ({village_a})")
    elif village_a and village_b:
        score -= 0.25

    if acres_agree:
        score += 0.20
        reasons.append(f"Same size (~{acre_a} ac)")
    elif acres_agree is False:
        score -= 0.15

    ppa_a, ppa_b = _n(a, "price_per_acre"), _n(b, "price_per_acre")
    if ppa_a and ppa_b:
        diff = abs(ppa_a - ppa_b) / max(ppa_a, ppa_b)
        if diff <= PRICE_TOLERANCE:
            score += 0.12
            reasons.append("Similar asking price")
        elif diff > 0.5:
            score -= 0.10

    sim = _text_similarity(a.value("raw_text"), b.value("raw_text"))
    if sim >= 0.75:
        score += 0.35
        reasons.append(f"Near-identical description ({sim:.0%} match)")
    elif sim >= 0.55:
        score += 0.18
        reasons.append(f"Similar description ({sim:.0%} match)")

    # Distinctive combinations that rarely coincide.
    depth_a, depth_b = _n(a, "borewell_depth_ft"), _n(b, "borewell_depth_ft")
    if depth_a and depth_b and abs(depth_a - depth_b) <= 25 and villages_agree:
        score += 0.15
        reasons.append(f"Same borewell depth (~{depth_a:.0f} ft) in the same village")

    trees_a, trees_b = _n(a, "tree_count"), _n(b, "tree_count")
    if trees_a and trees_b and abs(trees_a - trees_b) / max(trees_a, trees_b) < 0.1:
        score += 0.12
        reasons.append("Same tree count")

    return max(0.0, min(1.0, score)), reasons


def canonical_id(cs: ClaimSet) -> str:
    """Stable ID for a parcel, derived from its most durable attributes.

    Built from village + rounded acreage + the last four digits of the phone,
    because those are what stay the same when a parcel is relisted with a new
    price and rewritten copy six months later. Price is deliberately excluded
    — a price drop must not create a new property, since tracking price drops
    is the entire point.

    This is a first-guess key only. Real identity is decided by `match_score`
    against existing records; this exists so a re-scrape of the same listing
    lands on the same record without a full scan.
    """
    village = normalise_place(cs.value("village")) or "unknown"
    acres = _n(cs, "acres")
    acre_key = f"{round(acres, 1)}" if acres else "na"
    phone = normalise_phone(cs.value("phone"))
    phone_key = phone[-4:] if phone else "na"
    sy = (str(cs.value("survey_number") or "na")).lower().strip()

    basis = f"{village}|{acre_key}|{phone_key}|{sy}"
    if basis == "unknown|na|na|na":
        # Nothing durable to key on. Fall back to a content hash so the record
        # is at least stable across re-imports of the same text, and let
        # match_score sort out identity from there.
        basis = "text|" + hashlib.sha1(
            str(cs.value("raw_text") or "")[:2000].encode("utf-8")).hexdigest()[:12]
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"{village[:12].replace(' ', '-')}-{acre_key}-{digest}"


def find_duplicates(new: ClaimSet, existing: list[tuple[str, ClaimSet]]):
    """Compare a new sighting against everything on file.

    Returns (merge_target_id, suggestions). `merge_target_id` is the single
    best match at or above MERGE_THRESHOLD, or None. `suggestions` are the
    near-misses, which surface in the UI as "is this the same parcel?" rather
    than being merged silently.
    """
    scored = []
    for pid, other in existing:
        s, reasons = match_score(new, other)
        if s >= SUGGEST_THRESHOLD:
            scored.append((s, pid, reasons))
    scored.sort(reverse=True, key=lambda t: t[0])
    if scored and scored[0][0] >= MERGE_THRESHOLD:
        return scored[0][1], [(s, pid, r) for s, pid, r in scored[1:]]
    return None, scored
