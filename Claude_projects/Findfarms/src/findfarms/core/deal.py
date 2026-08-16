"""
deal.py
=======
DEAL_SCORE / 100, the A–E category, and the STATUS that can override both.

The weights are the brief's:

    Legal / document evidence   25%
    Water                       25%
    Agriculture                 15%
    Location / access           10%
    Price                       10%
    Retirement suitability      10%
    Future optionality           5%

Gates beat weights
------------------
A weighted average will always let a strong factor carry a fatal one — that
is what averaging does. So the score is computed, and then gates are applied
on top of it:

    HIGH legal risk        → STATUS = DO NOT PROCEED, score forced down, and
                             the property drops out of the ranked lists
                             entirely. An unwindable title is not a discount.
    UNKNOWN legal risk     → STATUS = DUE DILIGENCE REQUIRED, and the score is
                             capped. Almost everything sits here.
    Water below the floor  → capped, because a retirement property without
                             water is not a cheap retirement property.

The legal component itself is scored on *evidence*, not on the absence of
bad news. A listing with no title information scores low on that 25%, not
neutral — which is the mechanism that stops an information-free listing from
floating to the top on water and price alone. This is the most common way
these systems go wrong: the parcels with the least information look the
cleanest, because there is nothing to hold against them.

Optionality (5%) is where appreciation lives, and it is small on purpose. The
user's own framing is that livability and water come first and appreciation
third; a heavier weight would let a speculative parcel outrank a livable one,
which is the outcome this whole system exists to avoid.
"""

from __future__ import annotations

from findfarms.core import legal as legal_mod
from findfarms.core.claims import ClaimSet
from findfarms.core.geo import radius_status

WEIGHTS = {
    "legal": 25, "water": 25, "agriculture": 15,
    "location": 10, "price": 10, "retirement": 10, "optionality": 5,
}

# Statuses
PROCEED_CAUTION = "PROCEED WITH CAUTION"
DUE_DILIGENCE = "DUE DILIGENCE REQUIRED"
DO_NOT_PROCEED = "DO NOT PROCEED"

# Ceiling while legal risk is UNKNOWN. Set above the B threshold so a genuinely
# excellent unverified parcel can still reach B and demand attention — the cap
# exists to stop it reaching A, which is reserved for parcels where somebody
# has actually looked at documents.
UNKNOWN_LEGAL_CAP = 74

# Water floor. Below this the parcel cannot rank as a strong candidate no
# matter what else is true.
WATER_FLOOR = 35
WATER_FLOOR_CAP = 55

CATEGORIES = (
    (85, "A", "EXCEPTIONAL", "Strong candidate. Investigate immediately."),
    (72, "B", "STRONG", "Good candidate. Verify documents and visit."),
    (55, "C", "INVESTIGATE", "Possible opportunity, important information missing."),
    (38, "D", "WEAK", "Poor on economics, location, water or land quality."),
    (0,  "E", "REJECT", "Major red flags or clearly outside requirements."),
)


def _legal_points(legal_result: dict) -> tuple[float, str]:
    """Score the 25% legal component on evidence held, not on quiet.

    The ordering that matters: UNKNOWN (nothing checked) scores *below*
    MEDIUM (specific concerns found, documents partially seen). A property
    where a concern was identified and can be worked through is further along
    than one nobody has looked at — and scoring silence above a known,
    resolvable issue would reward listings for saying nothing.
    """
    level = legal_result.get("level")
    n_verified = len(legal_result.get("verified_documents", []))
    if level == legal_mod.HIGH:
        return 0.0, "Hard-stop category present — scores zero and gates the deal."
    if level == legal_mod.LOW:
        return 25.0, f"{n_verified} documents verified, no concerns outstanding."
    if level == legal_mod.MEDIUM:
        base = 8.0 + min(n_verified, 4) * 2.5
        return base, (f"Concerns identified{' and ' + str(n_verified) + ' documents verified' if n_verified else ''} "
                      f"— known problems, partially evidenced.")
    return 4.0, ("Nothing verified and nothing assessable. Scores near zero "
                 "because an unexamined title is not a clean one.")


def _location_points(cs: ClaimSet, driving_km) -> tuple[float, list[str]]:
    pts, notes = 0.0, []
    status, why = radius_status(driving_km)
    band = {"PREFERRED": 6.0, "INSIDE_CLOSE": 4.5, "OUTSIDE_NEAR": 2.5,
            "OUTSIDE": 0.5, "UNKNOWN": 0.0}.get(status, 0.0)
    pts += band
    notes.append(why)

    road = cs.get("road_surface")
    if road.known and str(road.value).lower() == "tarred":
        pts += road.scaled(2.5)
        notes.append("Tarred road access.")
    elif road.known:
        notes.append("Unpaved approach road.")
    if cs.get("road_frontage").truthy():
        pts += cs.get("road_frontage").scaled(1.5)
        notes.append("Direct road frontage.")
    return min(pts, 10.0), notes


def _price_points(price_result: dict) -> tuple[float, str]:
    """Price is worth 10%, and an unknown price position scores the middle.

    Deliberately different from the legal component. Not knowing whether a
    price is fair is a gap in our comparables, not a defect in the property —
    penalising the parcel for our thin database would rank a village we have
    covered above an identical one we have not.
    """
    pos = price_result.get("position")
    if pos == "CHEAP":
        return 9.0, "Below comparable listings — verify why before treating it as value."
    if pos == "FAIR":
        return 7.0, "In line with comparable listings."
    if pos == "EXPENSIVE":
        return 2.5, "Above comparable listings — there is negotiating work to do."
    return 5.0, ("Insufficient comparables for a verdict; scored neutral rather "
                 "than penalised, since that gap is in our data, not the parcel.")


def _optionality_points(cs: ClaimSet, driving_km) -> tuple[float, list[str]]:
    """Future optionality, 5%: what else could this land become?

    Kept small on purpose. It reads: can the parcel be split or partly sold;
    is it on a corridor that is developing; is the size flexible. It also
    carries a *negative* — land directly in a development path is optionality
    and acquisition risk at once, and for a retirement property the second
    matters more than the first.
    """
    pts, notes = 0.0, []
    acres = cs.value("acres")
    try:
        acres = float(acres) if acres is not None else None
    except (TypeError, ValueError):
        acres = None

    if acres and acres >= 3:
        pts += 2.0
        notes.append(f"{acres:.1f} acres could be partly sold or split later, "
                     f"subject to the minimum-extent rules.")
    if cs.get("road_frontage").truthy():
        pts += 1.5
        notes.append("Road frontage keeps future options open.")
    if driving_km is not None and driving_km <= 20:
        pts += 1.5
        notes.append("Inside the belt where Mysuru's growth is most likely to "
                     "reach — appreciation potential, and acquisition exposure "
                     "with it.")
    if cs.get("risk_acquisition").truthy():
        pts = 0.0
        notes.append("Acquisition risk cancels the optionality case entirely: "
                     "land taken at compensation rates is not an option, it is a "
                     "loss.")
    return min(pts, 5.0), notes


def category_for(score: int) -> tuple[str, str, str]:
    for floor, letter, name, meaning in CATEGORIES:
        if score >= floor:
            return letter, name, meaning
    return "E", "REJECT", CATEGORIES[-1][3]


def score_deal(cs: ClaimSet, water_result: dict, agri_result: dict,
               retirement_result: dict, legal_result: dict,
               price_result: dict, driving_km=None) -> dict:
    """Combine every engine into DEAL_SCORE, category and status."""
    breakdown = []

    legal_pts, legal_why = _legal_points(legal_result)
    breakdown.append({"factor": "Legal / documents", "weight": 25,
                      "points": round(legal_pts, 1), "why": legal_why})

    water_pts = (water_result.get("score", 0) / 100.0) * 25.0
    breakdown.append({"factor": "Water", "weight": 25, "points": round(water_pts, 1),
                      "why": f"Water score {water_result.get('score')} "
                             f"({water_result.get('label')})"
                             + (" — capped, unverified claims only"
                                if water_result.get("capped_by_evidence") else "")})

    agri_pts = (agri_result.get("score", 0) / 100.0) * 15.0
    breakdown.append({"factor": "Agriculture", "weight": 15,
                      "points": round(agri_pts, 1),
                      "why": f"Agriculture score {agri_result.get('score')} "
                             f"({agri_result.get('label')})"})

    loc_pts, loc_notes = _location_points(cs, driving_km)
    breakdown.append({"factor": "Location / access", "weight": 10,
                      "points": round(loc_pts, 1), "why": " ".join(loc_notes)})

    price_pts, price_why = _price_points(price_result)
    breakdown.append({"factor": "Price", "weight": 10, "points": round(price_pts, 1),
                      "why": price_why})

    ret_pts = (retirement_result.get("score", 0) / 100.0) * 10.0
    breakdown.append({"factor": "Retirement suitability", "weight": 10,
                      "points": round(ret_pts, 1),
                      "why": f"Retirement score {retirement_result.get('score')} "
                             f"({retirement_result.get('label')})"})

    opt_pts, opt_notes = _optionality_points(cs, driving_km)
    breakdown.append({"factor": "Future optionality", "weight": 5,
                      "points": round(opt_pts, 1),
                      "why": " ".join(opt_notes) or "No particular optionality."})

    raw = sum(b["points"] for b in breakdown)
    score = int(round(max(0.0, min(100.0, raw))))
    gates: list[str] = []

    # -- gates ---------------------------------------------------------------
    level = legal_result.get("level")
    if level == legal_mod.HIGH:
        status = DO_NOT_PROCEED
        score = min(score, 20)
        gates.append(
            "STOPPED on legal risk. A hard-stop category is present, and no "
            "combination of price, water or location offsets a title that can be "
            "undone after you have paid. Excluded from all ranked lists.")
    elif level == legal_mod.UNKNOWN:
        status = DUE_DILIGENCE
        if score > UNKNOWN_LEGAL_CAP:
            gates.append(
                f"Capped at {UNKNOWN_LEGAL_CAP}/100 because legal risk is UNKNOWN. "
                f"The parcel scores well on everything that can be read from an "
                f"advert — which is not the same as scoring well. Get documents "
                f"and the cap lifts.")
            score = UNKNOWN_LEGAL_CAP
    elif level == legal_mod.MEDIUM:
        status = DUE_DILIGENCE
    else:
        status = PROCEED_CAUTION

    ws = water_result.get("score", 0)
    if ws < WATER_FLOOR and score > WATER_FLOOR_CAP:
        gates.append(
            f"Capped at {WATER_FLOOR_CAP}/100 because the water score is {ws}. "
            f"Water is the one thing money cannot add to a parcel, and a "
            f"retirement property without it is not a cheap retirement property — "
            f"it is a different, worse thing.")
        score = WATER_FLOOR_CAP

    acres = cs.value("acres")
    try:
        acres = float(acres) if acres is not None else None
    except (TypeError, ValueError):
        acres = None
    if acres is not None and not (0.5 <= acres <= 10.0):
        gates.append(f"{acres:.2f} acres is outside the 0.5–10 acre range. Flagged, "
                     f"not rejected — but it is not the property that was asked for.")

    letter, cat_name, meaning = category_for(score)
    if status == DO_NOT_PROCEED:
        letter, cat_name = "E", "REJECT"
        meaning = "Legal hard stop."

    return {
        "score": score,
        "raw_score": round(raw, 1),
        "category": letter,
        "category_name": cat_name,
        "category_meaning": meaning,
        "status": status,
        "breakdown": breakdown,
        "gates": gates,
    }


# ------------------------------------------------------------- alerts ----

ALERT = "🚨 ALERT"
STRONG = "🟢 STRONG"
WATCH = "🟡 WATCH"
REJECT = "🔴 REJECT"


def alert_level(deal: dict, water: dict, retirement: dict, legal_result: dict,
                driving_km, acres) -> tuple[str, str]:
    """Alert band per the brief's criteria, with the reason.

    ALERT is deliberately hard to reach: it needs the size and distance
    targets met, real water, good retirement suitability, no legal hard stop
    *and* an A-grade deal score. If everything alerts, nothing does.
    """
    if legal_result.get("level") == legal_mod.HIGH:
        return REJECT, "Legal hard stop — do not proceed."

    in_size = acres is not None and 1.0 <= acres <= 5.0
    accept_size = acres is not None and 0.5 <= acres <= 10.0
    in_radius = driving_km is not None and driving_km <= 30.0
    good_water = water.get("score", 0) >= 60
    ok_retirement = retirement.get("score", 0) >= 60

    if deal["score"] >= 85 and in_size and in_radius and good_water and ok_retirement:
        return ALERT, ("Meets every target at once: size, distance, water, "
                       "retirement suitability and deal score. Investigate now.")
    if deal["score"] >= 72 and accept_size and in_radius and \
            water.get("score", 0) >= 50:
        return STRONG, "Strong on the factors that matter. Verify documents and visit."
    if deal["score"] >= 50:
        missing = []
        if not in_radius:
            missing.append("outside the 30 km target")
        if not accept_size:
            missing.append("outside the size range")
        if water.get("score", 0) < 50:
            missing.append("water not established")
        if water.get("capped_by_evidence"):
            missing.append("every water claim unverified")
        return WATCH, ("Worth tracking, but " +
                       (", ".join(missing) if missing else
                        "key information is still missing") + ".")
    return REJECT, "Fails on economics, location, water or land quality."
