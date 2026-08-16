"""
pipeline.py
===========
The workflow from the brief, wired end to end:

    DISCOVER → EXTRACT → DEDUPLICATE → GEOLOCATE → SCORE → RISK SCREEN
    → [ HUMAN REVIEW ] → SELLER CONTACT → DOCUMENT COLLECTION → SITE VISIT
    → LAWYER → SURVEYOR → NEGOTIATION → PURCHASE DECISION

Everything before the bracket is automated and lives here. Everything after
it is a person doing something in the physical world, tracked in the database
via `db.set_status` and `db.record_verification` but never advanced by code.

`analyse_property` is deliberately a pure function of (claims, database): it
takes no I/O and writes nothing, so scores can be recomputed at any time from
stored claims. That matters because claims get upgraded — you visit the land,
the water claim moves from SELLER_CLAIM to SITE_VISIT, and every score that
depended on it must move with it. If scores were computed once at ingest and
frozen, verifying a property would change nothing on its page, and the whole
confidence system would be decoration.
"""

from __future__ import annotations

from findfarms.core import (agriculture, checklists, deal, extract, geo,
                            legal, motivation, price, water)
from findfarms.core.claims import ClaimSet
from findfarms.store import db


def analyse_property(cs: ClaimSet, all_properties: dict | None = None,
                     property_id: str | None = None,
                     prop_record: dict | None = None,
                     price_timeline: list | None = None) -> dict:
    """Run every engine over one property's claims. No I/O, no writes.

    Order matters and is not arbitrary: geolocation feeds retirement and
    location scoring; water feeds agriculture, retirement and price
    comparability. Each engine receives the upstream result rather than
    recomputing it, so two parts of the app can never show different water
    scores for the same parcel.
    """
    all_properties = all_properties if all_properties is not None else {}

    # -- geolocate ---------------------------------------------------------
    resolved = geo.resolve_location(
        village=cs.value("village"), lat=cs.value("latitude"),
        lon=cs.value("longitude"), taluk=cs.value("taluk"))
    dist = geo.distance_claims(resolved, cs.value("seller_stated_distance"))
    driving_km = dist["_raw"]["driving_km"]
    radius_state, radius_why = geo.radius_status(driving_km)

    # -- score -------------------------------------------------------------
    # Watershed runs first: it needs only geography and the parcel's own
    # claims, and its harvesting potential is a (small, labelled) input to the
    # water score. Ordering it this way keeps one owner for each judgement.
    from findfarms.core import watershed as watershed_mod
    watershed_r = watershed_mod.score_watershed(cs, resolved)
    water_r = water.score_water(cs, watershed_r)
    agri_r = agriculture.score_agriculture(cs, water_r["score"])
    ret_r = retirement_r = None
    from findfarms.core import retirement as retirement_mod
    ret_r = retirement_mod.score_retirement(cs, resolved, driving_km, water_r["score"])
    legal_r = legal.screen_legal(cs)
    price_r = price.analyse_price(cs, all_properties, property_id, water_r["score"])
    motiv_r = motivation.assess_motivation(cs, prop_record, price_timeline)

    from findfarms.core import freshness as freshness_mod
    fresh_r = freshness_mod.assess_freshness(cs, prop_record)

    deal_r = deal.score_deal(cs, water_r, agri_r, ret_r, legal_r, price_r, driving_km)

    acres = cs.value("acres")
    try:
        acres = float(acres) if acres is not None else None
    except (TypeError, ValueError):
        acres = None

    alert, alert_why = deal.alert_level(deal_r, water_r, ret_r, legal_r,
                                        driving_km, acres)

    return {
        "location": {
            "resolved": resolved,
            "driving_km": driving_km,
            "straight_km": dist["_raw"]["straight_km"],
            "drive_minutes": dist["_raw"]["drive_minutes"],
            "radius_status": radius_state,
            "radius_why": radius_why,
            "claims": {k: v for k, v in dist.items() if k != "_raw"},
        },
        "water": water_r,
        "watershed": watershed_r,
        "agriculture": agri_r,
        "retirement": ret_r,
        "legal": legal_r,
        "price": price_r,
        "motivation": motiv_r,
        "freshness": fresh_r,
        "deal": deal_r,
        "alert": {"level": alert, "why": alert_why},
        "why_interesting": checklists.why_interesting(
            cs, water_r, agri_r, ret_r, price_r, deal_r, motiv_r),
        "major_risks": checklists.major_risks(
            cs, water_r, agri_r, ret_r, legal_r, price_r, deal_r),
        "missing_information": checklists.missing_information(
            cs, water_r, agri_r, ret_r, legal_r, price_r),
        "site_visit_checklist": checklists.site_visit_checklist(cs, water_r),
        "document_checklist": legal_r["document_checklist"],
        "conflicts": cs.conflicts(),
    }


def ingest(raw_text: str, source: str = "", source_url: str = "",
           extra: dict | None = None, force_property_id: str | None = None) -> dict:
    """DISCOVER → EXTRACT → DEDUPLICATE → GEOLOCATE → SCORE → RISK SCREEN.

    One listing in, a stored-and-scored property out, plus a description of
    what the dedup step decided so a human can overrule it.
    """
    cs = extract.extract_listing(raw_text, source=source, source_url=source_url,
                                 extra=extra)
    result = db.upsert_observation(cs, source=source, source_url=source_url,
                                   force_property_id=force_property_id)
    pid = result["property_id"]

    analysis = rescore_property(pid)
    result["analysis"] = analysis
    return result


def rescore_property(pid: str) -> dict | None:
    """Recompute and persist one property's scores from its stored claims.

    Called after ingest and after any verification. Persisting the scores is
    a cache for list views — the property page recomputes live, so a stale
    cached score can never be the thing a decision is made on.
    """
    props = db.load_properties()
    prop = props.get(pid)
    if not prop:
        return None
    cs = ClaimSet.from_dict(prop.get("claims", {}))
    analysis = analyse_property(cs, props, pid, prop, db.price_timeline(pid))

    props[pid]["scores"] = {
        "deal": analysis["deal"]["score"],
        "category": analysis["deal"]["category"],
        "status": analysis["deal"]["status"],
        "water": analysis["water"]["score"],
        "agriculture": analysis["agriculture"]["score"],
        "retirement": analysis["retirement"]["score"],
        "legal_risk": analysis["legal"]["level"],
        "harvest": analysis["watershed"]["score"],
        "rainfall_mm": analysis["watershed"]["rainfall_mm"],
        "river_km": analysis["watershed"]["rivers"].get("nearest_km"),
        "price_position": analysis["price"]["position"],
        "motivation": analysis["motivation"]["level"],
        "alert": analysis["alert"]["level"],
        "driving_km": analysis["location"]["driving_km"],
        "posted_date": analysis["freshness"]["posted_date"],
        "posted_exact": analysis["freshness"]["posted_exact"],
        "freshness": analysis["freshness"]["status"],
        "days_since_active": analysis["freshness"]["days_since_active"],
    }
    db.save_properties(props)
    return analysis


def rescore_all() -> int:
    """Recompute every property.

    Needed because scores are not independent: adding one listing to a
    village changes the comparable set, and therefore the price position and
    deal score, of every other parcel in that village. Run after a batch
    import or the ranking will be built on a stale price picture.
    """
    props = db.load_properties()
    for pid in list(props):
        rescore_property(pid)
    return len(props)


def check_alerts(fire: bool = True) -> list[dict]:
    """Find properties whose alert level has changed and log the new ones.

    Suppression is per property and per level (see db.already_alerted), so a
    WATCH that becomes an ALERT still fires — the escalation is the news.
    """
    out = []
    props = db.load_properties()
    for pid, prop in props.items():
        scores = prop.get("scores") or {}
        level = scores.get("alert")
        if not level or level == deal.REJECT:
            continue
        if db.already_alerted(pid, level):
            continue
        cs = ClaimSet.from_dict(prop.get("claims", {}))
        summary = (f"{level} — {cs.value('village') or 'unknown village'}, "
                   f"{cs.value('acres') or '?'} ac, deal score {scores.get('deal')}, "
                   f"water {scores.get('water')}, {scores.get('status')}")
        out.append({"property_id": pid, "level": level, "summary": summary})
        if fire:
            db.log_alert(pid, level, summary)
    return out


def price_drops(min_pct: float = 5.0) -> list[dict]:
    """Properties whose asking price has fallen since first discovery.

    The brief's headline use case. A parcel at ₹60L → ₹52L → ₹47L per acre is
    worth more attention than a hundred new listings, and this is the query
    that surfaces it.
    """
    out = []
    props = db.load_properties()
    for pid, prop in props.items():
        tl = db.price_timeline(pid)
        if len(tl) < 2:
            continue
        first, last = tl[0].get("price_per_acre"), tl[-1].get("price_per_acre")
        if not first or not last or last >= first:
            continue
        pct = (first - last) / first * 100
        if pct < min_pct:
            continue
        cs = ClaimSet.from_dict(prop.get("claims", {}))
        out.append({
            "property_id": pid,
            "village": cs.value("village") or "—",
            "acres": cs.value("acres"),
            "first_price": first, "current_price": last,
            "drop_pct": round(pct, 1),
            "steps": len(tl),
            "days_tracked": db.days_on_market(prop),
            "scores": prop.get("scores") or {},
            "flag": "POSSIBLE_NEGOTIATION_OPPORTUNITY",
        })
    out.sort(key=lambda d: -d["drop_pct"])
    return out
