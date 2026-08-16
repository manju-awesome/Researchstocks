"""
db.py
=====
The persistent property database. Flat JSON, matching the house pattern from
the trading workstation: single user, single machine, no server to stand up,
state you can read with your eyes and fix with a text editor.

The one rule this module exists to enforce
------------------------------------------
**Discovering a property again updates the existing record. It never creates
a second one.**

That single constraint is what makes the price-drop tracking in the brief
possible. If a re-discovery inserts a row, then the parcel near Hunsur Road
at ₹42L/acre and the same parcel at ₹35L/acre six months later are two
unrelated rows, and the ₹7L drop — the most valuable thing this system can
ever tell you — does not exist anywhere in the data. Every write therefore
goes through `upsert_observation`, which resolves identity first and only
then decides whether to merge or insert.

Layout
------
    properties.json    canonical parcels, keyed by property id
    observations.json  append-only log of every sighting, never rewritten
    price_history.json per-property price timeline
    alerts_log.json    what the alert engine has already fired on

Observations are append-only and separate from properties on purpose. The
property record is a merged, best-evidence view that changes over time; the
observation log is what was actually seen and when, so a merge that turns out
to be wrong can be unwound and the property rebuilt from source. Losing that
would mean a bad dedup silently destroys data.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, date
from pathlib import Path

from findfarms.core.claims import Claim, ClaimSet
from findfarms.core import dedup

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"

PROPERTIES_PATH = DATA_DIR / "properties.json"
OBSERVATIONS_PATH = DATA_DIR / "observations.json"
PRICE_HISTORY_PATH = DATA_DIR / "price_history.json"
ALERTS_PATH = DATA_DIR / "alerts_log.json"

# A price change smaller than this is noise — a broker rounding, or the same
# parcel quoted per-acre versus total with different rounding. Recording it
# as a "price drop" would bury real reductions under a stream of 0.4% moves.
MIN_PRICE_CHANGE = 0.02


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, payload) -> None:
    """Atomic write: temp file in the same directory, then rename.

    A half-written properties.json is the one failure that loses months of
    accumulated price history, and a plain `open(...,'w')` interrupted by a
    Ctrl-C during a scan produces exactly that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------- properties ----

def load_properties() -> dict:
    return _read(PROPERTIES_PATH, {})


def save_properties(props: dict) -> None:
    _write(PROPERTIES_PATH, props)


def get_property(pid: str) -> dict | None:
    return load_properties().get(pid)


def load_observations() -> list:
    return _read(OBSERVATIONS_PATH, [])


def load_price_history() -> dict:
    return _read(PRICE_HISTORY_PATH, {})


def _claimset(prop: dict) -> ClaimSet:
    return ClaimSet.from_dict(prop.get("claims", {}))


def upsert_observation(cs: ClaimSet, source: str = "", source_url: str = "",
                       force_property_id: str | None = None) -> dict:
    """Record one sighting and fold it into the property database.

    Returns a dict describing what happened: which property it landed on,
    whether that property is new, what changed, and any near-miss duplicates
    a human should confirm. The caller shows that to the user — a silent
    merge is a merge nobody can audit.
    """
    props = load_properties()
    existing = [(pid, _claimset(p)) for pid, p in props.items()]

    if force_property_id and force_property_id in props:
        pid, suggestions = force_property_id, []
        matched_reasons = ["Manually assigned to this property"]
    else:
        pid, suggestions = dedup.find_duplicates(cs, existing)
        matched_reasons = []
        if pid:
            _, reasons = dedup.match_score(cs, _claimset(props[pid]))
            matched_reasons = reasons

    is_new = pid is None
    if is_new:
        pid = dedup.canonical_id(cs)
        # Guard the astronomically unlikely key collision between two
        # genuinely different parcels rather than letting one overwrite the
        # other's history.
        base, n = pid, 2
        while pid in props:
            pid = f"{base}-{n}"
            n += 1

    result = {"property_id": pid, "is_new": is_new, "changes": [],
              "suggestions": suggestions, "match_reasons": matched_reasons,
              "price_change": None}

    # -- observation log (append-only) ------------------------------------
    obs = load_observations()
    obs.append({
        "property_id": pid,
        "observed_at": _now(),
        "source": source or cs.value("source") or "",
        "source_url": source_url or cs.value("source_url") or "",
        "claims": cs.to_dict(),
    })
    _write(OBSERVATIONS_PATH, obs)

    # -- property record --------------------------------------------------
    if is_new:
        prop = {
            "property_id": pid,
            "first_seen": _now(),
            "last_seen": _now(),
            "claims": cs.to_dict(),
            "sources": [],
            "status": "NEW",
            "human_notes": [],
            "site_visits": [],
            "documents_collected": [],
            "last_verified": None,
            "availability_checks": [],
            "observation_count": 1,
        }
        result["changes"].append("New property recorded.")
        # Seed the price timeline on the FIRST sighting. Without this the
        # opening price is never stored, and the first re-sighting seeds the
        # timeline with its own (already reduced) price — so a parcel first
        # seen at ₹36L and relisted at ₹30L records no drop at all. The bug
        # was invisible on any parcel seen three or more times, which is
        # exactly the case the demo data happened to cover.
        _record_price(pid, cs, None, _price_of(cs))
    else:
        prop = props[pid]
        merged = _claimset(prop)
        before_price = _price_of(merged)
        before_keys = set(merged.claims)

        merged.merge(cs)

        prop["claims"] = merged.to_dict()
        prop["last_seen"] = _now()
        prop["observation_count"] = int(prop.get("observation_count", 0)) + 1

        new_keys = set(merged.claims) - before_keys
        # raw_text churns on every re-scrape and is noise in a change list.
        new_keys.discard("raw_text")
        if new_keys:
            result["changes"].append(
                f"New information: {', '.join(sorted(new_keys)[:8])}")

        after_price = _price_of(merged)
        change = _record_price(pid, cs, before_price, after_price)
        if change:
            result["price_change"] = change
            result["changes"].append(change["summary"])
        if not result["changes"]:
            result["changes"].append("Re-seen with no new information.")

    # Source list, deduplicated by URL. Every place this parcel has appeared,
    # which is both an audit trail and a signal — a parcel on six portals for
    # eight months is a parcel the market has declined to buy.
    src_entry = {"source": source or cs.value("source") or "unspecified",
                 "url": source_url or cs.value("source_url") or "",
                 "seen": _now()}
    urls = {s.get("url") for s in prop.get("sources", []) if s.get("url")}
    names = {s.get("source") for s in prop.get("sources", [])}
    if (src_entry["url"] and src_entry["url"] not in urls) or \
       (not src_entry["url"] and src_entry["source"] not in names):
        prop.setdefault("sources", []).append(src_entry)
        if not is_new:
            result["changes"].append(f"Also now listed on {src_entry['source']}.")

    props[pid] = prop
    save_properties(props)
    return result


def _price_of(cs: ClaimSet):
    v = cs.value("price_per_acre") or cs.value("price_per_acre_stated")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _record_price(pid: str, cs: ClaimSet, before, after) -> dict | None:
    """Append to the price timeline when the asking price actually moved.

    The timeline is the asset here. A parcel whose ₹/acre has gone
    60L -> 52L -> 47L over nine months is telling you the seller's reserve is
    soft and roughly where it is — information no single listing contains,
    and the reason this system stores history instead of just re-scoring.
    """
    hist = load_price_history()
    entries = hist.get(pid, [])
    observed = _price_of(cs)
    if observed is None:
        return None

    if not entries:
        entries.append({"date": date.today().isoformat(), "price_per_acre": observed,
                        "source": cs.value("source") or "", "note": "first observation"})
        hist[pid] = entries
        _write(PRICE_HISTORY_PATH, hist)
        return None

    last = entries[-1]["price_per_acre"]
    if last and abs(observed - last) / last >= MIN_PRICE_CHANGE:
        entries.append({"date": date.today().isoformat(), "price_per_acre": observed,
                        "source": cs.value("source") or "", "note": ""})
        hist[pid] = entries
        _write(PRICE_HISTORY_PATH, hist)

        first = entries[0]["price_per_acre"]
        pct_from_last = (observed - last) / last * 100
        pct_from_first = (observed - first) / first * 100 if first else 0
        direction = "dropped" if observed < last else "increased"
        from findfarms.core.units import format_price
        return {
            "direction": "DOWN" if observed < last else "UP",
            "from": last, "to": observed,
            "pct_from_last": round(pct_from_last, 1),
            "pct_from_first": round(pct_from_first, 1),
            "summary": (f"Asking price {direction} {abs(pct_from_last):.0f}%: "
                        f"{format_price(last)}/acre → {format_price(observed)}/acre "
                        f"({pct_from_first:+.0f}% from first seen at "
                        f"{format_price(first)})"),
        }
    return None


def price_timeline(pid: str) -> list:
    return load_price_history().get(pid, [])


def days_on_market(prop: dict) -> int | None:
    """Days since this parcel was first discovered.

    Not days since it was listed — we cannot know that. It is a lower bound,
    and it is the negotiation-relevant number: a parcel we have watched for
    200 days has had 200 days of not selling at its asking price.
    """
    first = prop.get("first_seen")
    if not first:
        return None
    try:
        d = datetime.fromisoformat(first)
    except ValueError:
        return None
    return (datetime.now() - d).days


# ------------------------------------------------------ human workflow ----

def add_note(pid: str, text: str, author: str = "user") -> bool:
    props = load_properties()
    if pid not in props:
        return False
    props[pid].setdefault("human_notes", []).append(
        {"at": _now(), "author": author, "text": text})
    save_properties(props)
    return True


def set_status(pid: str, status: str, note: str = "") -> bool:
    """Move a property along the human workflow.

    The stages mirror the brief's pipeline: NEW -> SHORTLISTED -> CONTACTED
    -> DOCUMENTS_REQUESTED -> VISITED -> LAWYER_REVIEW -> NEGOTIATING ->
    ARCHIVED / REJECTED. Nothing in this system advances a property past
    SHORTLISTED on its own — every later stage requires a human to have
    actually done something in the physical world.
    """
    props = load_properties()
    if pid not in props:
        return False
    old = props[pid].get("status")
    props[pid]["status"] = status
    props[pid].setdefault("human_notes", []).append(
        {"at": _now(), "author": "workflow",
         "text": f"Status {old} → {status}" + (f": {note}" if note else "")})
    save_properties(props)
    return True


def record_verification(pid: str, field: str, value, source: str,
                        confidence: str = "VERIFIED", note: str = "") -> bool:
    """Overwrite a seller claim with something you actually confirmed.

    This is how a property graduates: you visit, you measure the borewell
    yield in April, you read the RTC — and the claim that was carrying 45%
    weight becomes evidence carrying 100%. Every score recomputes from the
    upgraded claim on the next read, which is the whole point of storing
    confidence alongside value rather than baking it into the score.
    """
    props = load_properties()
    if pid not in props:
        return False
    cs = _claimset(props[pid])
    cs.set(field, Claim(value=value, source=source, confidence=confidence,
                        note=note))
    props[pid]["claims"] = cs.to_dict()
    props[pid]["last_verified"] = _now()
    props[pid].setdefault("human_notes", []).append(
        {"at": _now(), "author": "verification",
         "text": f"{field} = {value} ({confidence}, source: {source})"})
    save_properties(props)
    return True


def record_availability_check(pid: str, still_available: bool, note: str = "",
                             checked_on: str = "") -> bool:
    """Record that you actually called and asked whether it is still for sale.

    Kept separate from every date the system infers, because it is the only
    one that establishes availability. Freshness bands are a guess from when a
    listing was last seen; this is someone answering the phone.
    """
    props = load_properties()
    if pid not in props:
        return False
    props[pid].setdefault("availability_checks", []).append({
        "date": checked_on or date.today().isoformat(),
        "available": bool(still_available), "note": note, "recorded_at": _now()})
    if not still_available:
        props[pid]["status"] = "ARCHIVED"
    props[pid].setdefault("human_notes", []).append(
        {"at": _now(), "author": "availability",
         "text": ("Confirmed still available" if still_available
                  else "Confirmed NO LONGER available")
                 + (f": {note}" if note else "")})
    save_properties(props)
    return True


def record_site_visit(pid: str, visited_on: str, observations: str,
                      verdict: str = "") -> bool:
    props = load_properties()
    if pid not in props:
        return False
    props[pid].setdefault("site_visits", []).append(
        {"date": visited_on, "observations": observations, "verdict": verdict,
         "recorded_at": _now()})
    save_properties(props)
    return True


# ------------------------------------------------------------- alerts ----

def load_alerts() -> list:
    return _read(ALERTS_PATH, [])


def already_alerted(pid: str, level: str) -> bool:
    """Whether this property already fired at this level.

    Suppression is per property *and* level, so a WATCH property that later
    becomes an ALERT still fires — the escalation is the news. A parcel
    re-alerting at the same level every scan is just noise that trains you to
    ignore the alerts.
    """
    return any(a.get("property_id") == pid and a.get("level") == level
               for a in load_alerts())


def log_alert(pid: str, level: str, summary: str) -> None:
    alerts = load_alerts()
    alerts.append({"property_id": pid, "level": level, "summary": summary,
                   "at": _now()})
    _write(ALERTS_PATH, alerts)
