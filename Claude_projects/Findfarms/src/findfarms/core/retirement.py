"""
retirement.py
=============
RETIREMENT_SCORE / 100 — can two people in their seventies live here well,
for twenty years, on a bad day?

This is scored against a harder standard than "is it a nice place". The brief
is explicit that this is for the user's parents, and that livability should
outrank agricultural return and appreciation. So the score is built around
the days that go wrong rather than the days that go right:

  * A chest pain at 2am in July. How long to a hospital, on a road that is
    passable in the monsoon, in a vehicle that has to be driven by someone
    who is also seventy?
  * A week of no rain and a failed pump. Is there anyone within shouting
    distance?
  * A three-day power cut. Does the phone work well enough to call for help?

Weightings follow from that:

    Healthcare access        20   The one that is irreversible when it fails
    Road access, main-road   22   A road that floods is not a road. This is
      connectivity, monsoon       the largest single bucket because the
                                  unpaved last mile decides whether every
                                  other factor is reachable in August
    Distance to Mysuru       14   Not for convenience — for how often the
                                  children and grandchildren actually come
    Water reliability        13   Living, not irrigation
    Community / neighbours   10   Isolation is the quiet killer of rural
                                  retirement plans; an empty farm is a
                                  security problem and a loneliness problem
    Power + connectivity      8   Ambulance calls, telemedicine, banking
    Yoga / wellness access    7   Mysuru-specific and not a luxury item: a
                                  daily practice is one of the few things
                                  that reliably structures a retirement, and
                                  it only survives if the trip is short
    Schools (family use)      4   Not for the retirees — for grandchildren
                                  staying, and for a caretaker family to be
                                  willing to live nearby
    Existing structure        2   Somewhere to stay from day one

On the two smaller additions: they are weighted to break ties between
otherwise comparable parcels, not to move a property between categories. A
farm with excellent yoga access and no water must never outrank a farm with
water, and at 7 and 4 points they cannot.

The distance thresholds for yoga and schools are much tighter than for
hospitals, because the trip frequency is inverted. A hospital 20 km away is
acceptable — you make that trip rarely and under duress. A yoga class 20 km
away is a trip you make five mornings a week, which means in practice you
stop making it within a month. So the bands below score generously up to
about 12 km and fall away sharply after.

The deliberate omission: **land appreciation is not in this score at all.**
It is not a retirement-livability factor and folding it in would let a
speculative location outrank a livable one. Optionality is handled separately,
at 5% of the deal score, where it belongs.

Distance is scored non-monotonically. Very close to the city is *not* best —
that belt is priced as urban fringe, is the first to be acquired for road
widening or a layout, and puts you next to development rather than fields.
The 10-30 km band is the target and scores highest.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet
from findfarms.core import geo

# Beyond this, an emergency is a genuinely different proposition. 20 km on a
# district road at night is roughly 35-45 minutes to a hospital that can
# actually admit someone.
HOSPITAL_COMFORTABLE_KM = 12.0
HOSPITAL_ACCEPTABLE_KM = 20.0

# Tighter than healthcare, deliberately: these are habitual trips, not
# emergency ones, and a habit does not survive a long drive.
YOGA_COMFORTABLE_KM = 12.0
YOGA_ACCEPTABLE_KM = 20.0
SCHOOL_COMFORTABLE_KM = 8.0
SCHOOL_ACCEPTABLE_KM = 15.0

LABELS = ((85, "Excellent"), (70, "Comfortable"), (55, "Workable"),
          (40, "Demanding"), (0, "Unsuitable"))


def _label(score: int) -> str:
    for floor, name in LABELS:
        if score >= floor:
            return name
    return "Unsuitable"


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def score_retirement(cs: ClaimSet, resolved: dict | None = None,
                     driving_km: float | None = None,
                     water_score: int | None = None) -> dict:
    """Compute RETIREMENT_SCORE.

    `resolved` is the geo.resolve_location() output; `driving_km` the
    estimated road distance to Mysuru. Both are passed in so this module
    never re-derives geography and can never disagree with the location shown
    on the property page.
    """
    points = 0.0
    drivers: list[str] = []
    warnings: list[str] = []
    questions: list[str] = []

    resolved = resolved or {}
    lat, lon = resolved.get("lat"), resolved.get("lon")
    amenities = geo.nearest_amenities(lat, lon) if lat and lon else {}

    # A parcel positioned at its village centroid sits 0.0 km from that
    # village's own amenities — an artifact of the positioning, not a fact
    # about the parcel, and it renders as "schools ~0.0 km" which reads as
    # broken. Farmland is not at the village centre; it is the land around
    # it, typically 1-3 km out. So a floor is applied to EVERY amenity kind
    # and the reason is said out loud.
    #
    # Applied uniformly rather than per-amenity: the first version floored
    # only hospitals, and every school in the seeded database then showed
    # 0.0 km, which is both wrong and the kind of wrong that looks like a
    # rendering bug rather than a modelling one.
    CENTROID_FLOOR_KM = 2.0
    centroid_artifact = False
    if resolved.get("method") == "village_centroid":
        for kind in geo.AMENITY_KINDS:
            v = amenities.get(kind)
            if v is not None and v < 1.5:
                amenities[kind] = CENTROID_FLOOR_KM
                centroid_artifact = True

    # -- healthcare (20) ----------------------------------------------------
    hosp_km = amenities.get("hospital")
    hosp_name = amenities.get("hospital_name")

    if hosp_km is not None:
        if hosp_km <= HOSPITAL_COMFORTABLE_KM:
            points += 20
            drivers.append(f"~{hosp_km:.0f} km to {hosp_name} — an emergency is a "
                           f"short drive, day or night")
        elif hosp_km <= HOSPITAL_ACCEPTABLE_KM:
            points += 14
            drivers.append(f"~{hosp_km:.0f} km to {hosp_name}")
            warnings.append(
                f"Nearest town with hospital facilities is ~{hosp_km:.0f} km "
                f"({hosp_name}). Workable, but for anything serious the real "
                f"destination is Mysuru — plan around that distance, not this one.")
        else:
            points += 6
            warnings.append(
                f"Nearest hospital town is ~{hosp_km:.0f} km away ({hosp_name}). "
                f"For a couple in their seventies this is the factor that decides "
                f"whether this property works in ten years, and it is the one "
                f"thing about it you can never change.")
        if centroid_artifact:
            drivers[-1:] = [f"{hosp_name} itself has hospital facilities — the "
                            f"parcel is within that village's land"]
            warnings.append(
                f"The parcel is positioned at its village centre because the "
                f"listing gave no coordinates, so every amenity distance below "
                f"~{CENTROID_FLOOR_KM:.0f} km is a floor, not a measurement. The "
                f"parcel could be 3 km further out on a mud road. Establish the "
                f"real distances before treating access as solved.")
        questions.append(
            f"Which hospital would you actually go to at 2am, and how long does "
            f"that drive take at night? Drive it once before deciding — the "
            f"~{hosp_km:.0f} km here is to the nearest town with facilities, not "
            f"to a specific verified hospital.")
    else:
        questions.append("How far is the nearest hospital that can admit a "
                         "patient overnight? Could not be estimated — the parcel's "
                         "location did not resolve.")
        warnings.append("Healthcare access could not be estimated. Treat the "
                        "retirement score as provisional.")

    # -- road access, main-road connectivity, monsoon (22) ------------------
    surface = cs.get("road_surface")
    frontage = cs.get("road_frontage")
    width = _num(cs.get("road_width_ft").value)
    access_type = cs.get("access_type")

    # Connectivity to a main tarred road (10 of the 22). Scored before
    # frontage and surface because it dominates them: a parcel with perfect
    # frontage on a lane 3 km of mud from the nearest tar road is, in the
    # monsoon, a parcel with no access at all.
    road_m = _num(cs.get("main_road_distance_m").value)
    band, band_why = geo.main_road_band(
        road_m, surface.value if surface.known else None)
    main_road_points = geo.MAIN_ROAD_POINTS.get(band, 0.0) * 10.0
    points += main_road_points

    if band == "UNKNOWN":
        questions.append(
            "How far is the parcel from the nearest main tarred road, and is "
            "that whole approach tarred? Sellers state this when it is good and "
            "omit it when it is not, so treat silence as a bad sign until you "
            "have driven it.")
        warnings.append(
            "Distance to a main tarred road is not stated, so 10 of the 22 "
            "access points could not be earned. This is the single most "
            "under-reported number in these listings and one of the most "
            "important for a retirement property.")
    elif band in ("ON_MAIN_ROAD", "EXCELLENT", "GOOD"):
        drivers.append(
            (f"Fronts a main tarred road" if band == "ON_MAIN_ROAD"
             else f"~{road_m:.0f} m from a main tarred road")
            + f" ({cs.get('main_road_distance_m').badge()})")
    else:
        warnings.append(band_why)
        questions.append(
            f"Drive the approach from the main road yourself, and ask a "
            f"neighbour what it is like in July. {road_m:.0f} m is the listing's "
            f"figure, not a measured one.")

    if band not in ("UNKNOWN",) and band_why and band in ("ON_MAIN_ROAD",
                                                          "EXCELLENT", "GOOD"):
        drivers.append(band_why)

    if surface.known and str(surface.value).lower() == "tarred":
        points += surface.scaled(7)
        drivers.append(f"Tarred road access ({surface.badge()})")
    elif surface.known:
        points += 2
        warnings.append(
            "Access road is unpaved. In this region that means the last stretch "
            "is doubtful for six weeks of the monsoon — which is exactly when a "
            "medical emergency is hardest to handle.")
        questions.append("Is the approach road passable by car in July and "
                         "August? Ask someone who lives there, and if at all "
                         "possible visit during the monsoon.")
    else:
        questions.append("What is the approach road — tarred or mud, and how far "
                         "is the unpaved stretch?")

    if frontage.truthy():
        points += frontage.scaled(3)
        drivers.append(f"Road frontage ({frontage.badge()})")
    else:
        questions.append("Does the parcel touch a public road, or is access "
                         "through someone else's land?")

    if width:
        if width >= 20:
            points += 2
            drivers.append(f"{width:.0f} ft road — wide enough for an ambulance "
                           f"and a truck to pass")
        else:
            warnings.append(f"{width:.0f} ft access road is narrow. Check that a "
                            f"car and an ambulance can actually get to the gate.")

    if access_type.known and "private" in str(access_type.value).lower():
        warnings.append(
            "Access is described as private, common or shared. Confirm there is a "
            "registered right of way in the sale deed. An access road that depends "
            "on a neighbour's goodwill is the most common way a good parcel turns "
            "into an unusable one after a disagreement.")
        questions.append("Is the access road a registered public road, or a "
                         "private one? If private, is the right of way in writing "
                         "and does it survive a sale of the neighbouring land?")

    # -- distance to Mysuru (14), non-monotonic -----------------------------
    if driving_km is None:
        questions.append("Distance to Mysuru could not be estimated.")
    else:
        status, why = geo.radius_status(driving_km)
        if status == "PREFERRED":
            points += 14
            drivers.append(f"~{driving_km:.0f} km from Mysuru — close enough for "
                           f"family to visit often, far enough to be countryside")
        elif status == "INSIDE_CLOSE":
            points += 11
            drivers.append(f"~{driving_km:.0f} km — very convenient")
            warnings.append(why)
        elif status == "OUTSIDE_NEAR":
            points += 7
            warnings.append(why)
        else:
            points += 2
            warnings.append(why)
            warnings.append(
                "Distance compounds for a retirement property in a way it does not "
                "for an investment: it is paid on every hospital trip, every "
                "grocery run and every visit the children decide not to make.")

    # -- market / groceries -------------------------------------------------
    mkt_km = amenities.get("market")
    if mkt_km is not None:
        if mkt_km <= 8:
            points += 4
            drivers.append(f"~{mkt_km:.0f} km to {amenities.get('market_name')} "
                           f"for groceries")
        elif mkt_km > 15:
            warnings.append(f"Nearest market town is ~{mkt_km:.0f} km — weekly "
                            f"shopping becomes a planned expedition.")

    # -- yoga and wellness access (7) ---------------------------------------
    # Mysuru-specific, and not an indulgence. A daily practice is one of the
    # few things that reliably gives a retirement its shape, and the shalas
    # here are a real reason to retire in this district rather than another.
    # It only survives a short trip, hence the tight bands.
    yoga_km = amenities.get("yoga")
    yoga_name = amenities.get("yoga_name")
    well_km = amenities.get("wellness")
    well_name = amenities.get("wellness_name")

    if yoga_km is not None:
        if yoga_km <= YOGA_COMFORTABLE_KM:
            points += 5
            drivers.append(f"~{yoga_km:.0f} km to yoga shalas at {yoga_name} — "
                           f"close enough for a practice to actually become daily")
        elif yoga_km <= YOGA_ACCEPTABLE_KM:
            points += 2.5
            warnings.append(
                f"Nearest yoga shalas are ~{yoga_km:.0f} km away ({yoga_name}). "
                f"Feasible two or three times a week; a daily practice at this "
                f"distance is a 40-minute round trip and rarely survives the "
                f"first month.")
        else:
            warnings.append(
                f"Nearest yoga shalas are ~{yoga_km:.0f} km away ({yoga_name}). "
                f"If a regular practice is part of the reason for retiring near "
                f"Mysuru specifically, this parcel does not deliver it.")
        questions.append(
            "If yoga is part of the plan, visit the shalas you would actually "
            "attend and ask about enrolment — the well-known Mysuru schools run "
            "waiting lists and fixed terms, so proximity alone does not mean a "
            "place. The distance here is to the neighbourhood where shalas "
            "cluster, not to a specific verified studio.")
    if well_km is not None and well_km <= 15:
        points += 2
        drivers.append(f"~{well_km:.0f} km to ayurveda / wellness facilities "
                       f"({well_name})")

    # -- schools, for family use (4) -----------------------------------------
    # Not for the retirees. Two things this actually buys: grandchildren able
    # to stay for a term rather than a weekend, and a caretaker family willing
    # to live nearby — which is usually decided by where their children can go
    # to school.
    school_km = amenities.get("school")
    school_name = amenities.get("school_name")
    if school_km is not None:
        if school_km <= SCHOOL_COMFORTABLE_KM:
            points += 4
            drivers.append(
                f"~{school_km:.0f} km to schools ({school_name}) — matters for "
                f"grandchildren staying, and for a caretaker family to be "
                f"willing to live here")
        elif school_km <= SCHOOL_ACCEPTABLE_KM:
            points += 2
        else:
            warnings.append(
                f"Nearest schooling is ~{school_km:.0f} km ({school_name}). This "
                f"narrows who will live on or near the land — caretaker families "
                f"with children generally will not, which is a staffing problem "
                f"before it is anything else.")
        questions.append(
            "Which schools are actually within reach, and does a school bus run "
            "to this village? Ask a family in the village rather than the seller "
            "— the distance here is to the nearest town with schools, not to a "
            "specific verified school.")

    # -- water for living (13) ----------------------------------------------
    if water_score is not None:
        wp = (water_score / 100.0) * 13.0
        points += wp
        drivers.append(f"Water reliability contributes {wp:.0f}/13 "
                       f"(water score {water_score})")
        if water_score < 40:
            warnings.append(
                "Weak water is a livability problem before it is an agricultural "
                "one. Drinking, washing and a garden are the daily reality; a "
                "tanker-dependent house is not a retirement.")
    else:
        questions.append("Water assessment unavailable — this score is incomplete.")

    if not cs.get("water_tested").known:
        questions.append("Get the water tested for drinking quality specifically. "
                         "Irrigation-grade water and drinking-grade water are not "
                         "the same test.")

    # -- community and security (10) ----------------------------------------
    village = cs.get("village").value or resolved.get("matched_name")
    if cs.get("neighbouring_houses").known:
        c = cs.get("neighbouring_houses")
        points += c.scaled(5)
        drivers.append(f"Neighbouring houses: {c.value} ({c.badge()})")
    else:
        questions.append(
            "How many occupied houses are within walking distance, and is anyone "
            "there at night? An isolated farm is a security question and, more "
            "quietly, a loneliness one — this is the factor people underestimate "
            "most and regret fastest.")

    if cs.get("caretaker").truthy():
        points += cs.get("caretaker").scaled(3)
        drivers.append(f"Caretaker arrangement mentioned ({cs.get('caretaker').badge()})")
    else:
        questions.append("Is there a caretaker family in the village who could "
                         "look after the land, and what would that cost? Arrange "
                         "this before you buy, not after.")

    if village:
        points += 2
        drivers.append(f"Located at {village} — an established village rather "
                       f"than open country")

    # -- power and connectivity (8) -----------------------------------------
    if cs.get("electricity").truthy():
        points += cs.get("electricity").scaled(5)
        drivers.append(f"Electricity connection ({cs.get('electricity').badge()})")
    else:
        questions.append("Is there an existing electricity connection to the "
                         "parcel, and how far is the nearest transformer? Getting "
                         "a new connection out to a field takes months.")
        warnings.append("No electricity connection mentioned. Verify before "
                        "assuming one exists.")

    if cs.get("mobile_signal").known:
        c = cs.get("mobile_signal")
        points += c.scaled(3)
        drivers.append(f"Mobile signal: {c.value} ({c.badge()})")
    else:
        questions.append(
            "Check mobile signal standing on the parcel itself, on more than one "
            "network — not in the village centre. This is how an ambulance gets "
            "called, and coverage drops off sharply between the road and the field.")

    if not cs.get("internet").known:
        questions.append("Is there fibre or fixed wireless broadband in the "
                         "village? Telemedicine, banking and video calls with "
                         "family all depend on it.")

    # -- existing structure (2) ---------------------------------------------
    if cs.get("farmhouse").truthy():
        points += cs.get("farmhouse").scaled(2)
        drivers.append(f"Existing farmhouse ({cs.get('farmhouse').badge()}) — "
                       f"somewhere to stay while everything else is sorted out")
        questions.append(
            "Is the farmhouse legally built? A structure on agricultural land "
            "often has no building approval, which becomes your problem on "
            "purchase, not the seller's.")
    elif cs.get("shed").truthy():
        points += cs.get("shed").scaled(2)

    score = int(round(max(0.0, min(100.0, points))))

    return {
        "score": score,
        "label": _label(score),
        "hospital_km": hosp_km,
        "hospital_name": hosp_name,
        "market_km": mkt_km,
        "yoga_km": yoga_km,
        "yoga_name": yoga_name,
        "wellness_km": well_km,
        "wellness_name": well_name,
        "school_km": school_km,
        "school_name": school_name,
        "main_road_m": road_m,
        "main_road_band": band,
        "main_road_why": band_why,
        "drivers": drivers,
        "warnings": warnings,
        "questions": questions,
    }
