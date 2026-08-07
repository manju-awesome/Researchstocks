"""
decision_engine.py
===================
A decision layer over the screener's results. The screener answers "which
stocks meet my criteria"; this answers "which of those deserve attention,
what kind of opportunity is it, and what would have to change".

This module is step one of that: the three scores everything else is built
on. It computes nothing about actions or tiers yet — those read these
scores, so they have to be right first.

    investment_score()   long-term company quality, 0-100
    swing_score()        short/intermediate setup quality, 0-100
    confluence()         0-10, how many INDEPENDENT factors agree

Nothing here replaces core/screener.py. Screening decides membership; this
ranks and characterises what came back.

The rule that shapes the whole file
-----------------------------------
A missing input must never quietly become a score. The obvious
implementations both lie: treating an absent field as 0 punishes a company
for a data gap, and skipping it while keeping the divisor does the same
thing more subtly. Assigning a neutral 50 invents a measurement.

So each score renormalises over the components it actually has, and returns
`coverage` (share of the intended weight that was measurable) plus the names
of what was missing. A score built from 40% of its inputs is not the same
claim as one built from 100%, and callers are expected to refuse
high-conviction labels below `MIN_COVERAGE`. This matters concretely here:
R:R is present for 207 of 545 library rows and breakout probability for 313,
so partial coverage is the common case, not an edge case.

Confluence counts independent confirmations, which is why it is not just a
sum of the other two. Quality and Moat both describe the business; RS rank
and being above the 200-day both describe trend. Counting each pair twice
would manufacture agreement out of one signal — the exact error the score
exists to detect.
"""

from __future__ import annotations

# A score computed from less than this share of its intended weight is
# reported but must not carry a high-conviction action.
MIN_COVERAGE = 0.60

INVESTMENT_BANDS = ((90, "Exceptional"), (80, "Strong"), (70, "Good"),
                    (60, "Average"), (0, "Weak"))
SWING_BANDS = ((90, "A+ Setup"), (80, "A Setup"), (70, "B Setup"),
               (60, "C Setup"), (0, "Avoid"))


def _f(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _band(score: float | None, bands) -> str | None:
    if score is None:
        return None
    for floor, label in bands:
        if score >= floor:
            return label
    return bands[-1][1]


def _scale(value: float, lo: float, hi: float) -> float:
    """Map a raw value onto 0-100, clamped. `lo`/`hi` are the range over
    which the metric is actually discriminating — beyond them, more is not
    meaningfully better."""
    if hi == lo:
        return 0.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _inverse(value: float, best: float, worst: float) -> float:
    """Lower-is-better metrics (valuation). Values at or below `best` score
    100; at or above `worst`, 0."""
    if worst == best:
        return 0.0
    return max(0.0, min(100.0, (worst - value) / (worst - best) * 100.0))


def _blend(parts: list[tuple[str, float, float | None]]) -> dict:
    """parts: [(name, weight, value_0_100_or_None)].

    Renormalises over the measurable components and reports how much of the
    intended weight that was. Returns score None when nothing is measurable
    — not 0, which would read as "bad" rather than "unknown".
    """
    total_weight = sum(w for _, w, _ in parts) or 1.0
    got_weight = 0.0
    acc = 0.0
    missing = []
    used = {}
    for name, weight, value in parts:
        if value is None:
            missing.append(name)
            continue
        acc += weight * value
        got_weight += weight
        used[name] = round(value, 1)
    if not got_weight:
        return {"score": None, "coverage": 0.0, "missing": missing,
                "components": {}}
    return {"score": int(round(acc / got_weight)),
            "coverage": round(got_weight / total_weight, 3),
            "missing": missing, "components": used}


# ─────────────────────────────────────────────────────────────────────────────
# INVESTMENT SCORE — is this a good company to own
# ─────────────────────────────────────────────────────────────────────────────
# Ranges are set where each metric stops discriminating. EPS growth tops out
# at 60% because the library's distribution runs to five figures on one-off
# comparisons — rewarding 21,000% over 60% would rank an accounting artifact
# above a real compounder. Forward P/E is scored between 10 and 45 and only
# for positive multiples: a negative P/E means no earnings, which is not
# cheap, so it scores 0 rather than off the top of the scale.

def investment_score(row: dict) -> dict:
    quality = _f(row.get("quality"))
    health = _f(row.get("health"))
    moat = _f(row.get("moat"))
    eps = _f(row.get("eps_growth"))
    rev = _f(row.get("revenue_growth"))
    pe = _f(row.get("forward_pe"))
    rs = _f(row.get("rs_rank"))
    above200 = row.get("above_200ma")

    parts = [
        ("Quality", 25, quality),                       # already 0-100
        ("Health", 15, health),
        ("Moat", 15, None if moat is None else _scale(moat, 0, 4)),
        ("EPS growth", 15, None if eps is None else _scale(eps, 0, 60)),
        ("Revenue growth", 10, None if rev is None else _scale(rev, 0, 30)),
        ("Valuation", 10, None if pe is None or pe <= 0
                          else _inverse(pe, 10, 45)),
        ("RS", 5, rs),
        ("Technical", 5, None if above200 is None else (100.0 if above200 else 0.0)),
    ]
    out = _blend(parts)
    out["label"] = _band(out["score"], INVESTMENT_BANDS)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SWING SCORE — is this a good trade right now
# ─────────────────────────────────────────────────────────────────────────────
# Deliberately shares no fundamental input with investment_score. A great
# business with no setup must not score well here; that conflation is what
# makes a single blended score useless for timing.

def swing_score(row: dict) -> dict:
    existing = _f(row.get("swing_score"))
    rs = _f(row.get("rs_rank"))
    breakout = _f(row.get("breakout_probability"))
    rr = _f(row.get("rr"))
    rvol = _f(row.get("rvol"))
    above200 = row.get("above_200ma")
    above50 = row.get("above_50ma")
    dist8 = _f(row.get("abs_vs_8ema"))

    # Trend: both moving averages, since one alone is a weaker statement.
    trend = None
    if above200 is not None or above50 is not None:
        legs = [x for x in (above200, above50) if x is not None]
        trend = sum(100.0 if x else 0.0 for x in legs) / len(legs)

    # Setup quality: the scan's own swing score when present — it already
    # encodes pattern work this module has no access to. Falls back to
    # proximity to the 8 EMA, which is the entry most of these setups use.
    setup = existing if existing is not None else (
        None if dist8 is None else _inverse(abs(dist8), 0.5, 8.0))

    parts = [
        ("Technical trend", 25, trend),
        ("RS", 20, rs),
        ("Setup quality", 20, setup),
        ("Breakout probability", 15, breakout),
        ("Momentum", 10, None if rvol is None else _scale(rvol, 0.8, 2.5)),
        ("Risk/reward", 10, None if rr is None else _scale(rr, 1.0, 4.0)),
    ]
    out = _blend(parts)
    out["label"] = _band(out["score"], SWING_BANDS)
    out["used_scan_swing"] = existing is not None
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CONFLUENCE — how many INDEPENDENT things agree
# ─────────────────────────────────────────────────────────────────────────────
# Each check below is a different kind of evidence. Correlated signals are
# deliberately collapsed into one check rather than counted separately:
# quality and moat are one business-strength check, RS and above-200MA are
# one trend check. Counting them twice would turn a single signal into
# apparent agreement, which is precisely what this score exists to catch.
_CONFLUENCE_CHECKS = (
    "Fundamentals", "Business strength", "Relative strength", "Long-term trend",
    "Intermediate trend", "Near entry", "Setup present", "Volume confirmation",
    "Risk/reward", "Market regime",
)


def confluence(row: dict, regime_favorable: bool | None = None) -> dict:
    """0-10. `regime_favorable` comes from the caller (market regime or
    benchmark leadership); None means unknown and simply isn't counted."""
    hits, misses, unknown = [], [], []

    def check(name, value):
        if value is None:
            unknown.append(name)
        elif value:
            hits.append(name)
        else:
            misses.append(name)

    quality = _f(row.get("quality"))
    health = _f(row.get("health"))
    moat = _f(row.get("moat"))
    eps = _f(row.get("eps_growth"))
    rs = _f(row.get("rs_rank"))
    rr = _f(row.get("rr"))
    rvol = _f(row.get("rvol"))
    breakout = _f(row.get("breakout_probability"))
    dist8 = _f(row.get("abs_vs_8ema"))

    check("Fundamentals", None if (eps is None and health is None) else
          ((eps or 0) >= 15 and (health or 0) >= 60))
    # Quality and Moat describe the same thing — one check, not two.
    check("Business strength", None if (quality is None and moat is None) else
          ((quality or 0) >= 70 or (moat or 0) >= 3))
    check("Relative strength", None if rs is None else rs >= 70)
    check("Long-term trend", row.get("above_200ma"))
    check("Intermediate trend", row.get("above_50ma"))
    check("Near entry", None if (dist8 is None and row.get("in_buy_zone") is None)
          else (row.get("in_buy_zone") is True or (dist8 is not None and dist8 <= 3)))
    check("Setup present", None if (row.get("category") is None and breakout is None)
          else (str(row.get("category") or "") in
                ("Momentum", "Momentum-Pullback", "VCP Setup", "Turnaround")
                or (breakout or 0) >= 70))
    check("Volume confirmation", None if rvol is None else rvol >= 1.2)
    check("Risk/reward", None if rr is None else rr >= 2.0)
    check("Market regime", regime_favorable)

    return {"score": len(hits), "max": len(_CONFLUENCE_CHECKS),
            "hits": hits, "misses": misses, "unknown": unknown,
            # A 7/10 with three unknowns is a weaker claim than a clean 7/10.
            "measured": len(hits) + len(misses)}


def score_row(row: dict, regime_favorable: bool | None = None) -> dict:
    """All three scores for one screener result row."""
    inv = investment_score(row)
    swing = swing_score(row)
    conf = confluence(row, regime_favorable)
    return {
        "ticker": row.get("ticker"),
        "investment": inv,
        "swing": swing,
        "confluence": conf,
        # Surfaced so callers don't have to re-derive the rule that decides
        # whether a high-conviction action is even permissible.
        "reliable": (inv["coverage"] >= MIN_COVERAGE
                     and swing["coverage"] >= MIN_COVERAGE),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ACTIONS — exactly one primary action per stock
# ─────────────────────────────────────────────────────────────────────────────
# Thresholds are set from the library's real distribution, not from round
# numbers. Swing tops out at 83 and confluence at 9/10, so the natural-looking
# ">= 85 and >= 8/10" gate for BUY NOW is empty by construction — not because
# nothing qualifies but because the scale doesn't reach there. The cutoffs
# below sit at roughly the 97th/90th percentile of what the scores actually
# produce, which is what "exceptional" has to mean if the label is to name
# anything. Moving the goalposts to a rounder number would give a screen that
# reads as rigorous and returns nothing.
BUY_NOW_SCORE = 78
BUY_NOW_CONFLUENCE = 7
PULLBACK_SCORE = 72
PULLBACK_CONFLUENCE = 6
WATCH_SCORE = 65
MIN_RR = 2.0

ACTIONS = ("BUY NOW", "BUY ZONE", "BUY ON PULLBACK", "BREAKOUT ENTRY",
           "WATCH", "WAIT", "SPECULATIVE", "AVOID")

ACTION_ICONS = {"BUY NOW": "🟢", "BUY ZONE": "🟢", "BUY ON PULLBACK": "🟢",
                "BREAKOUT ENTRY": "🚀", "WATCH": "🔵", "WAIT": "⏳",
                "SPECULATIVE": "🟡", "AVOID": "🔴"}

# Earnings proximity. An imminent report is a gap risk no setup quality
# offsets, so it downgrades rather than scoring.
EARNINGS_BANDS = ((2, "CRITICAL"), (7, "HIGH"), (14, "MEDIUM"))


def earnings_risk(days) -> str:
    d = _f(days)
    if d is None:
        return "UNKNOWN"
    if d < 0:
        return "LOW"
    for limit, label in EARNINGS_BANDS:
        if d <= limit:
            return label
    return "LOW"


STRATEGIES = ("LONGTERM", "SWING", "BALANCED")


def _primary_score(inv, swing, strategy: str) -> int:
    """Which score gates the action.

    Using max() here — the obvious shortcut — silently undoes the whole
    point of scoring investment and swing separately: it lets a strong chart
    on a weak company, or a strong company with no setup, both reach BUY
    NOW. Neither is a buy for the same reason, and calling them the same
    thing hides which one you are actually taking.

    LONGTERM gates on the company, SWING on the setup, and BALANCED demands
    both — the lower of the two, which is the honest reading when no
    strategy has been declared.
    """
    inv, swing = inv or 0, swing or 0
    if strategy == "LONGTERM":
        return inv
    if strategy == "SWING":
        return swing
    return min(inv, swing)


def decide(row: dict, scores: dict | None = None,
           regime: str = "FAVORABLE",
           strategy: str = "BALANCED",
           earnings_strategy: bool = False) -> dict:
    """One primary action for one row, with the reasoning that produced it.

    `regime` (FAVORABLE / SELECTIVE / DEFENSIVE) only changes how selective
    the gates are — it is not a market prediction. `earnings_strategy=True`
    is the explicit opt-in that stops an imminent report downgrading a buy.
    """
    s = scores or score_row(row)
    inv = s["investment"]["score"]
    swing = s["swing"]["score"]
    conf = s["confluence"]["score"]
    best = _primary_score(inv, swing, strategy)

    rr = _f(row.get("rr"))
    quality = _f(row.get("quality"))
    health = _f(row.get("health"))
    # SIGNED, not absolute. abs_vs_8ema exists for "within X% of" screens
    # and cannot tell above from below — reading it here reported WDC, which
    # sits 11% UNDER its 8 EMA, as "11.0% above it now" and offered a
    # pullback that had already happened. Direction is the point of this
    # branch: extended above is a chase, far below is weakness.
    pct8 = _f(row.get("pct_vs_8ema"))
    dist8 = None if pct8 is None else abs(pct8)
    above200 = row.get("above_200ma")
    in_zone = row.get("in_buy_zone") is True
    breakout = _f(row.get("breakout_probability"))
    rs = _f(row.get("rs_rank"))
    rvol = _f(row.get("rvol"))
    er = earnings_risk(row.get("days_to_earnings"))

    # Regime tightens the gates rather than vetoing anything outright.
    bump = {"FAVORABLE": 0, "SELECTIVE": 3, "DEFENSIVE": 6}.get(regime, 0)
    buy_score = BUY_NOW_SCORE + bump
    buy_conf = BUY_NOW_CONFLUENCE + (1 if regime == "DEFENSIVE" else 0)

    blockers, triggers = [], []

    # ── disqualifiers first ──────────────────────────────────────────────
    if not s["reliable"]:
        return _verdict("AVOID", row, s, er,
                        why=["Insufficient data to judge this setup"],
                        blockers=["Key inputs missing — "
                                  + ", ".join(sorted(set(
                                      s["investment"]["missing"]
                                      + s["swing"]["missing"]))[:4])],
                        triggers=["Run a scan so the missing fields populate"])
    if above200 is False and (inv or 0) < 60:
        blockers.append("Below the 200-day with weak fundamentals")
    if health is not None and health < 30:
        blockers.append(f"Balance sheet weak (health {health:.0f})")
    if rr is not None and rr < 1.0:
        blockers.append(f"R:R {rr:.1f} — risk exceeds reward")
    if blockers:
        return _verdict("AVOID", row, s, er, blockers=blockers)

    # Attractive but fragile: never mixed in with high-conviction buys.
    speculative = ((quality is not None and quality < 45)
                   or (health is not None and health < 45))

    # ── the positive ladder ──────────────────────────────────────────────
    # Earnings gate. This used to apply only when `best >= WATCH_SCORE`,
    # which meant a stock scoring BELOW the watch threshold skipped it and
    # could still reach a buy further down: MNST reported earnings the same
    # day and came out "BUY ZONE" under Swing because its swing score of 56
    # was too low to trip the guard. An imminent report is gap risk
    # regardless of how the setup scores, so it now blocks every buy action
    # rather than only the high-scoring ones.
    earnings_blocked = er in ("HIGH", "CRITICAL") and not earnings_strategy
    if earnings_blocked:
        days = _f(row.get("days_to_earnings"))
        when = ("today" if days is not None and days <= 0
                else f"in {days:.0f} day{'s' if days != 1 else ''}"
                if days is not None else "imminent")
        if best >= WATCH_SCORE:
            return _verdict("WAIT", row, s, er,
                            blockers=[f"Earnings {when}"],
                            triggers=["Re-assess once the report is out"])

    if speculative and best >= WATCH_SCORE:
        return _verdict("SPECULATIVE", row, s, er,
                        blockers=["Quality or balance sheet is weak — size "
                                  "this as a speculation, not a core position"])

    if not earnings_blocked \
            and (swing or 0) >= buy_score and (rs or 0) >= 80 \
            and (breakout or 0) >= 70 \
            and (rvol or 0) >= 1.2 and (rr or 0) >= MIN_RR:
        return _verdict("BREAKOUT ENTRY", row, s, er)

    if not earnings_blocked and best >= buy_score and conf >= buy_conf \
            and (rr or 0) >= MIN_RR \
            and (in_zone or (dist8 is not None and dist8 <= 3)):
        return _verdict("BUY NOW", row, s, er)

    if not earnings_blocked and in_zone and best >= PULLBACK_SCORE \
            and (quality or 0) >= 70 and (health or 0) >= 60:
        return _verdict("BUY ZONE", row, s, er)

    if not earnings_blocked and best >= PULLBACK_SCORE \
            and conf >= PULLBACK_CONFLUENCE:
        if pct8 is not None and pct8 > 3:
            triggers.append(f"Pull back toward the 8/21 EMA "
                            f"(now {pct8:.1f}% above it)")
            return _verdict("BUY ON PULLBACK", row, s, er, triggers=triggers)
        if pct8 is not None and pct8 < -6:
            # Well under the short-term average is not a pullback waiting to
            # be bought — the trend has to turn back up first.
            triggers.append(f"Reclaim the 8 EMA "
                            f"(now {abs(pct8):.1f}% below it)")
            return _verdict("WATCH", row, s, er, triggers=triggers)
        if rr is not None and rr < MIN_RR:
            triggers.append(f"R:R improves above {MIN_RR:.0f} (now {rr:.1f})")
            return _verdict("WAIT", row, s, er,
                            blockers=[f"R:R only {rr:.1f}"], triggers=triggers)
        return _verdict("BUY ON PULLBACK", row, s, er, triggers=triggers)

    if best >= WATCH_SCORE:
        if breakout is not None and breakout >= 70 and (rvol or 0) < 1.2:
            triggers.append("Breakout confirms on above-average volume")
        if pct8 is not None and abs(pct8) > 3:
            triggers.append(
                f"Price returns to the 8 EMA "
                f"({abs(pct8):.1f}% {'above' if pct8 > 0 else 'below'} it now)")
        if rr is not None and rr < MIN_RR:
            triggers.append(f"R:R improves above {MIN_RR:.0f} (now {rr:.1f})")
        if not in_zone and row.get("buy_zone_label"):
            triggers.append("Price enters the buy zone")
        return _verdict("WATCH", row, s, er, triggers=triggers or
                        ["A valid entry appears"])

    return _verdict("AVOID", row, s, er,
                    blockers=[f"Scores below the watch threshold "
                              f"(best {best})"])


def _verdict(action, row, scores, er, why=None, blockers=None, triggers=None):
    """Assemble the audit alongside the action — §9/§22: never a score
    without the reasoning that produced it."""
    conf = scores["confluence"]
    positives = why or [f"{n}" for n in conf["hits"]][:6]
    missing = conf["misses"][:4]
    unknown = sorted(set(scores["investment"]["missing"]
                         + scores["swing"]["missing"]))
    risks = list(blockers or [])
    if er in ("HIGH", "CRITICAL") and not any("Earnings" in r for r in risks):
        risks.append(f"Earnings risk {er}")
    if row.get("recovered"):
        risks.append(f"Data recovered from snapshot, as of "
                     f"{row.get('data_as_of') or 'an earlier scan'}")
    return {
        "ticker": row.get("ticker"),
        "action": action,
        "icon": ACTION_ICONS.get(action, ""),
        "investment": scores["investment"]["score"],
        "swing": scores["swing"]["score"],
        "confluence": conf["score"],
        "reliable": scores["reliable"],
        "earnings_risk": er,
        "why": positives,
        "missing": missing,
        "unknown_fields": unknown,
        "risks": risks,
        "triggers": triggers or [],
    }
