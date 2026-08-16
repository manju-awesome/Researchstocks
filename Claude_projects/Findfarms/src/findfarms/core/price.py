"""
price.py
========
PRICE_POSITION = CHEAP / FAIR / EXPENSIVE / UNKNOWN, from comparables built
out of the system's own database.

The discipline here is refusing to answer. The brief says it plainly: do not
claim a market value unless sufficient comparable evidence exists. Two
listings in a village is not a market — it is two people's opinions, and if
both are optimistic, a third optimistic listing looks "fair" against them.
So below MIN_COMPARABLES the answer is UNKNOWN and the reason is stated.

Comparables are drawn in widening rings, and the ring is always reported
alongside the verdict, because "cheap for this village" and "cheap for
Mysuru district" are different claims and only the first is worth much:

    1. Same village                      strongest
    2. Same taluk, similar size and water
    3. Same corridor / distance band     weakest usable

Adjustments before comparison
-----------------------------
Raw ₹/acre across parcels is not comparable. A 2-acre parcel is worth more
per acre than a 10-acre one (small parcels carry a premium), irrigated land
is worth substantially more than dry, and road frontage carries a real
premium. So each comparable is normalised toward the subject property's
characteristics before the median is taken. The adjustments are crude and
declared — they move a comparable by a stated percentage for a stated reason,
and every one is shown on the property page.

Asking prices, not transactions
-------------------------------
Everything here is built from *asking* prices, because that is what public
listings contain. Asking prices in this market run above achieved prices, and
a whole database of them is internally consistent and collectively inflated.
Two consequences, both handled: the verdict compares like with like so the
bias largely cancels; and the guidance value — the government's published
minimum for stamp duty, which the buyer can look up per survey number — is
flagged as the one externally anchored number in the whole exercise, and is
recorded as a question rather than guessed at.
"""

from __future__ import annotations

import statistics

from findfarms.core.claims import ClaimSet
from findfarms.core.geo import normalise_place
from findfarms.core.units import format_price

# Below this, no verdict. Three is already thin; it is the floor at which
# saying anything is better than saying nothing, and the thinness is
# reported with the answer.
MIN_COMPARABLES = 3
CONFIDENT_COMPARABLES = 6

# Bands around the adjusted median.
CHEAP_BELOW = 0.85
EXPENSIVE_ABOVE = 1.15

# Size premium: smaller parcels cost more per acre. Roughly 4% per acre of
# difference, capped — the effect is real and non-linear, and beyond ±25%
# the adjustment is doing more harm than the comparison is worth.
SIZE_ADJ_PER_ACRE = 0.04
MAX_SIZE_ADJ = 0.25


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ppa(cs: ClaimSet):
    return _num(cs.value("price_per_acre")) or _num(cs.value("price_per_acre_stated"))


def _water_tier(cs: ClaimSet, water_score=None) -> int:
    """Coarse water bucket for comparability: 2 = irrigated, 1 = some, 0 = dry."""
    if water_score is not None:
        return 2 if water_score >= 65 else 1 if water_score >= 35 else 0
    if cs.get("water_canal").truthy() or cs.get("water_open_well").truthy():
        return 2
    if cs.get("water_borewell").truthy():
        return 1
    return 0


def _adjust(comp_ppa: float, comp: ClaimSet, subject: ClaimSet,
            comp_water: int, subj_water: int) -> tuple[float, list[str]]:
    """Normalise a comparable's ₹/acre toward the subject's characteristics."""
    adj = comp_ppa
    notes: list[str] = []

    c_acres, s_acres = _num(comp.value("acres")), _num(subject.value("acres"))
    if c_acres and s_acres and abs(c_acres - s_acres) >= 0.5:
        # Comparable is larger than subject ⇒ its ₹/acre understates what the
        # subject's smaller size would fetch ⇒ adjust the comparable up.
        delta = (c_acres - s_acres) * SIZE_ADJ_PER_ACRE
        delta = max(-MAX_SIZE_ADJ, min(MAX_SIZE_ADJ, delta))
        adj *= (1 + delta)
        notes.append(f"{delta:+.0%} for size ({c_acres:.1f} ac vs {s_acres:.1f} ac)")

    if comp_water != subj_water:
        # ~18% per tier. Irrigated versus dry is the largest single driver of
        # price difference in this market, larger than most people expect.
        delta = (subj_water - comp_water) * 0.18
        adj *= (1 + delta)
        tiers = {0: "dry", 1: "borewell", 2: "irrigated"}
        notes.append(f"{delta:+.0%} for water ({tiers[comp_water]} → "
                     f"{tiers[subj_water]})")

    c_road = comp.get("road_frontage").truthy()
    s_road = subject.get("road_frontage").truthy()
    if c_road != s_road:
        delta = 0.10 if s_road else -0.10
        adj *= (1 + delta)
        notes.append(f"{delta:+.0%} for road frontage")

    return adj, notes


def find_comparables(subject: ClaimSet, all_properties: dict,
                     subject_id: str | None = None,
                     subject_water: int | None = None) -> dict:
    """Gather and adjust comparables, widening the ring until enough are found."""
    s_village = normalise_place(subject.value("village"))
    s_taluk = normalise_place(subject.value("taluk"))
    s_acres = _num(subject.value("acres"))
    s_water = _water_tier(subject, subject_water)

    pool = []
    for pid, prop in (all_properties or {}).items():
        if pid == subject_id:
            continue
        cs = ClaimSet.from_dict(prop.get("claims", {}))
        ppa = _ppa(cs)
        if not ppa or ppa <= 0:
            continue
        # Rejected properties still inform the price picture — a parcel
        # rejected for title reasons is still evidence of what land in that
        # village is being asked for.
        pool.append((pid, cs, ppa, prop))

    def ring_same_village():
        return [p for p in pool
                if s_village and normalise_place(p[1].value("village")) == s_village]

    def ring_same_taluk():
        out = []
        for p in pool:
            if not s_taluk or normalise_place(p[1].value("taluk")) != s_taluk:
                continue
            a = _num(p[1].value("acres"))
            if s_acres and a and (a > s_acres * 3 or a < s_acres / 3):
                continue     # wildly different size is not a comparable
            out.append(p)
        return out

    def ring_all():
        return list(pool)

    for ring_name, ring_fn, quality in (
            ("same village", ring_same_village, "strong"),
            ("same taluk, similar size", ring_same_taluk, "moderate"),
            ("wider Mysuru area", ring_all, "weak")):
        found = ring_fn()
        if len(found) >= MIN_COMPARABLES:
            comps = []
            for pid, cs, ppa, prop in found:
                cw = _water_tier(cs, (prop.get("scores") or {}).get("water"))
                adj, notes = _adjust(ppa, cs, subject, cw, s_water)
                comps.append({
                    "property_id": pid,
                    "village": cs.value("village") or "—",
                    "acres": _num(cs.value("acres")),
                    "raw_ppa": ppa,
                    "adjusted_ppa": adj,
                    "adjustments": notes,
                    "source": cs.value("source") or "",
                })
            comps.sort(key=lambda c: c["adjusted_ppa"])
            return {"ring": ring_name, "quality": quality, "comparables": comps}

    # Not enough anywhere. Report the largest ring tried and what was in it,
    # so the page can say "2 comparables found, 3 needed" rather than going
    # silent — a thin market is itself information.
    found = ring_all()
    return {"ring": "wider Mysuru area", "quality": "insufficient",
            "comparables": [{"property_id": pid, "village": cs.value("village") or "—",
                             "acres": _num(cs.value("acres")), "raw_ppa": ppa,
                             "adjusted_ppa": ppa, "adjustments": [],
                             "source": cs.value("source") or ""}
                            for pid, cs, ppa, prop in found]}


def analyse_price(subject: ClaimSet, all_properties: dict,
                  subject_id: str | None = None,
                  subject_water: int | None = None) -> dict:
    """Full price analysis: position, band, comparables and the caveats."""
    asking_ppa = _ppa(subject)
    result = {
        "asking_price": _num(subject.value("asking_price")),
        "asking_price_per_acre": asking_ppa,
        "position": "UNKNOWN",
        "low": None, "median": None, "high": None,
        "ratio": None,
        "ring": None, "quality": None,
        "comparables": [],
        "rationale": "",
        "warnings": [],
        "questions": [
            "Look up the government guidance value for this survey number "
            "(Kaveri / sub-registrar). It is the one price reference in this "
            "whole exercise that is not somebody's asking price, and it sets "
            "the stamp duty floor regardless of what you agree to pay.",
            "Ask two local brokers, independently, what land in this village "
            "actually sold for in the last year — not what it was listed at. "
            "Asking and achieved prices diverge materially here.",
        ],
    }

    if not asking_ppa:
        result["rationale"] = ("No usable asking price per acre — either the price "
                               "or the extent is missing from the listing.")
        result["warnings"].append("Price not stated clearly enough to analyse.")
        return result

    warn = subject.get("price_warning")
    if warn.known:
        result["warnings"].append(str(warn.value))
    inconsistent = subject.get("price_inconsistency")
    if inconsistent.known:
        result["warnings"].append(str(inconsistent.value))

    found = find_comparables(subject, all_properties, subject_id, subject_water)
    result["ring"] = found["ring"]
    result["quality"] = found["quality"]
    result["comparables"] = found["comparables"]

    comps = found["comparables"]
    n = len(comps)
    if n < MIN_COMPARABLES:
        result["rationale"] = (
            f"Only {n} comparable{'' if n == 1 else 's'} in the database "
            f"({MIN_COMPARABLES} needed). No price verdict — {n} listings is not "
            f"a market, and calling this parcel cheap or expensive against them "
            f"would be guessing with extra steps. Add more listings from this "
            f"area and re-run.")
        result["warnings"].append(
            "Insufficient comparable evidence for any price judgement.")
        return result

    values = [c["adjusted_ppa"] for c in comps]
    low, median, high = min(values), statistics.median(values), max(values)
    result.update(low=low, median=median, high=high)
    ratio = asking_ppa / median if median else None
    result["ratio"] = ratio

    if ratio is None:
        result["position"] = "UNKNOWN"
    elif ratio < CHEAP_BELOW:
        result["position"] = "CHEAP"
    elif ratio > EXPENSIVE_ABOVE:
        result["position"] = "EXPENSIVE"
    else:
        result["position"] = "FAIR"

    conf = ("thin" if n < CONFIDENT_COMPARABLES else "reasonable")
    result["rationale"] = (
        f"{format_price(asking_ppa)}/acre against an adjusted median of "
        f"{format_price(median)}/acre from {n} comparables in the {found['ring']} "
        f"({format_key_range(low, high)}). That is {ratio:.0%} of median — "
        f"{result['position']}. Evidence base is {conf} and {found['quality']}, "
        f"and every comparable is an ASKING price, not a recorded sale.")

    if result["position"] == "CHEAP":
        result["warnings"].append(
            "Priced below comparable listings. In this market that is more often "
            "a title, water or access problem than a bargain — find out which "
            "before treating the discount as value. Genuinely motivated sellers "
            "exist, but so do parcels nobody can register.")
    if found["quality"] == "weak":
        result["warnings"].append(
            "Comparables come from the wider Mysuru area rather than this village. "
            "Land prices move sharply over a few kilometres here, so treat the "
            "verdict as a rough orientation only.")
    if n < CONFIDENT_COMPARABLES:
        result["warnings"].append(
            f"Only {n} comparables — enough for a verdict, not enough for "
            f"confidence in it.")

    return result


def format_key_range(low, high) -> str:
    return f"range {format_price(low)}–{format_price(high)}"
