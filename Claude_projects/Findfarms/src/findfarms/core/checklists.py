"""
checklists.py
=============
The three lists the brief asks for on every candidate: what is missing, what
to verify on the site visit, and what documents to obtain.

These are the most practically useful output of the whole system, and they
are generated rather than fixed. A parcel claiming a canal gets canal
questions; a parcel with no borewell gets "what happened when the neighbours
drilled". A static checklist would be ignored by the third property; one that
names this parcel's specific unknowns gets used.

The site-visit list is ordered by what is hardest to undo rather than by
convenience: water and access first, because a wrong answer there ends the
purchase, and cosmetic things last. It also deliberately includes the items
people skip — going in the monsoon, standing on the land to check phone
signal, talking to neighbours rather than the seller — because those are the
ones that surface the problems.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet, VERIFIED, SITE_VISIT

# Fields whose absence materially changes the assessment, in the order they
# should be chased. (key, question, why it matters)
CRITICAL_UNKNOWNS = (
    ("acres", "Exact registered extent (from the RTC, not the advert)",
     "Everything price-related is computed from this."),
    ("asking_price", "Asking price, and whether it is per acre or total",
     "No price means no value judgement is possible."),
    ("survey_number", "Survey number and hissa",
     "Nothing can be checked — RTC, EC, guidance value — without it. A seller "
     "who will not give it before a visit is common; one who will not give it "
     "after a visit is a reason to walk away."),
    ("water_sources", "What the actual water source is",
     "The single largest determinant of whether this parcel works."),
    ("summer_yield", "Borewell yield in April–May",
     "A borewell that runs in December and not in April is not a water source."),
    ("village", "Village, hobli and taluk",
     "Determines which sub-registrar and taluk office hold the records."),
    ("road_surface", "Approach road surface and the last unpaved stretch",
     "Decides monsoon access, which decides emergency access."),
    ("main_road_distance_m", "Distance from the nearest main tarred road, and how "
     "much of that approach is unpaved",
     "A different question from road frontage, and a more decisive one. Frontage "
     "only means the parcel touches a road — which may be a mud lane. Sellers "
     "state this figure when it is good and omit it when it is not."),
    ("electricity", "Whether an electricity connection exists",
     "A new connection to a field takes months and costs real money."),
    ("undulation", "Which way and how much the land falls across its length",
     "Decides where a farm pond can go and whether gravity or a pump moves the "
     "stored water. A gentle fall is the best case for harvesting — better than "
     "dead-flat, which is the opposite of what the cultivation score prefers."),
)

SITE_VISIT_CHECKLIST = [
    # -- water: do this first, and do it properly -------------------------
    ("Water", "Run the borewell pump for at least 30–45 minutes and watch the "
              "discharge the whole time. A bore that starts strong and thins out "
              "is the most common way a 'good water' parcel disappoints."),
    ("Water", "Visit in April or May if the decision can wait for it. Any parcel "
              "looks watered in November. If it cannot wait, find someone who "
              "saw it last summer."),
    ("Water", "Look into the open well, if there is one, and note the standing "
              "water level against the season."),
    ("Water", "Ask three neighbours — not the seller and not the broker — how "
              "deep their borewells are, what they yield, and whether any have "
              "failed or been deepened."),
    ("Water", "If a canal is claimed: walk to it, confirm it reaches this parcel, "
              "and ask how many days it ran last year."),
    ("Water", "Take a water sample for a drinking-quality test, not just an "
              "irrigation one."),

    # -- access and boundaries --------------------------------------------
    ("Access", "Drive the full route from Mysuru yourself and time it. Do not "
               "accept the stated distance — the estimate in this system is "
               "computed, not measured, and the seller's is usually optimistic."),
    ("Access", "Measure the distance from the nearest main tarred road to the "
               "gate, on the odometer, and note how much of it is unpaved. This "
               "is the number that decides whether an ambulance, a delivery or a "
               "seventy-year-old driver reaches the property in August."),
    ("Access", "Drive the last kilometre and judge it in monsoon conditions. Ask "
               "whether the approach floods, and where the water goes."),
    ("Access", "Confirm the parcel physically touches a public road. If access "
               "crosses anyone else's land, that right of way must be registered "
               "and must survive a sale of that land."),
    ("Boundaries", "Walk the entire boundary. Note every stone, fence, bund and "
                   "tree line, and where a neighbour's crop crosses in."),
    ("Boundaries", "Book a licensed surveyor to measure the parcel against the "
                   "registered extent before paying anything. Advertised and "
                   "registered extents differ often enough to expect it."),

    # -- land ---------------------------------------------------------------
    ("Land", "Dig a pit two to three feet down in more than one spot. Check soil "
             "depth before rock, and whether it holds moisture."),
    ("Land", "Count and inspect the trees actually standing. Note age, health and "
             "whether they are bearing — a mature unproductive stand is a cost."),
    ("Land", "Stand at the lowest point and work out where monsoon water "
             "collects and drains. That point is where a farm pond goes, and "
             "finding it decides most of the harvesting potential."),
    ("Land", "Pace out the fall across the parcel — roughly how many feet does "
             "it drop from the highest corner to the lowest, and over what "
             "length? A gentle fall is worth more for water harvesting than "
             "dead-flat land, because runoff concentrates and gravity "
             "distributes the stored water without a pump."),
    ("Land", "Look for existing bunds, gullies, natural depressions or an old "
             "pond. Ask whether anything was ever built and silted up — a "
             "silted pond is far cheaper to restore than to dig."),
    ("Land", "Ask the neighbours whether their borewells improved after anyone "
             "nearby built a recharge pit or pond. It is the cheapest evidence "
             "you will get on whether recharge actually works in this soil."),
    ("Land", "Look at what the neighbours are growing. It is the most honest "
             "statement available about what this soil and water can support."),

    # -- livability, the part people skip ----------------------------------
    ("Livability", "Check mobile signal standing on the parcel itself, on two "
                   "different networks. Not in the village centre."),
    ("Livability", "Count the occupied houses within walking distance and ask "
                   "whether people are there at night."),
    ("Livability", "Drive from the parcel to the hospital you would actually use "
                   "in an emergency, and time that too."),
    ("Livability", "Ask about power-cut frequency and duration in summer."),
    ("Livability", "Find out who could act as caretaker, and what they would "
                   "charge. Settle this before buying, not after."),
    ("Livability", "Visit once after dark. Isolation, road lighting and how far "
                   "away help feels are all different at night."),
    ("Livability", "If a yoga or wellness practice is part of the plan, drive to "
                   "the shala you would actually attend, at the hour you would "
                   "attend it, and ask about enrolment — the established Mysuru "
                   "schools run waiting lists and fixed terms, so being nearby "
                   "does not mean having a place."),
    ("Livability", "Check which schools are within reach and whether a school bus "
                   "serves this village. This decides whether grandchildren can "
                   "stay for a term rather than a weekend, and whether a "
                   "caretaker family with children will live nearby at all."),

    # -- people ------------------------------------------------------------
    ("People", "Meet the person whose name is on the RTC, in person. Not a "
               "relative, not a broker, not a power-of-attorney holder without "
               "reading the power of attorney."),
    ("People", "Ask directly how many people have a share in this land, and get "
               "the answer against the genealogical tree, not against the "
               "seller's memory."),
    ("People", "Ask why they are selling, and listen for consistency with what "
               "the advert said."),
]


def missing_information(cs: ClaimSet, water: dict, agri: dict,
                        retirement: dict, legal: dict, price: dict) -> list[dict]:
    """Exactly what needs to be obtained, ordered by importance.

    Merges the critical-field gaps with each engine's own outstanding
    questions, de-duplicated. This is the call-the-seller list.
    """
    out: list[dict] = []
    seen = set()

    for key, question, why in CRITICAL_UNKNOWNS:
        c = cs.get(key)
        if not c.known:
            out.append({"priority": "CRITICAL", "item": question, "why": why})
            seen.add(question.lower()[:40])

    # Claims resting only on the seller's word for things that decide the
    # purchase. Not "missing" exactly — unconfirmed, which needs chasing too.
    for key, label in (("water_sources", "water source"),
                       ("acres", "extent"),
                       ("survey_number", "survey number"),
                       ("road_frontage", "road access")):
        c = cs.get(key)
        if c.known and c.confidence not in (VERIFIED, SITE_VISIT):
            item = f"Independent confirmation of the {label} " \
                   f"(currently {c.badge().lower()})"
            if item.lower()[:40] not in seen:
                out.append({"priority": "HIGH", "item": item,
                            "why": f"Currently rests on: {c.source or 'the listing'}."})
                seen.add(item.lower()[:40])

    for engine, tag in ((water, "Water"), (agri, "Agriculture"),
                        (retirement, "Retirement"), (price, "Price")):
        for q in engine.get("questions", []):
            k = q.lower()[:40]
            if k not in seen:
                out.append({"priority": "MEDIUM", "item": q, "why": f"({tag})"})
                seen.add(k)

    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
    out.sort(key=lambda d: order.get(d["priority"], 3))
    return out


def site_visit_checklist(cs: ClaimSet, water: dict) -> list[dict]:
    """The physical-verification list, tailored to this parcel."""
    items = [{"area": a, "item": t} for a, t in SITE_VISIT_CHECKLIST]

    # Parcel-specific additions, inserted at the front of the water section
    # because they are the reason this particular visit is being made.
    extra: list[dict] = []
    if cs.get("water_borewell_absent").truthy():
        extra.append({"area": "Water", "item":
                      "There is no borewell. Find out how many have been attempted "
                      "nearby and how many failed, and get a quote for drilling "
                      "before you price the parcel."})
    if cs.get("water_river").truthy():
        extra.append({"area": "Water", "item":
                      "River is claimed as a water source. Establish whether there "
                      "is any registered lifting right — proximity alone gives you "
                      "nothing — and check for buffer-zone building restrictions."})
    if cs.get("farmhouse").truthy():
        extra.append({"area": "Structures", "item":
                      "Check whether the farmhouse has any building approval. A "
                      "structure on unconverted agricultural land is usually "
                      "unapproved, and it becomes your problem on purchase."})
    if cs.get("access_type").known:
        extra.append({"area": "Access", "item":
                      "Access is described as private or shared. Trace exactly "
                      "whose land it crosses and get the right of way in writing."})
    if cs.get("risk_multiple_owners").truthy():
        extra.append({"area": "People", "item":
                      "Multiple owners are indicated. Get all of them in one room, "
                      "or at minimum confirm every one has agreed to sell."})

    depth = cs.get("borewell_depth_ft").value
    try:
        if depth and float(depth) >= 600:
            extra.append({"area": "Water", "item":
                          f"Borewell is {float(depth):.0f} ft — deep for this belt. "
                          f"Ask specifically whether it has been deepened before, "
                          f"and what it yielded when first drilled versus now."})
    except (TypeError, ValueError):
        pass

    return extra + items


def why_interesting(cs: ClaimSet, water: dict, agri: dict, retirement: dict,
                    price: dict, deal: dict, motivation: dict) -> list[str]:
    """3–5 points on what makes this worth a look. Honest when it is nothing."""
    pts: list[str] = []

    if water.get("score", 0) >= 65:
        pts.append(f"Water is the strongest thing here — {water['label'].lower()} "
                   f"at {water['score']}/100"
                   + (" (though still on the seller's word alone)"
                      if water.get("capped_by_evidence") else "") + ".")
    if price.get("position") == "CHEAP":
        pts.append(f"Priced below comparable listings — {price.get('ratio', 0):.0%} "
                   f"of the adjusted median in the {price.get('ring')}.")
    if retirement.get("score", 0) >= 70:
        pts.append(f"Genuinely livable: retirement suitability {retirement['score']}"
                   f"/100, hospital ~{retirement.get('hospital_km')} km.")
    if agri.get("perennials"):
        pts.append(f"Established perennials ({', '.join(agri['perennials'][:3])}) — "
                   f"yield without demanding daily management.")
    if motivation.get("level") in ("HIGHLY_MOTIVATED", "POSSIBLY_MOTIVATED"):
        beh = "behavioural" in motivation.get("evidence_kinds", [])
        pts.append(f"Negotiating room indicated"
                   + (" by actual price and time-on-market behaviour, not just "
                      "advert wording." if beh else " by the listing's wording "
                      "(weak evidence)."))
    if cs.get("owner_direct").truthy():
        pts.append("Owner-direct: negotiation with the decision-maker and no "
                   "commission built into the price.")
    if len(cs.claims) and cs.get("acres").known:
        try:
            a = float(cs.value("acres"))
            if 1.0 <= a <= 5.0:
                pts.append(f"{a:.2f} acres is squarely in the target range — "
                           f"productive without becoming a job.")
        except (TypeError, ValueError):
            pass

    if not pts:
        pts.append("Nothing here stands out. It is in the database so that it "
                   "counts as a comparable and so a future price drop is noticed.")
    return pts[:5]


def major_risks(cs: ClaimSet, water: dict, agri: dict, retirement: dict,
                legal: dict, price: dict, deal: dict) -> list[str]:
    """3–5 risks, worst first."""
    risks: list[str] = []

    for f in legal.get("findings", []):
        if f["severity"] == "HIGH":
            risks.append(f"LEGAL — {f['label']}: {f['why'].split('.')[0]}.")
    if legal.get("level") == "UNKNOWN":
        risks.append("Title is entirely unassessed. Nothing in the listing allows "
                     "any judgement about ownership, encumbrances or transfer "
                     "restrictions.")
    for f in legal.get("findings", []):
        if f["severity"] == "MEDIUM":
            risks.append(f"LEGAL — {f['label']}.")

    if water.get("capped_by_evidence"):
        risks.append("Every water claim rests on the seller's word. Water is the "
                     "one thing that cannot be fixed after purchase.")
    for w in water.get("warnings", [])[:2]:
        risks.append(f"WATER — {w.split('.')[0]}.")
    for w in retirement.get("warnings", [])[:2]:
        risks.append(f"LIVABILITY — {w.split('.')[0]}.")
    for w in agri.get("warnings", [])[:1]:
        risks.append(f"LAND — {w.split('.')[0]}.")
    for w in price.get("warnings", [])[:1]:
        risks.append(f"PRICE — {w.split('.')[0]}.")
    for g in deal.get("gates", []):
        risks.append(g.split(".")[0] + ".")

    # De-duplicate while preserving the worst-first order.
    seen, out = set(), []
    for r in risks:
        k = r.lower()[:50]
        if k not in seen:
            out.append(r)
            seen.add(k)
    return out[:5]
