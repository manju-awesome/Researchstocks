"""
water.py
========
WATER_SCORE / 100 — the most important number this system produces.

Around Mysuru, water is what separates land you can live on from land you
can only own. A parcel with a failed borewell and no canal is worth a
fraction of its neighbour and cannot be fixed with money — you can build a
house, lay a road, plant trees and improve soil, but you cannot make an
aquifer. So this score is weighted heavily in the deal score and, unlike
every other factor, it is *capped by evidence quality* rather than merely
discounted by it.

The cap is the design decision that matters
-------------------------------------------
Every listing says "good water". It costs nothing to write and it is the
single most-repeated claim in the market. If a seller's assertion of a
borewell could earn full marks, the top of the rankings would be sorted by
seller enthusiasm — which is the exact failure the brief warns about ("Do not
give a high score merely because the seller says 'good water'").

So: an unverified claim, however glowing, cannot exceed UNVERIFIED_CAP (55).
That is enough to be worth a phone call and never enough to outrank a parcel
where someone actually saw water running. The cap lifts as evidence arrives —
a site visit or a pump test rewrites the same claim at a higher confidence
and the score moves on its own.

Source ranking (the brief's ladder, with the reasoning)

    Canal / assured irrigation  Highest, when the parcel is genuinely in a
                                command area with an entitlement. Independent
                                of the water table and of electricity.
    Multiple independent        Borewell + open well + canal: redundancy is
      sources                   worth more than any single strong source,
                                because the failure modes are uncorrelated.
    Borewell + open well        An open well that holds water in April is the
                                best cheap evidence of a shallow table that
                                exists.
    Proven borewell             Depth, yield and — critically — summer
                                performance known.
    Seasonal irrigation         Useful for one crop cycle, not for living.
    Unverified borewell claim   Capped. Most listings sit here.
    No reliable water           Scored near zero and flagged hard.

Two traps this module refuses to fall into
------------------------------------------
1. **River proximity is not irrigation.** A parcel 200 m from the Kaveri may
   have no legal right to lift a drop from it. Proximity earns a small
   context credit and an explicit warning, never a water score.
2. **A borewell is not water.** A 900 ft borewell that yields half an inch in
   April is a dry hole with a pump on it. Depth without yield is recorded as
   an open question, and deep-without-yield is treated as a negative signal
   about the local table, not a positive one about the investment made.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet, EVIDENCE_LEVELS

# Ceiling on the score when nothing beyond the seller's word supports it.
UNVERIFIED_CAP = 55

# Above this, a borewell depth is telling you the water table is deep and
# the neighbours have been chasing it downward — a cost and a risk, not a
# feature. Local rule of thumb for this belt.
DEEP_BOREWELL_FT = 600
VERY_DEEP_BOREWELL_FT = 800

LABELS = ((85, "Assured"), (70, "Strong"), (55, "Adequate"),
          (40, "Questionable"), (20, "Weak"), (0, "Critical"))


def _label(score: int) -> str:
    for floor, name in LABELS:
        if score >= floor:
            return name
    return "Critical"


def score_water(cs: ClaimSet, harvest: dict | None = None) -> dict:
    """Compute WATER_SCORE with its full reasoning trail.

    Returns score, label, points breakdown, the evidence level the score is
    capped at, the questions still outstanding, and the warnings. The
    questions list is not an afterthought — for most properties it is the
    genuinely actionable output, since it is the exact set of things to ask
    on the first phone call.
    """
    points = 0.0
    drivers: list[str] = []
    warnings: list[str] = []
    questions: list[str] = []

    canal = cs.get("water_canal")
    river = cs.get("water_river")
    open_well = cs.get("water_open_well")
    borewell = cs.get("water_borewell")
    lake = cs.get("water_lake_tank")
    rain_fed = cs.get("water_rain_fed")

    depth = cs.get("borewell_depth_ft")
    count = cs.get("borewell_count")
    yield_c = cs.get("borewell_yield_inches")
    summer = cs.get("summer_yield")          # only ever set by verification
    age = cs.get("borewell_age_years")
    storage = cs.get("water_storage")
    power = cs.get("three_phase_power")
    pump = cs.get("pump")
    tested = cs.get("water_tested")

    # Best evidence supporting *any* water source — this sets the cap.
    source_claims = [canal, open_well, borewell, lake]
    best_evidence = max((c.confidence for c in source_claims if c.truthy()),
                        key=lambda c: 0 if c in EVIDENCE_LEVELS else 1, default=None)
    has_evidence = any(c.truthy() and c.is_evidence for c in source_claims)

    # -- primary source (max 55) -------------------------------------------
    sources_present = 0

    if canal.truthy():
        sources_present += 1
        points += canal.scaled(50)
        drivers.append(f"Canal / irrigation channel claimed ({canal.badge()})")
        questions.append("Is the parcel inside a declared canal command area, and "
                         "what is its registered entitlement? Ask for the "
                         "irrigation department record, not the seller's word.")
        questions.append("How many days a year does the canal actually run? "
                         "Ask three neighbours, not the seller.")

    if borewell.truthy():
        sources_present += 1
        base = 38
        d = _num(depth.value)
        if d:
            if d >= VERY_DEEP_BOREWELL_FT:
                base = 24
                warnings.append(
                    f"Borewell is {d:.0f} ft deep. At this depth the local water "
                    f"table is under real pressure — deep does not mean strong, it "
                    f"usually means the shallow water was already gone.")
            elif d >= DEEP_BOREWELL_FT:
                base = 32
                warnings.append(
                    f"Borewell at {d:.0f} ft is on the deep side for this belt. "
                    f"Check what the neighbours' borewells are yielding.")
            drivers.append(f"Borewell {d:.0f} ft ({depth.badge()})")
        else:
            questions.append("How deep is the borewell? Depth was not stated.")
            drivers.append(f"Borewell claimed, depth unstated ({borewell.badge()})")
        points += borewell.scaled(base)

        n = _num(count.value)
        if n and n >= 2:
            points += count.scaled(10)
            drivers.append(f"{n:.0f} borewells — redundancy against one failing")

        if yield_c.known:
            points += yield_c.scaled(8)
            drivers.append(f"Yield stated: {yield_c.value} ({yield_c.badge()})")
        else:
            questions.append("What does the borewell yield, in inches? A depth "
                             "with no yield figure tells you nothing.")

        if summer.known:
            points += summer.scaled(12)
            drivers.append(f"Summer yield known: {summer.value} ({summer.badge()})")
        else:
            questions.append(
                "What does this borewell yield in April–May, at the end of the dry "
                "season? This is the single most important water question and the "
                "one sellers are least likely to volunteer.")

        if age.known:
            drivers.append(f"Borewell age: {age.value} years ({age.badge()})")
        else:
            questions.append("How old is the borewell, and has it ever been "
                             "deepened or re-drilled?")

    if open_well.truthy():
        sources_present += 1
        points += open_well.scaled(22)
        drivers.append(f"Open well ({open_well.badge()})")
        questions.append("Does the open well hold water through April? An open "
                         "well with standing water in summer is the best evidence "
                         "of a shallow table you can get without a pump test.")

    if lake.truthy():
        points += lake.scaled(6)
        drivers.append(f"Lake / tank nearby ({lake.badge()})")
        warnings.append("A nearby lake or tank helps the local water table but "
                        "confers no right to use the water. It can also mean a "
                        "buffer-zone restriction on building — check the extent.")

    # -- redundancy bonus ---------------------------------------------------
    if sources_present >= 3:
        points += 12
        drivers.append("Three or more independent water sources — the failure "
                       "modes are uncorrelated, which is what security means")
    elif sources_present == 2:
        points += 7
        drivers.append("Two independent water sources")

    # -- infrastructure (max ~15) ------------------------------------------
    if power.truthy():
        points += power.scaled(6)
        drivers.append(f"Three-phase power for the pump ({power.badge()})")
    elif borewell.truthy():
        questions.append("Is there a three-phase connection? A borewell without "
                         "reliable power is a borewell you cannot run when you "
                         "need it.")
    if pump.truthy():
        points += pump.scaled(3)
    if storage.truthy():
        points += storage.scaled(5)
        drivers.append(f"Water storage: {storage.value} ({storage.badge()})")
    else:
        questions.append("Is there a sump, tank or farm pond? Storage decouples "
                         "you from daily supply interruptions.")
    if tested.truthy():
        points += tested.scaled(4)
        drivers.append(f"Water quality tested ({tested.badge()})")
    else:
        questions.append("Has the water been tested for salinity, hardness and "
                         "nitrates? Cheap to do, and the result decides whether "
                         "you can drink it as well as irrigate with it.")

    # -- negatives ---------------------------------------------------------
    if rain_fed.truthy() and sources_present == 0:
        warnings.append("Described as rain-fed / dry land with no other source. "
                        "This is one-season farming and not a year-round "
                        "residence unless you create a source.")
    if cs.get("water_borewell_absent").truthy():
        warnings.append("The listing appears to state there is NO borewell "
                        "(or that one 'can be dug' — which means there isn't one). "
                        "Budget ₹3–6 lakh and accept a real chance of a dry hole.")
        questions.append("Have any borewells been attempted on this parcel or the "
                         "neighbouring ones, and what happened? A village with "
                         "three failed bores is telling you something.")

    if river.truthy():
        drivers.append(f"River nearby ({river.badge()})")
        warnings.append(
            "River proximity is NOT an irrigation right. Lifting water from a "
            "river requires a permission the parcel may not have, and riverside "
            "land often carries buffer-zone building restrictions. Treat this as "
            "zero water security until an entitlement document says otherwise.")
        questions.append("Is there a lift-irrigation permission or registered "
                         "pumping right from the river? Ask to see it.")

    if sources_present == 0 and not river.truthy():
        warnings.append("No water source of any kind is mentioned. For a "
                        "retirement property this is disqualifying until proven "
                        "otherwise — everything else is negotiable, this is not.")
        questions.append("What is the water source? Nothing in the listing "
                         "answers this.")

    # -- harvesting potential (max HARVEST_WATER_BONUS) ---------------------
    # Deliberately small and applied BEFORE the cap, so it can never make an
    # unverified parcel look wet. This is buildable water, not present water,
    # and the distinction is the whole reason watershed.py is a separate
    # module: a good slope and 900 mm of rain is a rescue path for a mediocre
    # borewell, not a substitute for one.
    if harvest and harvest.get("score") is not None:
        from findfarms.core.watershed import HARVEST_WATER_BONUS
        bonus = (harvest["score"] / 100.0) * HARVEST_WATER_BONUS
        points += bonus
        vols = harvest.get("volumes") or {}
        litres = vols.get("harvestable_litres")
        drivers.append(
            f"Rainwater harvesting potential adds {bonus:.0f}/{HARVEST_WATER_BONUS} "
            f"(harvest score {harvest['score']}"
            + (f", ~{litres / 1_000_000:.1f} million litres/year buildable"
               if litres else "")
            + ") — potential, not water the parcel has today")
        if harvest["score"] >= 65 and sources_present <= 1:
            drivers.append(
                "Weak on existing water but strong on harvesting potential: a "
                "pond and recharge structures are a realistic and comparatively "
                "cheap way to fix this parcel, which is not true of every parcel")

    # -- neighbour context --------------------------------------------------
    if not cs.get("neighbour_borewell_status").known:
        questions.append("What are the neighbouring parcels' borewells doing — "
                         "depth, yield, and any that have failed? The neighbours "
                         "are the only honest source on the local water table.")

    score = int(round(max(0.0, min(100.0, points))))

    # -- the evidence cap ---------------------------------------------------
    capped = False
    if score > UNVERIFIED_CAP and not has_evidence:
        score = UNVERIFIED_CAP
        capped = True
        warnings.append(
            f"Score capped at {UNVERIFIED_CAP}/100: every water claim here rests "
            f"on the seller's word alone. This is not scepticism about this "
            f"particular seller — it is that an unverified water claim cannot be "
            f"allowed to outrank a parcel where water was actually observed. "
            f"A site visit or a pump test lifts this cap immediately.")

    return {
        "score": score,
        "label": _label(score),
        "capped_by_evidence": capped,
        "evidence_level": best_evidence or "UNKNOWN",
        "sources_present": sources_present,
        "drivers": drivers,
        "warnings": warnings,
        "questions": questions,
    }


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
