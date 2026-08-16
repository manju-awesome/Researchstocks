"""
agriculture.py
==============
AGRICULTURE_SCORE / 100 — can this land actually grow things, at the scale
and effort level a retired couple would want?

This score deliberately answers a narrower question than "is this good
farmland". Good farmland by a commercial standard is flat, large, irrigated
and near a mandi. What the brief is optimising for is different: land that
produces something worthwhile without demanding constant management, on 1-5
acres, for people who want a productive place to live rather than an
agricultural business.

That changes several weightings from the obvious ones:

  * **Water carries 30 of the 100 points** even though water has its own
    score. It is not double counting — it is that the agricultural value of
    unirrigated land in this belt is close to zero regardless of how good
    the soil is, and a score that let excellent soil compensate for no water
    would rank dry land above wet land with average soil. It must not.

  * **Established perennials are worth more than annual crops.** A 15-year
    coconut or mango stand yields with modest labour and survives a season
    of neglect. Two acres of sugarcane is a full-time job with a harvest
    contract attached. For this buyer the tree crop is strictly better, so
    it scores higher — the opposite of what a yield-per-acre model would say.

  * **Size is scored against the 1-5 acre target, not maximised.** Ten acres
    is penalised here, not rewarded. It is more land than two people can
    manage and it converts a retirement into an employment.

Everything read here is a seller claim unless a site visit or photo analysis
upgraded it, and the score is discounted by confidence throughout.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet

# Target band from the brief. Outside ACCEPT the parcel is flagged, not
# rejected — the flag travels to the deal score and the property page.
PREFERRED_MIN_ACRES = 1.0
PREFERRED_MAX_ACRES = 5.0
ACCEPT_MIN_ACRES = 0.5
ACCEPT_MAX_ACRES = 10.0

# Perennials that pay a retired owner: plant once, harvest for decades,
# survive a missed season. The value is the low management burden as much as
# the yield.
PERENNIAL_CROPS = ("coconut", "arecanut", "areca", "mango", "sapota", "chikoo",
                   "tamarind", "jackfruit", "guava", "pomegranate", "cashew",
                   "lemon", "teak", "silver oak", "sandalwood", "coffee",
                   "pepper", "banana")

# Annuals: real income, real labour, real exposure to one bad season.
ANNUAL_CROPS = ("sugarcane", "paddy", "ragi", "maize", "jowar", "cotton",
                "turmeric", "ginger", "vegetables", "flowers", "mulberry",
                "sunflower", "groundnut", "tur", "avare")

# Soil quality for mixed horticulture in this region.
SOIL_POINTS = {
    "red soil": 12,      # the regional default; good for coconut, areca, mango
    "loam": 14,
    "black soil": 11,    # holds moisture well, harder to work
    "sandy": 6,
    "rocky": 2,
}

LABELS = ((85, "Excellent"), (70, "Strong"), (55, "Workable"),
          (40, "Marginal"), (0, "Poor"))


def _label(score: int) -> str:
    for floor, name in LABELS:
        if score >= floor:
            return name
    return "Poor"


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def score_agriculture(cs: ClaimSet, water_score: int | None = None) -> dict:
    """Compute AGRICULTURE_SCORE.

    `water_score` is passed in rather than recomputed so the two scores can
    never disagree about the same parcel's water — one engine owns that
    judgement and this one consumes it.
    """
    points = 0.0
    drivers: list[str] = []
    warnings: list[str] = []
    questions: list[str] = []

    # -- water (30) ---------------------------------------------------------
    if water_score is None:
        questions.append("Water assessment unavailable — agriculture score is "
                         "incomplete without it.")
        warnings.append("Scored without a water assessment. Treat with caution: "
                        "water is 30% of this score and the largest single "
                        "determinant of what this land can grow.")
    else:
        water_points = (water_score / 100.0) * 30.0
        points += water_points
        drivers.append(f"Water security contributes {water_points:.0f}/30 "
                       f"(water score {water_score})")
        if water_score < 40:
            warnings.append("Weak water makes most of the agricultural upside "
                            "here theoretical. Soil and trees cannot compensate.")

    # -- current cultivation (20) -------------------------------------------
    cultivated = cs.get("under_cultivation")
    crops_claim = cs.get("crops")
    crops = [c.strip() for c in str(crops_claim.value or "").split(",") if c.strip()]

    perennials = [c for c in crops if any(p in c for p in PERENNIAL_CROPS)]
    annuals = [c for c in crops if any(a in c for a in ANNUAL_CROPS)]

    if cultivated.known and cultivated.truthy():
        points += cultivated.scaled(10)
        drivers.append(f"Reported under active cultivation ({cultivated.badge()})")
    elif cultivated.known and not cultivated.truthy():
        warnings.append("Described as barren, fallow or uncultivated. Land that "
                        "nobody is farming next to land that people are farming "
                        "usually has a reason — water, soil, access or title.")
        questions.append("Why is this land not being cultivated, and for how long "
                         "has it been idle?")
    else:
        questions.append("Is the land currently under cultivation, and with what?")

    if perennials:
        points += crops_claim.scaled(12)
        drivers.append(f"Established perennials: {', '.join(perennials)} "
                       f"({crops_claim.badge()}) — yield with modest labour and "
                       f"survive a neglected season")
        questions.append(f"How old are the {perennials[0]} trees, and what did "
                         f"they yield last year? An unproductive mature stand is "
                         f"a cost, not an asset.")
    if annuals:
        points += crops_claim.scaled(6)
        drivers.append(f"Annual crops: {', '.join(annuals)} ({crops_claim.badge()})")
        if annuals and not perennials:
            warnings.append(
                f"Only annual crops ({', '.join(annuals)}). These need someone "
                f"present through the season — sowing, irrigation, harvest and a "
                f"sale. Workable with a caretaker; a burden without one.")

    trees = _num(cs.get("tree_count").value)
    acres = _num(cs.get("acres").value)
    if trees:
        drivers.append(f"~{trees:.0f} trees claimed ({cs.get('tree_count').badge()})")
        if acres and acres > 0:
            per_acre = trees / acres
            # Coconut at roughly 70/acre, areca much denser. Well under 40/acre
            # over the whole parcel means the "plantation" is a corner of it.
            if per_acre < 40:
                questions.append(
                    f"~{per_acre:.0f} trees per acre suggests only part of the "
                    f"parcel is planted. How much of the {acres:.1f} acres is "
                    f"actually under the plantation?")

    # -- soil (14) ----------------------------------------------------------
    soil = cs.get("soil")
    if soil.known:
        base = SOIL_POINTS.get(str(soil.value).strip().lower(), 7)
        points += soil.scaled(base)
        drivers.append(f"Soil: {soil.value} ({soil.badge()})")
        if str(soil.value).strip().lower() == "rocky":
            warnings.append("Rocky or gravelly soil limits what can be planted and "
                            "makes borewell siting harder.")
    else:
        questions.append("What is the soil type and depth? Dig a pit on the site "
                         "visit — two feet of red loam over rock is a different "
                         "property from six feet of it.")

    # -- terrain and drainage (10) ------------------------------------------
    terrain = cs.get("terrain")
    if terrain.known:
        t = str(terrain.value).lower()
        if "flat" in t:
            points += terrain.scaled(10)
            drivers.append(f"Flat land ({terrain.badge()}) — easiest to irrigate "
                           f"and build on")
        elif "gentle" in t:
            points += terrain.scaled(8)
            drivers.append(f"Gentle slope ({terrain.badge()}) — drains well, still "
                           f"workable")
        else:
            points += terrain.scaled(4)
            warnings.append("Sloping or undulating land costs more to level, "
                            "irrigate and build on, and loses topsoil in heavy rain.")
    else:
        questions.append("What is the terrain and how does the parcel drain? Walk "
                         "it, ideally after rain.")

    if cs.get("flood_risk").truthy():
        points -= 8
        warnings.append("Flood or waterlogging risk noted. Check where the water "
                        "goes in a heavy monsoon before anything else.")
    else:
        questions.append("Does any part of the parcel waterlog or flood in the "
                         "monsoon? Ask neighbours, not the seller.")

    # -- infrastructure (8) -------------------------------------------------
    if cs.get("irrigation_system").truthy():
        c = cs.get("irrigation_system")
        points += c.scaled(6)
        drivers.append(f"Irrigation system in place: {c.value} ({c.badge()})")
    if cs.get("fencing").truthy():
        points += cs.get("fencing").scaled(4)
        drivers.append(f"Fenced ({cs.get('fencing').badge()}) — matters more than "
                       f"it sounds; unfenced land near a village means grazing")
    else:
        questions.append("Is the parcel fenced, and are the boundaries physically "
                         "marked? Unfenced land invites grazing and encroachment.")
    if cs.get("shed").truthy():
        points += cs.get("shed").scaled(3)
    if cs.get("organic").truthy():
        points += cs.get("organic").scaled(3)
        drivers.append(f"Described as organic / natural farming "
                       f"({cs.get('organic').badge()})")
        questions.append("If organic certification is claimed, ask for the "
                         "certificate and its validity — the word is used loosely.")

    # -- size fit (18) ------------------------------------------------------
    if acres is None:
        questions.append("Total extent is not stated. Get the acreage from the "
                         "RTC, not the advert.")
        warnings.append("Size unknown — the size-fit component could not be scored.")
    else:
        if PREFERRED_MIN_ACRES <= acres <= PREFERRED_MAX_ACRES:
            points += 18
            drivers.append(f"{acres:.2f} acres sits in the 1–5 acre target — enough "
                           f"to be productive, small enough for two people to manage")
        elif ACCEPT_MIN_ACRES <= acres < PREFERRED_MIN_ACRES:
            points += 11
            warnings.append(
                f"{acres:.2f} acres is below the 1-acre preference. Workable as a "
                f"home with a garden; too small for meaningful agricultural income, "
                f"and small parcels are often carved out of a larger holding — "
                f"check how the split was done and registered.")
        elif PREFERRED_MAX_ACRES < acres <= ACCEPT_MAX_ACRES:
            points += 9
            warnings.append(
                f"{acres:.2f} acres is above the 5-acre preference. This is more "
                f"land than two people can manage without hired help — it converts "
                f"a retirement into a job, and the extra acres are the ones you "
                f"stop visiting.")
        else:
            points += 2
            warnings.append(
                f"{acres:.2f} acres is outside the 0.5–10 acre range entirely. "
                f"Flagged rather than rejected, but this is an agricultural "
                f"business, not a retirement property.")

    score = int(round(max(0.0, min(100.0, points))))

    return {
        "score": score,
        "label": _label(score),
        "perennials": perennials,
        "annuals": annuals,
        "drivers": drivers,
        "warnings": warnings,
        "questions": questions,
    }
