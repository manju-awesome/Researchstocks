"""
watershed.py
============
River proximity, rainfall, land undulation, and what they add up to:
**HARVEST_SCORE / 100** — how much water this parcel could capture and store
if you built for it.

Why this is a separate score from WATER_SCORE
---------------------------------------------
`water.py` answers "what water does this parcel have?". This module answers a
different and complementary question: "what water could it have?" Those must
not be blended, because one is an observation and the other is a plan. A
parcel with a strong borewell has water today. A parcel with a weak borewell,
900 mm of rain and a natural fall across it has water available for the cost
of a pond and some bunding — which is a real and much cheaper thing than
buying a different parcel, but it is not the same as having water.

So harvesting potential contributes only a small, explicitly labelled amount
to the water score (see `HARVEST_WATER_BONUS`), and gets its own full analysis
on the property page. It is decision-relevant mainly as a tie-breaker and as a
rescue path: of two parcels with equally mediocre borewells, the one that can
be made wet is worth considerably more than the one that cannot.

The three inputs
----------------
**River distance.** Computed from a coarse polyline of each river's course,
not from the seller's claim. This is deliberately *not* treated as irrigation
— the rule from `water.py` stands and is restated here, because "200 m from
the Kaveri" is one of the most misleading things a listing can say. What
river proximity genuinely buys is a better shallow water table in the alluvial
belt, which helps a borewell and helps recharge. What it can also bring is a
buffer-zone building restriction and flood exposure, so being very close is
scored as a mixed signal, not a good one.

**Rainfall.** Taluk-level annual averages. The gradient across this district
is large — roughly 700 mm at Nanjangud and T. Narasipura against 1000+ mm at
H.D. Kote and Periyapatna — and it runs in tension with the distance
preference, since the wetter taluks are the further ones. Worth seeing
explicitly rather than discovering after buying.

**Undulation.** The counter-intuitive one, and the reason "up and down in
land" deserves its own treatment. `agriculture.py` scores flat land highest,
which is correct for cultivation. For water harvesting it is close to the
opposite: a **gentle fall across the parcel is the ideal case**, because
runoff concentrates at a natural low point where a farm pond can be sited and
gravity does the distribution work for free. Dead-flat land needs the pond
excavated with no natural catchment; steep land moves water too fast to catch
and takes topsoil with it.

So a parcel described as "undulating" is being marked down by the agriculture
score and marked up by this one, and that disagreement is the correct
behaviour rather than an inconsistency to reconcile.

The arithmetic
--------------
    gross rainfall (m³) = area (m²) × rainfall (m)
    runoff (m³)         = gross × runoff coefficient
    harvestable (m³)    = runoff × capture efficiency

Runoff coefficients follow standard agricultural-catchment values, adjusted
for slope and soil. All three figures are reported, because they answer
different questions: gross is what falls, runoff is what leaves, harvestable
is what a well-sited pond actually holds onto across a year of refills.

Every number here is an estimate from approximate inputs. It is meant to
support a conversation with a borewell contractor or a watershed engineer,
not to replace one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from findfarms.core.claims import ClaimSet, Claim, INFERRED
from findfarms.core.geo import DATA_DIR, normalise_place

HYDROLOGY_PATH = DATA_DIR / "reference" / "hydrology.json"

SQM_PER_ACRE = 4046.86

# Contribution harvesting potential may make to WATER_SCORE. Small on
# purpose: it is buildable water, not present water, and letting it run
# higher would rank a dry parcel with a good slope above a wet one.
HARVEST_WATER_BONUS = 8

# Distance bands from a major river, in km.
#
# RIVER_PRECISION_KM is the honest resolution limit, not a band: the river
# course is a 7-9 point polyline and the parcel is usually positioned from a
# village centroid, so anything computing below this is "too close to call"
# rather than a measurement. It is set at the top of the ladder deliberately —
# this is the band where buffer-zone and flood restrictions live, so it is the
# band where pretending to precision is most expensive.
RIVER_PRECISION_KM = 2.0
RIVER_CLOSE_KM = 4.0         # strong water-table benefit
RIVER_NEAR_KM = 8.0          # meaningful benefit
RIVER_INFLUENCE_KM = 12.0    # marginal

# Runoff coefficients for agricultural catchments, by slope class. Higher
# means more water runs off (better to harvest, worse for erosion and for
# in-situ infiltration) — which is why the score below does not simply
# reward the highest number.
RUNOFF_BY_SLOPE = {
    "flat":         0.15,
    "gentle_slope": 0.28,
    "undulating":   0.35,
    "sloping":      0.45,
    "steep":        0.55,
    "unknown":      0.25,
}

# Soil adjustment to the runoff coefficient. Sandy soil infiltrates and
# yields little runoff; black cotton and rocky ground shed water.
RUNOFF_SOIL_ADJ = {
    "sandy": -0.08, "loam": -0.03, "red soil": 0.0,
    "black soil": +0.07, "rocky": +0.12,
}

# What fraction of annual runoff a well-sited farm pond actually retains,
# allowing for storms that overtop it, evaporation and seepage, and rain that
# arrives when it is already full. Conservative on purpose.
CAPTURE_EFFICIENCY = 0.60

LABELS = ((80, "Excellent"), (65, "Strong"), (50, "Workable"),
          (35, "Limited"), (0, "Poor"))

_hydro_cache: dict | None = None


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


def load_hydrology(force: bool = False) -> dict:
    global _hydro_cache
    if _hydro_cache is not None and not force:
        return _hydro_cache
    try:
        _hydro_cache = json.loads(HYDROLOGY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _hydro_cache = {"rivers": {}, "rainfall_mm_by_taluk": {},
                        "rainfall_default_mm": 780}
    return _hydro_cache


# ------------------------------------------------------- river distance ----

def _to_local_km(lat, lon, lat0):
    """Equirectangular projection to local km. Adequate at this scale — the
    error over a 50 km district is well under the ±2 km the coarse river
    polyline already carries, so a geodesic solve would be false precision."""
    return (math.radians(lon) * 6371.0 * math.cos(math.radians(lat0)),
            math.radians(lat) * 6371.0)


def _point_segment_km(px, py, ax, ay, bx, by) -> float:
    """Shortest distance from a point to a line segment, in km."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def river_distances(lat, lon) -> dict:
    """Perpendicular distance to each river's course, in km.

    Computed against the polyline rather than against a town on the river,
    which is the distinction that matters: Nanjangud sits on the Kabini, so
    "distance to Nanjangud" and "distance to the Kabini" are different
    numbers for a parcel 8 km north of the town.
    """
    out = {"kaveri_km": None, "kabini_km": None,
           "nearest": None, "nearest_km": None, "resolved": False}
    lat, lon = _num(lat), _num(lon)
    if lat is None or lon is None:
        return out

    hydro = load_hydrology()
    px, py = _to_local_km(lat, lon, lat)

    for name, river in (hydro.get("rivers") or {}).items():
        pts = river.get("waypoints") or []
        if len(pts) < 2:
            continue
        best = None
        for i in range(len(pts) - 1):
            ax, ay = _to_local_km(pts[i][0], pts[i][1], lat)
            bx, by = _to_local_km(pts[i + 1][0], pts[i + 1][1], lat)
            d = _point_segment_km(px, py, ax, ay, bx, by)
            best = d if best is None else min(best, d)
        if best is not None:
            out[f"{name.lower()}_km"] = round(best, 1)
            out["resolved"] = True

    candidates = [(out.get("kaveri_km"), "Kaveri"), (out.get("kabini_km"), "Kabini")]
    candidates = [(d, n) for d, n in candidates if d is not None]
    if candidates:
        d, n = min(candidates)
        out["nearest"], out["nearest_km"] = n, d
    return out


def river_assessment(dist: dict) -> tuple[float, list[str], list[str], list[str]]:
    """Score river proximity for GROUNDWATER context — never for irrigation.

    Returns (points out of 20, drivers, warnings, questions). The irrigation
    warning is restated at every band because the misconception is that
    durable: proximity to a river is not a right to take water from it, and a
    parcel can be 200 m from the Kaveri with no legal access to a drop.
    """
    drivers, warnings, questions = [], [], []
    km = dist.get("nearest_km")
    name = dist.get("nearest")

    if km is None:
        questions.append("How far is the parcel from the Kaveri or the Kabini? "
                         "Could not be computed — the location did not resolve.")
        return 0.0, drivers, warnings, questions

    if km <= RIVER_PRECISION_KM:
        # Below the resolution of a coarse polyline positioned from a village
        # centroid. Reporting "0.0 km from the Kaveri" here would be false
        # precision that reads as certainty — and it is the one band where a
        # wrong answer is expensive, because it is the band where buffer-zone
        # and flood restrictions live.
        points = 12.0
        drivers.append(f"Within about {RIVER_PRECISION_KM:.0f} km of the {name} — "
                       f"the shallow water table in this belt is usually excellent")
        warnings.append(
            f"The parcel computes as within ~{RIVER_PRECISION_KM:.0f} km of the "
            f"{name}, which is below what this data can resolve — the river course "
            f"here is a coarse polyline and the parcel is positioned from a village "
            f"centroid, so the true distance could be anywhere from riverfront to a "
            f"few km out. That matters more in this band than any other: land this "
            f"close can sit inside a notified river buffer, which restricts "
            f"construction and sometimes transfer, and it floods. Treat it as "
            f"unresolved and check it properly.")
        questions.append(
            f"Establish the real distance to the {name} and whether any part of the "
            f"parcel falls inside its notified buffer. This needs the village map "
            f"and a licensed surveyor — ask the village accountant and two "
            f"neighbours about the highest flood level on record, not the seller.")
    elif km <= RIVER_CLOSE_KM:
        points = 20.0
        drivers.append(f"~{km:.1f} km from the {name} — close enough for a strong "
                       f"shallow water table, far enough to be clear of the buffer "
                       f"and the flood plain. This is the best band to be in.")
    elif km <= RIVER_NEAR_KM:
        points = 14.0
        drivers.append(f"~{km:.1f} km from the {name} — meaningful benefit to the "
                       f"local water table")
    elif km <= RIVER_INFLUENCE_KM:
        points = 7.0
        drivers.append(f"~{km:.1f} km from the {name} — some regional influence on "
                       f"groundwater")
    else:
        points = 0.0
        warnings.append(
            f"Nearest major river ({name}) is ~{km:.0f} km away. No river "
            f"contribution to the water table here; groundwater depends entirely "
            f"on local recharge, which makes harvesting and the neighbours' "
            f"borewell history matter more, not less.")

    if km <= RIVER_INFLUENCE_KM:
        warnings.append(
            f"River proximity is NOT an irrigation right. Being {km:.1f} km from "
            f"the {name} gives this parcel no entitlement to lift a drop from it. "
            f"It is scored here only as groundwater context.")
        questions.append(
            "Is there any registered lift-irrigation permission from the river "
            "attached to this land? If the seller says there is, ask to see it.")
    return points, drivers, warnings, questions


# ------------------------------------------------------------- rainfall ----

def rainfall_for(taluk, village=None) -> tuple[float, str, str]:
    """Annual rainfall for a taluk. Returns (mm, source_label, note)."""
    hydro = load_hydrology()
    table = hydro.get("rainfall_mm_by_taluk") or {}
    default = float(hydro.get("rainfall_default_mm", 780))
    if taluk:
        key = normalise_place(taluk)
        for name, mm in table.items():
            if normalise_place(name) == key:
                return float(mm), f"{name} taluk average", ""
    return default, "district default", (
        f"Taluk not matched to the rainfall table, so the district default of "
        f"{default:.0f} mm was used. Check the actual figure for this hobli.")


def rainfall_assessment(mm: float) -> tuple[float, list[str], list[str]]:
    """Score annual rainfall out of 25, with the seasonality caveat."""
    drivers, warnings = [], []
    if mm >= 1000:
        points, band = 25.0, "high for this district"
    elif mm >= 850:
        points, band = 21.0, "above the district average"
    elif mm >= 750:
        points, band = 16.0, "around the district average"
    elif mm >= 650:
        points, band = 11.0, "below the district average"
    else:
        points, band = 6.0, "low"
    drivers.append(f"~{mm:.0f} mm annual rainfall — {band}")

    if mm < 750:
        warnings.append(
            f"At ~{mm:.0f} mm this is one of the drier corridors in the district. "
            f"Harvesting still works, but the pond will need to be sized for the "
            f"rain that actually arrives, and the dry-season gap is longer.")

    warnings.append(
        "Annual rainfall is a weak guide on its own: roughly 55-60% arrives in "
        "the June-September monsoon and most of the rest in October-November, "
        "leaving a five-month dry spell. What decides whether this parcel carries "
        "itself through April is storage, not the annual total.")
    return points, drivers, warnings


# ---------------------------------------------------------- undulation ----

def slope_class(cs: ClaimSet) -> tuple[str, str]:
    """Read the parcel's slope/undulation. Returns (class, evidence).

    Deliberately distinct from `agriculture.py`'s reading of the same claim.
    That module wants to know how easy the land is to cultivate; this one
    wants to know whether water concentrates anywhere. The same word —
    "undulating" — is a mild negative there and a positive here.
    """
    explicit = cs.get("undulation")
    if explicit.known:
        return str(explicit.value), explicit.describe()

    terrain = cs.get("terrain")
    if terrain.known:
        t = str(terrain.value).lower()
        if "gentle" in t:
            return "gentle_slope", terrain.describe()
        if "flat" in t or "plain" in t or "level" in t:
            return "flat", terrain.describe()
        if "undulat" in t:
            return "undulating", terrain.describe()
        if "steep" in t or "hill" in t:
            return "steep", terrain.describe()
        if "slop" in t or "gradient" in t:
            return "sloping", terrain.describe()
    return "unknown", ""


def undulation_assessment(slope: str, evidence: str) -> tuple[float, list[str],
                                                              list[str], list[str]]:
    """Score the land's fall for harvesting, out of 25.

    The ranking that matters, and the one that surprises people: **a gentle
    slope beats dead-flat land.** Runoff concentrates at a natural low point,
    so a pond sites itself and gravity distributes the stored water without a
    pump. Flat land harvests perfectly well but every cubic metre of the pond
    has to be dug on purpose and the water pumped back out.
    """
    drivers, warnings, questions = [], [], []
    ev = f" ({evidence})" if evidence else ""

    if slope == "gentle_slope":
        points = 25.0
        drivers.append(
            f"Gentle fall across the land{ev} — the ideal case for harvesting. "
            f"Runoff concentrates at a natural low point, so a farm pond sites "
            f"itself and gravity does the distribution without a pump.")
    elif slope == "undulating":
        points = 22.0
        drivers.append(
            f"Undulating ground{ev} — good for harvesting. The dips are natural "
            f"collection points and contour bunds work well across the fall. "
            f"Note this is the same feature the agriculture score marks down: "
            f"harder to plough, better at catching water.")
    elif slope == "flat":
        points = 15.0
        drivers.append(f"Flat land{ev} — harvests well by infiltration.")
        warnings.append(
            "Flat land has no natural low point, so a farm pond must be fully "
            "excavated and the stored water pumped back out rather than flowing. "
            "Workable, and more expensive to build and to run than a parcel with "
            "a gentle fall.")
    elif slope == "sloping":
        points = 13.0
        drivers.append(f"Sloping ground{ev} — plenty of runoff to catch.")
        warnings.append(
            "On a pronounced slope water moves fast and takes topsoil with it. "
            "Harvesting here means bunding and check dams before ponding, which "
            "is a larger earthworks job.")
    elif slope == "steep":
        points = 6.0
        warnings.append(
            "Steep ground sheds water too quickly to catch cheaply and erodes. "
            "Terracing would be needed, which is a serious cost.")
    else:
        points = 10.0
        questions.append(
            "Does the land fall in any direction, and by roughly how much across "
            "its length? Walk it and find the lowest point — that is where a farm "
            "pond goes, and whether one exists decides most of the harvesting "
            "potential.")

    questions.append(
        "Where does water actually leave this parcel in a heavy monsoon, and is "
        "there an existing low point, gully or natural depression? Visit after "
        "rain if you possibly can — an hour on the land in July tells you more "
        "than any survey.")
    return points, drivers, warnings, questions


# ------------------------------------------------------------ the score ----

def runoff_coefficient(slope: str, soil) -> float:
    base = RUNOFF_BY_SLOPE.get(slope, RUNOFF_BY_SLOPE["unknown"])
    if soil:
        base += RUNOFF_SOIL_ADJ.get(str(soil).strip().lower(), 0.0)
    return max(0.05, min(0.70, base))


def harvest_volumes(acres, rainfall_mm, coefficient) -> dict:
    """Gross rainfall, runoff and realistically harvestable volume, in m³.

    Reported as three separate numbers because they answer different
    questions, and because quoting only the gross figure — which is what
    rainwater-harvesting marketing tends to do — overstates what a pond
    actually holds by roughly four times.
    """
    a = _num(acres)
    if a is None or a <= 0 or not rainfall_mm:
        return {"gross_m3": None, "runoff_m3": None, "harvestable_m3": None,
                "harvestable_litres": None, "suggested_pond_m3": None}
    area_m2 = a * SQM_PER_ACRE
    gross = area_m2 * (rainfall_mm / 1000.0)
    runoff = gross * coefficient
    harvestable = runoff * CAPTURE_EFFICIENCY
    # A pond does not need to hold the year's runoff — it refills several
    # times through the monsoon. Sizing at about a third of annual runoff is
    # the usual working rule for a farm pond in this rainfall regime.
    pond = runoff * 0.33
    return {"gross_m3": round(gross), "runoff_m3": round(runoff),
            "harvestable_m3": round(harvestable),
            "harvestable_litres": round(harvestable * 1000),
            "suggested_pond_m3": round(pond)}


def score_watershed(cs: ClaimSet, resolved: dict | None = None) -> dict:
    """Full watershed assessment: rivers, rainfall, undulation, HARVEST_SCORE.

    Weighted: rainfall 25, undulation 25, river proximity 20, existing
    harvesting infrastructure 15, soil and infiltration 15.
    """
    resolved = resolved or {}
    drivers, warnings, questions = [], [], []
    points = 0.0

    # -- rivers (20) --------------------------------------------------------
    dist = river_distances(resolved.get("lat"), resolved.get("lon"))
    rp, rd, rw, rq = river_assessment(dist)
    points += rp
    drivers += rd
    warnings += rw
    questions += rq

    # -- rainfall (25) ------------------------------------------------------
    taluk = cs.value("taluk") or resolved.get("taluk")
    mm, rain_source, rain_note = rainfall_for(taluk, cs.value("village"))
    pp, pd, pw = rainfall_assessment(mm)
    points += pp
    drivers += pd
    warnings += pw
    if rain_note:
        warnings.append(rain_note)

    # -- undulation (25) ----------------------------------------------------
    slope, slope_ev = slope_class(cs)
    up, ud, uw, uq = undulation_assessment(slope, slope_ev)
    points += up
    drivers += ud
    warnings += uw
    questions += uq

    # -- existing infrastructure (15) ---------------------------------------
    infra = 0.0
    for key, label, pts in (("farm_pond", "farm pond", 8),
                            ("contour_bunds", "contour bunds", 4),
                            ("recharge_pit", "recharge pit / borewell recharge", 4),
                            ("check_dam", "check dam", 3),
                            ("water_storage", "water storage", 2)):
        c = cs.get(key)
        if c.truthy():
            infra += c.scaled(pts)
            drivers.append(f"Existing {label} ({c.badge()})")
    if infra == 0:
        questions.append(
            "Is there any existing farm pond, contour bunding, check dam or "
            "recharge pit? None is mentioned. Building them is normal and not "
            "expensive relative to the land, but it is a cost to plan for.")
    points += min(infra, 15.0)

    # -- soil and infiltration (15) -----------------------------------------
    soil = cs.value("soil")
    coefficient = runoff_coefficient(slope, soil)
    if soil:
        s = str(soil).lower()
        if "sandy" in s:
            points += 13
            drivers.append(f"{soil} — high infiltration, so harvested water "
                           f"recharges the aquifer well, though a pond will need "
                           f"lining to hold surface storage")
        elif "loam" in s or "red" in s:
            points += 15
            drivers.append(f"{soil} — a good balance of runoff to catch and "
                           f"infiltration to recharge with")
        elif "black" in s:
            points += 11
            drivers.append(f"{soil} — sheds water readily, so runoff is high and "
                           f"easy to collect; infiltration is slower")
        elif "rocky" in s:
            points += 7
            warnings.append("Rocky ground gives high runoff but poor recharge, and "
                            "excavating a pond in it costs considerably more.")
        else:
            points += 9
    else:
        points += 7
        questions.append("What is the soil type and depth? It decides both how "
                         "much runoff there is to catch and how well a pond holds.")

    score = int(round(max(0.0, min(100.0, points))))
    vols = harvest_volumes(cs.value("acres"), mm, coefficient)

    if vols["harvestable_m3"]:
        drivers.insert(0, (
            f"~{vols['harvestable_litres'] / 1_000_000:.1f} million litres a year "
            f"realistically harvestable ({vols['harvestable_m3']:,} m³) from "
            f"{mm:.0f} mm over {cs.value('acres')} acres"))

    return {
        "score": score,
        "label": _label(score),
        "rivers": dist,
        "rainfall_mm": mm,
        "rainfall_source": rain_source,
        "slope_class": slope,
        "slope_evidence": slope_ev,
        "runoff_coefficient": round(coefficient, 2),
        "volumes": vols,
        "drivers": drivers,
        "warnings": warnings,
        "questions": questions,
        "recommendations": recommendations(slope, vols, dist, mm, cs),
        "caveat": (
            "Every figure here is an estimate built on approximate inputs: a "
            "coarse river polyline (±2 km), a taluk-level rainfall average, and "
            "a slope read from the listing's own wording. Use it to frame a "
            "conversation with a watershed engineer or borewell contractor, not "
            "to replace one."),
    }


def recommendations(slope, vols, dist, mm, cs: ClaimSet) -> list[str]:
    """Concrete, parcel-specific harvesting actions."""
    out = []
    pond = vols.get("suggested_pond_m3")
    if pond:
        # A pond roughly 2 m deep with 1:1 side slopes — the usual farm-pond
        # geometry — needs about this footprint.
        side = math.sqrt(max(pond / 2.0, 1))
        out.append(
            f"Size a farm pond at roughly {pond:,} m³ — about {side:.0f} m × "
            f"{side:.0f} m at 2 m depth. It will refill several times through the "
            f"monsoon rather than filling once, which is why it can be well under "
            f"the annual runoff volume.")
    if slope in ("gentle_slope", "undulating"):
        out.append("Site the pond at the natural low point and let the fall feed "
                   "it. Contour bunds across the slope above it will slow runoff "
                   "and cut topsoil loss on the way down.")
    elif slope == "flat":
        out.append("With no natural fall, the pond must be excavated and sited "
                   "where you will actually need the water. Budget for pumping "
                   "back out — on sloping land gravity would do this free.")
    elif slope in ("sloping", "steep"):
        out.append("Bund and check-dam first to slow the water down, then pond. "
                   "Ponding a fast slope without slowing it silts the pond up "
                   "within a few seasons.")

    if cs.get("water_borewell").truthy() and not cs.get("recharge_pit").truthy():
        out.append("Connect a recharge pit to the existing borewell. This is one "
                   "of the cheapest interventions available and directly improves "
                   "the borewell's summer yield — which is the number that "
                   "actually matters here.")
    if mm and mm < 750:
        out.append(f"At ~{mm:.0f} mm, prioritise recharge over open storage: "
                   f"evaporation in this belt is high and an open pond loses a "
                   f"great deal through the dry months.")
    nearest_km = dist.get("nearest_km")
    if nearest_km is not None and nearest_km > RIVER_INFLUENCE_KM:
        out.append("With no river influence on the water table, harvesting and "
                   "recharge are the main levers you have over the groundwater "
                   "here. Treat them as part of the purchase cost, not an "
                   "improvement to do later.")
    out.append("Get a watershed engineer or the local Krishi Vigyan Kendra to "
               "walk the land before excavating anything. Karnataka has had "
               "subsidy schemes for farm ponds and recharge structures — worth "
               "checking what is currently available at the taluk office.")
    return out
