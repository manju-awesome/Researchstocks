"""
motivation.py
=============
SELLER_MOTIVATION = NORMAL / POSSIBLY_MOTIVATED / HIGHLY_MOTIVATED / UNKNOWN

What this measures, precisely: **how much negotiating room the seller's own
published behaviour suggests.** Not their circumstances, not their finances,
not their family situation.

The brief draws this line and it is worth stating why it is drawn where it
is. "Family settlement" in an advert is a fact about the advert — the seller
chose to publish it, usually as an explanation of why the sale is genuine.
Reading it as "this family is in distress and can be pressured" is both an
invented inference about strangers and a bad negotiating model, because the
phrase appears in perfectly unhurried sales all the time. So this module
scores *published signals and observed market behaviour*, and the output is
phrased as negotiating room rather than as a diagnosis of anybody.

The strongest signals are not linguistic
----------------------------------------
Language is the weakest evidence here — "urgent sale" is often just copy. The
signals that actually predict negotiability come from the database, which is
the payoff for storing history:

  * **A recorded price reduction.** The seller has already demonstrated the
    asking price was not the real price. One cut usually means another.
  * **Time on market.** A parcel we have watched for 250 days has had 250
    days of the market declining to pay the asking price.
  * **Repeated relisting across portals.** Escalating distribution effort.

A listing full of urgent language that appeared last week scores below a
quiet listing that has sat for eight months and dropped once — which is the
correct ordering, and the opposite of what a text-only reading gives.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet
from findfarms.core.units import format_price

NORMAL = "NORMAL"
POSSIBLY_MOTIVATED = "POSSIBLY_MOTIVATED"
HIGHLY_MOTIVATED = "HIGHLY_MOTIVATED"
UNKNOWN = "UNKNOWN"

# Days on market past which the market's silence is itself a signal. Rural
# agricultural parcels move slowly, so this is generously long — 120 days is
# an ordinary marketing period here, not a stale listing.
STALE_DAYS = 180
VERY_STALE_DAYS = 365


def assess_motivation(cs: ClaimSet, prop: dict | None = None,
                      price_timeline: list | None = None) -> dict:
    """Score negotiating room from published signals and market behaviour."""
    prop = prop or {}
    timeline = price_timeline or []
    points = 0
    signals: list[str] = []
    evidence_kind = set()

    # -- behavioural: price movement (strongest) ----------------------------
    if len(timeline) >= 2:
        first = timeline[0].get("price_per_acre")
        last = timeline[-1].get("price_per_acre")
        drops = sum(1 for i in range(1, len(timeline))
                    if timeline[i].get("price_per_acre", 0) <
                    timeline[i - 1].get("price_per_acre", 0))
        if first and last and last < first:
            pct = (first - last) / first * 100
            points += 40 if pct >= 15 else 28 if pct >= 8 else 18
            evidence_kind.add("behavioural")
            signals.append(
                f"Asking price has come down {pct:.0f}% since first seen "
                f"({format_price(first)} → {format_price(last)} per acre)"
                + (f", across {drops} separate reductions" if drops > 1 else "")
                + ". The seller has already shown the list price was not the "
                  "real price.")
        elif first and last and last > first:
            points -= 15
            signals.append(
                f"Asking price has gone UP since first seen "
                f"({format_price(first)} → {format_price(last)} per acre). "
                f"Either the seller is not under pressure, or the earlier figure "
                f"was a mis-read — check which.")

    # -- behavioural: time on market ----------------------------------------
    days = None
    if prop.get("first_seen"):
        from findfarms.store.db import days_on_market
        days = days_on_market(prop)
    if days is not None:
        if days >= VERY_STALE_DAYS:
            points += 30
            evidence_kind.add("behavioural")
            signals.append(
                f"Tracked for {days} days without selling. Over a year of the "
                f"market declining to pay this price is the most reliable "
                f"negotiating signal available.")
        elif days >= STALE_DAYS:
            points += 18
            evidence_kind.add("behavioural")
            signals.append(f"Tracked for {days} days without selling — longer "
                           f"than an ordinary marketing period for this market.")

    # -- behavioural: distribution effort -----------------------------------
    n_sources = len(prop.get("sources", []) or [])
    if n_sources >= 4:
        points += 15
        evidence_kind.add("behavioural")
        signals.append(f"Listed across {n_sources} separate channels — a level of "
                       f"distribution effort that suggests the seller wants a "
                       f"transaction, not just an offer.")
    elif n_sources == 3:
        points += 8
        signals.append(f"Listed on {n_sources} channels.")

    obs = int(prop.get("observation_count", 0) or 0)
    if obs >= 6 and n_sources <= 2:
        points += 6
        signals.append(f"Re-posted {obs} times on few channels — repeated "
                       f"refreshing of the same listing.")

    # -- published language (weakest) ---------------------------------------
    hint = cs.get("motivation_level_hint")
    lang = cs.get("motivation_signals")
    if hint.known:
        evidence_kind.add("language")
        if hint.value == "HIGHLY_MOTIVATED":
            points += 20
            signals.append(
                f'Listing uses urgency wording ("{lang.value}"). Recorded because '
                f'the seller chose to publish it — but this phrasing is common '
                f'copy and is the weakest evidence here.')
        else:
            points += 10
            signals.append(
                f'Listing mentions "{lang.value}". Noted as published wording '
                f'only; it says nothing reliable about the seller\'s situation.')

    if cs.get("negotiable").known:
        c = cs.get("negotiable")
        if c.truthy():
            points += 8
            signals.append("Listing states the price is negotiable.")
        else:
            points -= 10
            signals.append("Listing states the price is fixed. Take it as an "
                           "opening position, not a fact, but do not count on room.")

    if cs.get("owner_direct").truthy():
        points += 5
        signals.append(
            "Owner-direct listing — negotiation is with the decision-maker, and "
            "there is no commission built into the asking price.")

    # -- verdict -------------------------------------------------------------
    if not signals:
        level = UNKNOWN
        rationale = ("Nothing published, and no history yet. Motivation becomes "
                     "assessable once this property has been tracked for a few "
                     "months — that is what the database is for.")
    elif points >= 45:
        level = HIGHLY_MOTIVATED
        rationale = "Multiple independent signals of substantial negotiating room."
    elif points >= 20:
        level = POSSIBLY_MOTIVATED
        rationale = "Some negotiating room suggested."
    elif points <= 0:
        level = NORMAL
        rationale = "No indication of negotiating room; some signals point the "\
                    "other way."
    else:
        level = NORMAL
        rationale = "Weak signals only — treat as an ordinary sale."

    if level in (HIGHLY_MOTIVATED, POSSIBLY_MOTIVATED) and \
            evidence_kind == {"language"}:
        rationale += (" Note: this rests entirely on advertising wording, with no "
                      "price history or time-on-market behind it. Wording is cheap; "
                      "re-check once there is a few months of history.")

    return {
        "level": level,
        "score": points,
        "signals": signals,
        "rationale": rationale,
        "days_tracked": days,
        "evidence_kinds": sorted(evidence_kind),
        "caveat": ("Measures negotiating room from published signals and market "
                   "behaviour only. It is deliberately not an inference about the "
                   "seller's circumstances, and should not be used as one — in a "
                   "negotiation as well as ethically, the market evidence is the "
                   "part that actually holds."),
    }
