"""
ai_sentiment.py
================
Scoring for the AI Sentiment dashboard — turns the raw fetches from
scanners.ai_pulse (tier snapshots, yield/DXY/SOXX, NVDA VWAP) plus
scanners.market_movers.market_pulse() (VIX, SPY/QQQ, sector ETFs, econ
events) into the user's five scanner ideas: Risk Score, Rotation Detection,
AI Health Index, Macro Event Filter, and a composite AI Market Sentiment
Score. Pure functions, no network — mirrors core/market_regime.py's
compute_*(pulse=...) -> {score, drivers, label} pattern so it's unit
testable with synthetic fixtures (see tests/test_ai_sentiment.py).

Risk Score
----------
Implements the indicator table as given: yield/DXY/VIX/SOXX/Nasdaq-vs-SPY/
NVDA-vs-VWAP/breadth, each worth the listed points. NOTE: that table sums to
a max of +4 (breadth +2, yield-falls +2) and a min of -10 (all six negative
rows firing at once) — not the +8/-8 used in the illustrative example, which
appears aspirational rather than derived from the table. Bands below are
scaled to the table's real achievable range rather than the example's.

AI Market Sentiment Score (0-100)
----------------------------------
composite = 0.5 * ai_health_index
          + 0.3 * risk_component      (risk score rescaled -10..+4 -> 0..100)
          + 0.2 * rotation_component  (Risk-On=100 / Mixed=50 / Risk-Off=0)
minus a 15-point penalty when all three AI tiers are red while the broader
market (SPY) is flat — the user's explicit "AI-specific rotation, not a
broad sell-off" signal. Bands (the user's own): >70 Aggressive, 40-70
Selective, <40 avoid new AI longs (oversold-rebound only).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

MACRO_KEYWORDS = (
    "cpi", "ppi", "nonfarm", "payroll", "fomc", "fed ", "fed:", "treasury",
    "rate decision", "jobs report", "pce", "gdp",
)

DEFENSIVE_SECTORS = ["Utilities", "Staples", "Health"]
GROWTH_SECTORS    = ["Semis", "Software", "Industr", "Financials"]


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────────────────────────────────────────
# 1. RISK SCORE
# ─────────────────────────────────────────────────────────────────────────────

def _risk_label(score: int) -> str:
    if score >= 3:  return "Aggressive buying"
    if score >= 1:  return "Selective buying"
    if score == 0:  return "Neutral"
    if score >= -4: return "Reduce position size"
    return "Defensive"


def compute_risk_score(pulse_extra: dict, pulse: dict | None = None) -> dict:
    """Never raises; missing inputs simply don't contribute to the score."""
    pulse = pulse or {}
    score, drivers = 0, []

    yield_info = pulse_extra.get("yield") or {}
    bps = yield_info.get("change_bps")
    if bps is not None:
        if bps > 5:
            score -= 2; drivers.append(f"10Y yield +{bps}bp -2")
        elif bps < -5:
            score += 2; drivers.append(f"10Y yield {bps}bp (falling) +2")
        else:
            drivers.append(f"10Y yield {bps:+d}bp +0")

    dxy = pulse_extra.get("dxy") or {}
    dxy_chg = dxy.get("change_pct")
    if dxy_chg is not None:
        if dxy_chg > 0.5:
            score -= 1; drivers.append(f"DXY {dxy_chg:+.2f}% -1")
        else:
            drivers.append(f"DXY {dxy_chg:+.2f}% +0")

    vix = pulse.get("vix") or {}
    vix_chg_pct = vix.get("change_pct")
    if vix_chg_pct is not None:
        if vix_chg_pct > 5:
            score -= 2; drivers.append(f"VIX {vix_chg_pct:+.1f}% -2")
        else:
            drivers.append(f"VIX {vix_chg_pct:+.1f}% +0")

    soxx = pulse_extra.get("soxx") or {}
    above_soxx_20ma = soxx.get("above_20ma")
    if above_soxx_20ma is not None:
        if not above_soxx_20ma:
            score -= 2; drivers.append("SOXX below 20DMA -2")
        else:
            drivers.append("SOXX above 20DMA +0")

    spy_chg = ((pulse.get("spy") or {}).get("day_chg_pct"))
    qqq_chg = ((pulse.get("qqq") or {}).get("day_chg_pct"))
    if spy_chg is not None and qqq_chg is not None:
        if qqq_chg < spy_chg:
            score -= 1; drivers.append(f"Nasdaq underperforms SPY ({qqq_chg:+.2f}% vs {spy_chg:+.2f}%) -1")
        else:
            drivers.append(f"Nasdaq vs SPY {qqq_chg:+.2f}% vs {spy_chg:+.2f}% +0")

    nvda_vwap = pulse_extra.get("nvda_above_vwap")
    if nvda_vwap is not None:
        if not nvda_vwap:
            score -= 2; drivers.append("NVDA below VWAP -2")
        else:
            drivers.append("NVDA above VWAP +0")

    basket = pulse_extra.get("basket") or []
    scored = [b for b in basket if b.get("day_chg_pct") is not None]
    if scored:
        pct_green = sum(1 for b in scored if b["day_chg_pct"] > 0) / len(scored) * 100
        if pct_green > 60:
            score += 2; drivers.append(f"AI basket breadth {pct_green:.0f}% green +2")
        else:
            drivers.append(f"AI basket breadth {pct_green:.0f}% green +0")

    return {"score": score, "label": _risk_label(score), "drivers": drivers}


# ─────────────────────────────────────────────────────────────────────────────
# 2. ROTATION DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def compute_rotation(sectors: list[dict]) -> dict:
    """Classifies sector-ETF % changes (from market_pulse()["sectors"]) into
    Risk-On / Risk-Off / Mixed using the user's two patterns: defensive
    sectors up + semis down = risk-off; semis/software/industrials/
    financials all up = risk-on."""
    by_label = {s["label"]: s for s in (sectors or []) if s.get("chg_pct") is not None}

    def_up = sum(1 for l in DEFENSIVE_SECTORS if l in by_label and by_label[l]["chg_pct"] > 0)
    growth_up = sum(1 for l in GROWTH_SECTORS if l in by_label and by_label[l]["chg_pct"] > 0)
    semis = by_label.get("Semis")
    semis_down = semis is not None and semis["chg_pct"] < 0

    drivers = [f"{l} {by_label[l]['chg_pct']:+.1f}%" for l in DEFENSIVE_SECTORS + GROWTH_SECTORS
               if l in by_label]

    if not by_label:
        state = "Unknown"
    elif def_up >= 2 and semis_down:
        state = "Risk-Off"
    elif growth_up >= 3:
        state = "Risk-On"
    else:
        state = "Mixed"

    return {"state": state, "defensive_up": def_up, "growth_up": growth_up,
            "drivers": drivers}


# ─────────────────────────────────────────────────────────────────────────────
# 3. AI HEALTH INDEX
# ─────────────────────────────────────────────────────────────────────────────

def _health_label(index: float) -> str:
    if index > 80: return "Strong AI trend"
    if index > 60: return "Healthy"
    if index > 40: return "Mixed"
    if index > 20: return "Weak"
    return "Broad AI correction"


def compute_ai_health(basket_snapshots: list[dict]) -> dict:
    """% above 20 EMA, avg RSI, avg daily return, advance/decline ratio for
    the equal-weight AI basket, combined into a 0-100 index (average of four
    0-100-normalized sub-scores)."""
    snaps = [s for s in (basket_snapshots or []) if s]
    if not snaps:
        return {"index": None, "label": "No data", "pct_above_20ema": None,
                "avg_rsi": None, "avg_daily_return_pct": None,
                "advancers": 0, "decliners": 0, "adv_decl_ratio": None}

    with_ema = [s for s in snaps if s.get("above_20ema") is not None]
    pct_above_20ema = (sum(1 for s in with_ema if s["above_20ema"]) / len(with_ema) * 100
                        if with_ema else None)

    rsis = [s["rsi_14"] for s in snaps if s.get("rsi_14") is not None]
    avg_rsi = sum(rsis) / len(rsis) if rsis else None

    rets = [s["day_chg_pct"] for s in snaps if s.get("day_chg_pct") is not None]
    avg_ret = sum(rets) / len(rets) if rets else None
    advancers = sum(1 for r in rets if r > 0)
    decliners = sum(1 for r in rets if r < 0)
    adv_decl_ratio = round(advancers / decliners, 2) if decliners else (float(advancers) or None)
    pct_advancers = advancers / len(rets) * 100 if rets else None

    sub_scores = []
    if pct_above_20ema is not None: sub_scores.append(pct_above_20ema)
    if avg_rsi is not None:         sub_scores.append(avg_rsi)
    if pct_advancers is not None:   sub_scores.append(pct_advancers)
    if avg_ret is not None:         sub_scores.append(_clamp(50 + avg_ret * 10))

    index = round(sum(sub_scores) / len(sub_scores), 1) if sub_scores else None

    return {
        "index": index, "label": _health_label(index) if index is not None else "No data",
        "pct_above_20ema": round(pct_above_20ema, 1) if pct_above_20ema is not None else None,
        "avg_rsi": round(avg_rsi, 1) if avg_rsi is not None else None,
        "avg_daily_return_pct": round(avg_ret, 2) if avg_ret is not None else None,
        "advancers": advancers, "decliners": decliners,
        "adv_decl_ratio": adv_decl_ratio,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. MACRO EVENT FILTER
# ─────────────────────────────────────────────────────────────────────────────

def compute_macro_caution(econ_events: list[dict], now: datetime | None = None) -> dict:
    """Flags CPI/PPI/Jobs/FOMC/Treasury-auction-style events within the next
    48h (these move yields first, which ripples into AI names)."""
    now = now or datetime.now(ET)
    upcoming = []
    for ev in econ_events or []:
        when = ev.get("when")
        if when is None:
            continue
        title = (ev.get("title") or "").lower()
        hrs = (when - now).total_seconds() / 3600
        if 0 <= hrs <= 48 and any(k in title for k in MACRO_KEYWORDS):
            upcoming.append(ev)

    note = (f"{len(upcoming)} high-impact macro release(s) within 48h — "
            f"expect yield/vol swings, be more cautious on new entries"
            if upcoming else "No major macro releases in the next 48h")
    return {"caution": bool(upcoming), "events": upcoming, "note": note}


# ─────────────────────────────────────────────────────────────────────────────
# TIER STATUS (Leadership / Networking / Power)
# ─────────────────────────────────────────────────────────────────────────────

def compute_tier_status(snapshots: list[dict]) -> dict:
    scored = [s for s in (snapshots or []) if s.get("day_chg_pct") is not None]
    green = sum(1 for s in scored if s["day_chg_pct"] > 0)
    red = sum(1 for s in scored if s["day_chg_pct"] < 0)
    total = len(scored)
    return {"green": green, "red": red, "total": total,
            "all_red": total > 0 and red == total}


# ─────────────────────────────────────────────────────────────────────────────
# 5. COMPOSITE AI MARKET SENTIMENT SCORE
# ─────────────────────────────────────────────────────────────────────────────

ROTATION_COMPONENT = {"Risk-On": 100, "Mixed": 50, "Risk-Off": 0, "Unknown": 50}


def _sentiment_label(score: int) -> str:
    if score > 70: return "Aggressive — full risk budget on AI longs"
    if score >= 40: return "Selective — A-grade setups only"
    return "Defensive — avoid new AI longs (oversold-rebound only)"


def compute_ai_sentiment(risk: dict, rotation: dict, ai_health: dict,
                         tier_statuses: list[dict], market_flat: bool) -> dict:
    risk_component = _clamp(50 + risk["score"] * 8)
    rotation_component = ROTATION_COMPONENT.get(rotation["state"], 50)
    ai_health_index = ai_health.get("index")
    ai_health_component = ai_health_index if ai_health_index is not None else 50

    composite = (0.5 * ai_health_component
                + 0.3 * risk_component
                + 0.2 * rotation_component)

    all_tiers_red = bool(tier_statuses) and all(t.get("all_red") for t in tier_statuses)
    ai_specific_rotation = all_tiers_red and market_flat
    if ai_specific_rotation:
        composite -= 15

    composite = round(_clamp(composite))
    return {
        "score": composite, "label": _sentiment_label(composite),
        "ai_specific_rotation": ai_specific_rotation,
        "components": {"ai_health": ai_health_component, "risk": round(risk_component, 1),
                       "rotation": rotation_component},
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_events(events: list[dict]) -> list[dict]:
    out = []
    for e in events or []:
        when = e.get("when")
        out.append({**e, "when": when.strftime("%a %m/%d %H:%M ET") if hasattr(when, "strftime") else when})
    return out


def build_snapshot(pulse_extra: dict, pulse: dict | None = None) -> dict:
    """Orchestrates all compute_* functions into one JSON-serializable dict —
    the AI Sentiment page reads this straight from data/output/ai_sentiment.json,
    same shape convention as reporting/dashboard.py::build_snapshot."""
    pulse = pulse or {}

    risk = compute_risk_score(pulse_extra, pulse)
    rotation = compute_rotation(pulse.get("sectors") or [])
    ai_health = compute_ai_health(pulse_extra.get("basket") or [])
    macro = compute_macro_caution(pulse.get("econ_events") or [])

    tier1_status = compute_tier_status(pulse_extra.get("tier1") or [])
    tier2_status = compute_tier_status(pulse_extra.get("tier2") or [])
    tier3_status = compute_tier_status(pulse_extra.get("tier3") or [])

    spy_chg = (pulse.get("spy") or {}).get("day_chg_pct")
    market_flat = spy_chg is not None and abs(spy_chg) < 0.3

    sentiment = compute_ai_sentiment(
        risk, rotation, ai_health, [tier1_status, tier2_status, tier3_status], market_flat)

    return {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET"),
        "sentiment": sentiment,
        "risk": risk,
        "rotation": rotation,
        "ai_health": ai_health,
        "macro": {**macro, "events": _fmt_events(macro["events"])},
        "tiers": {
            "tier1": {"tickers": pulse_extra.get("tier1") or [], "status": tier1_status},
            "tier2": {"tickers": pulse_extra.get("tier2") or [], "status": tier2_status},
            "tier3": {"tickers": pulse_extra.get("tier3") or [], "status": tier3_status},
        },
        "all_ai": pulse_extra.get("all_ai") or [],
        "soxx": pulse_extra.get("soxx"),
        "yield": pulse_extra.get("yield"),
        "dxy": pulse_extra.get("dxy"),
        "nvda_above_vwap": pulse_extra.get("nvda_above_vwap"),
        "relative_strength": pulse_extra.get("relative_strength") or {},
        "sectors": pulse.get("sectors") or [],
        "vix": pulse.get("vix") or {},
        "market_flat": market_flat,
    }
