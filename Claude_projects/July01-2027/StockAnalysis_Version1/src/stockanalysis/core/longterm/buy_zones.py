"""
buy_zones.py — where a price becomes worth owning, not merely worth watching
=============================================================================
Valuation decides WHETHER to buy. Technical support decides WHEN. This module
computes the two independently and reports a buy zone only where they
overlap — which, for most of a quality library at most times, is nowhere.

The first version of this module had it backwards. It built bands from the
tracked support levels and then annotated each with a valuation check, which
produced output that contradicted itself:

    Preferred $386-395 — price is inside this band now
    ✗ Valuation requires 51% growth here vs 18% delivered
    No band qualifies: even the deepest tracked support is an expensive price

Both statements were true and they should never have appeared together,
because "Preferred" was never a claim about the price being worth paying — it
only ever meant "the 50 MA is here". Support existing is not a reason to buy;
it is a reason the price might pause. So the ladder is now built the other
way round:

    1. QUALITY      the business clears the tier floor              (engine)
    2. VALUATION     what the model says the cash flows are worth
    3. EXPECTED RETURN  what buying at a given price would earn
    4. FUNDAMENTAL ZONE  the prices where that return clears the hurdle
    5. TECHNICAL ZONE    where support actually sits
    6. INVESTMENT ZONE   the intersection — often empty, and that is a result

Three outputs, deliberately not merged:

    technical      pullback zones. Named for their level, never for their
                   desirability. "50 MA $386-395" claims only that the 50 MA
                   is there.
    fundamental    the price ladder from expected return: Fair, Attractive,
                   Exceptional, each a price rather than an adjective.
    investment     the overlap, tiered Aggressive / Preferred / Excellent.
                   Empty when the two curves do not meet.

What the expected-return figure assumes
---------------------------------------
Two things, and both are stated everywhere the number is shown.

First, that the business compounds at the conservative leg of what it has
delivered — the SLOWER of free-cash-flow and revenue growth, capped (see
PROJECTION_CEILING_PCT). Not the rate the valuation band credits: that one
takes the faster leg for a different and equally deliberate reason.

Second, that the market eventually pays this model's value for the company.
That is the strong one. A business priced above this model for a decade may
simply stay there, and no part of this can tell you whether it will.

Which makes every figure here a hurdle test — "would this price clear my
bar IF those hold" — and never a forecast.
"""

from __future__ import annotations

import math

from stockanalysis.core.longterm import valuation as V
from stockanalysis.core.longterm._common import f

# ─────────────────────────────────────────────────────────────────────────────
# TECHNICAL — where support is. Says nothing about whether to buy.
# ─────────────────────────────────────────────────────────────────────────────
# (key, label, anchor zones, zones that may join if they sit close enough).
# Labelled by the level, not by a verdict: naming the 50 MA band "Preferred"
# was the original sin this module was rewritten to undo.
TECHNICAL_ZONES = (
    ("ema", "8 / 21 EMA", ("EMA",), ()),
    ("50ma", "50 MA", ("50MA",), ("BREAKOUT",)),
    ("200ma", "200 MA", ("200MA",), ()),
)

MIN_BAND_ATR = 0.5
MAX_BAND_ATR = 2.0
MAX_BAND_PCT = 10.0
FALLBACK_BAND_PCT = 1.5
MIN_DOWNSIDE_PCT = 0.5

# ─────────────────────────────────────────────────────────────────────────────
# FUNDAMENTAL — what return a price would earn
# ─────────────────────────────────────────────────────────────────────────────
# Minimum expected 5-year CAGR by quality tier. A better business earns a
# higher hurdle rather than a lower one: paying up for quality is only
# defensible if the quality is what delivers the return, so the tier that
# justifies the premium is the tier asked to clear the taller bar.
RETURN_HURDLES = ((90, 15.0), (80, 12.0), (70, 10.0), (0, 10.0))

# Distance from the hurdle that defines each rung, in percentage points.
FAIR_BELOW_HURDLE = 3.0
EXCEPTIONAL_ABOVE_HURDLE = 5.0

# Quality floors for the three investment tiers (§4-§7 of the framework, and
# the same numbers the engine's zone gates use).
TIER_QUALITY = {"aggressive": 85, "preferred": 85, "excellent": 90}

# ─────────────────────────────────────────────────────────────────────────────
# WHAT RATE MAY BE PROJECTED FORWARD
# ─────────────────────────────────────────────────────────────────────────────
# The valuation band and this projection use DIFFERENT growth rates on
# purpose, and the asymmetry is the whole reason the expected-return figure is
# usable at all.
#
# `_delivered_growth` takes the HIGHER of the free-cash-flow and revenue
# CAGRs, because the band is asking "is the price demanding more than this
# company has shown", and taking the lower would punish exactly the companies
# investing hardest (Microsoft: FCF +4% while revenue +16%, because capex went
# from $28B to $116B).
#
# Projecting a return forward is the opposite question — what you will
# actually receive — so it takes the LOWER leg and caps it:
#
#   Hasbro   free cash flow +51.8% a year while revenue fell 7.1%. That is a
#            margin and working-capital recovery, not a growth rate. Projected
#            at 51.8% it valued a $96 stock at $696 and reported a 59%/yr
#            expected return.
#   Newmont  free cash flow +88.5% off a depressed base, credited at the
#            engine's 40% ceiling, which still valued a $118 stock at $1,007.
#
# The ceiling is deliberately below the engine's IMPLAUSIBLE_IMPLIED_GROWTH of
# 35%: if a PRICE demanding 35% is not underwriting a forecast anyone should
# take, then projecting more than that to compute a return is making exactly
# that forecast. This biases every expected return DOWNWARD, which is the
# right direction for a hurdle test — the cost is calling a genuine
# compounder expensive, and the alternative is manufacturing 60%/yr
# opportunities out of one good year.
PROJECTION_CEILING_PCT = 20.0


def projection_growth(row: dict, val: dict) -> tuple[float | None, str]:
    """(rate, how it was arrived at) for the forward projection."""
    fcf = f((row or {}).get("FCF_CAGR%"))
    rev = f((row or {}).get("Revenue_CAGR%"))
    rates = [r for r in (fcf, rev) if r is not None]
    base = min(rates) if rates else f((val or {}).get("delivered_credited_pct"))
    if base is None:
        return None, "no delivered growth to project"

    if len(rates) == 2 and base == rev and rev < fcf:
        note = (f"revenue +{rev:.0f}%/yr, the slower of the two legs — free "
                f"cash flow grew {fcf:+.0f}% and cannot outrun revenue for "
                f"five years")
    elif len(rates) == 2:
        note = f"free cash flow {base:+.0f}%/yr, the slower of the two legs"
    else:
        note = f"{base:+.0f}%/yr delivered"

    if base > PROJECTION_CEILING_PCT:
        return PROJECTION_CEILING_PCT, (
            f"{note}, projected at the {PROJECTION_CEILING_PCT:.0f}% ceiling — "
            f"no company at this size sustains more for five years")
    return base, note


def hurdle_for(quality_score) -> float | None:
    """The expected-return bar this business has to clear."""
    score = f(quality_score)
    if score is None:
        return None
    for floor, hurdle in RETURN_HURDLES:
        if score >= floor:
            return hurdle
    return RETURN_HURDLES[-1][1]


# Best first. Named here rather than as literals inside value_zone() so the
# /longterm filter can offer exactly the values the panel can produce.
VALUE_ZONES = ("Exceptional", "Attractive", "Fair", "Expensive", "Extreme",
               "Not priced")
TIER_LABELS = ("Excellent", "Preferred", "Aggressive")
CONFIDENCE_LEVELS = ("High", "Medium", "Low")


def value_zone(cagr, hurdle) -> tuple[str, str]:
    """(label, icon) for a price, from the return it would earn.

    Defined relative to the hurdle rather than in absolute percentages, so
    "Attractive" means the same thing — clears the bar for this business — on
    an Elite name and a merely good one.
    """
    if cagr is None or hurdle is None:
        return "Not priced", "⚪"
    if cagr >= hurdle + EXCEPTIONAL_ABOVE_HURDLE:
        return "Exceptional", "🟢🟢"
    if cagr >= hurdle:
        return "Attractive", "🟢"
    if cagr >= hurdle - FAIR_BELOW_HURDLE:
        return "Fair", "🟡"
    if cagr >= 0:
        return "Expensive", "🟠"
    return "Extreme", "🔴"


# ─────────────────────────────────────────────────────────────────────────────
# TECHNICAL ZONE CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────

def _round_band(low: float, high: float) -> tuple[float, float]:
    """Round outward to a price step a human would name. $147.83-154.92 ->
    $147-155: a band's edges are not claims, and rounding to the cent would
    restore the false precision the bands exist to remove."""
    step = 1.0 if high >= 100 else 0.5 if high >= 10 else 0.1
    return (math.floor(low / step) * step, math.ceil(high / step) * step)


def _downside(low: float, candidates: list[dict]) -> tuple[float | None, str]:
    """Distance from a zone's floor to the next tracked level beneath it.

    TECHNICAL downside only — how far to the next shelf. Deliberately not the
    same thing as the fundamental downside computed below, which is the gap
    to what the cash flows are worth. Confusing a tight stop for a margin of
    safety is the error this split exists to prevent.
    """
    below = sorted((c for c in candidates
                    if c.get("price")
                    and c["price"] < low * (1 - MIN_DOWNSIDE_PCT / 100)),
                   key=lambda c: -c["price"])
    if not below:
        return None, "nothing tracked below this zone"
    nxt = below[0]
    return round((nxt["price"] / low - 1) * 100, 1), \
        f"{nxt['name']} ${nxt['price']:,.2f}"


def _technical_zones(candidates, price, atr_pct) -> list[dict]:
    zones = []
    for key, label, anchor_zones, join_zones in TECHNICAL_ZONES:
        levels = [c for c in candidates if c.get("zone") in anchor_zones]
        if not levels:
            levels = [c for c in candidates if c.get("zone") in join_zones]
        if not levels:
            continue

        # Grown outward from the level nearest today's price. Anchors and
        # joiners obey the same width cap: PAYC's 8 and 21 EMA were 13.7%
        # apart, and two levels that far apart are two decisions.
        anchor = min(levels, key=lambda c: abs(c["price"] - (price or c["price"])))
        max_width = anchor["price"] * min(atr_pct * MAX_BAND_ATR,
                                          MAX_BAND_PCT) / 100.0
        others = [c for c in levels if c is not anchor]
        others += [c for c in candidates
                   if c.get("zone") in join_zones and c not in levels]
        others.sort(key=lambda c: abs(c["price"] - anchor["price"]))

        levels, excluded = [anchor], []
        low = high = anchor["price"]
        for cand in others:
            merged_low, merged_high = min(low, cand["price"]), max(high, cand["price"])
            if merged_high - merged_low <= max_width:
                levels.append(cand)
                low, high = merged_low, merged_high
            else:
                excluded.append(cand)
        levels.sort(key=lambda c: c["price"])

        mid = (low + high) / 2
        min_width = mid * min(atr_pct * MIN_BAND_ATR, MAX_BAND_PCT) / 100.0
        if high - low < min_width:
            low, high = mid - min_width / 2, mid + min_width / 2
        low, high = _round_band(low, high)

        down_pct, down_note = _downside(low, candidates)
        zones.append({
            "key": key, "label": label,
            "low": round(low, 2), "high": round(high, 2),
            "mid": round((low + high) / 2, 2),
            "basis": ", ".join(c["name"] for c in levels),
            "tested": any(c.get("held") for c in levels),
            "reached": (None if price is None else
                        "inside" if low <= price <= high else
                        "above" if price > high else "below"),
            "distance_pct": (None if not price else
                             round(((low + high) / 2 / price - 1) * 100, 1)),
            "downside_pct": down_pct,
            "downside_note": down_note,
            "excluded": [{"name": c["name"], "price": c["price"]}
                         for c in excluded],
        })
    zones.sort(key=lambda z: -z["mid"])
    return zones


# ─────────────────────────────────────────────────────────────────────────────
# FUNDAMENTAL LADDER
# ─────────────────────────────────────────────────────────────────────────────

def _fundamental(row, val, quality, price, risk_free) -> dict:
    """The price ladder from expected return, independent of the chart."""
    hurdle = hurdle_for((quality or {}).get("score"))
    out = {
        "hurdle_pct": hurdle,
        "quality_tier": (quality or {}).get("tier"),
        "method": (val or {}).get("method"),
        "confidence": (val or {}).get("confidence"),
        "intrinsic": None, "fair_value_gap_pct": None,
        "expected_cagr_now": None, "zone": None, "zone_icon": None,
        "ladder": [], "buy_below": None,
        "blocked": None,
    }

    if (val or {}).get("method") != "REVERSE_DCF":
        out["blocked"] = (
            "Expected return needs a cash-flow model. This name is priced off "
            "peer multiples, which say what others pay — not what the cash "
            "flows are worth.")
        return out

    growth, growth_note = projection_growth(row, val)
    if growth is None or hurdle is None:
        out["blocked"] = "No delivered growth rate to project from."
        return out
    out["projection_growth_pct"] = growth
    out["projection_note"] = growth_note

    intrinsic = V.price_at_implied_growth(row, growth, risk_free)
    if intrinsic is None:
        out["blocked"] = "The cash-flow model could not be solved for a value."
        return out

    out["intrinsic"] = intrinsic
    if price:
        out["fair_value_gap_pct"] = round((price / intrinsic - 1) * 100, 1)
        out["expected_cagr_now"] = V.expected_cagr_at_price(
            row, price, growth, risk_free)
    label, icon = value_zone(out["expected_cagr_now"], hurdle)
    out["zone"], out["zone_icon"] = label, icon

    for key, name, target in (
            ("fair", "Fair", hurdle - FAIR_BELOW_HURDLE),
            ("attractive", "Attractive", hurdle),
            ("exceptional", "Exceptional", hurdle + EXCEPTIONAL_ABOVE_HURDLE)):
        level = V.price_for_expected_cagr(row, target, growth, risk_free)
        if level is not None:
            out["ladder"].append({"key": key, "label": name,
                                  "cagr_pct": round(target, 1),
                                  "price": level})
    out["buy_below"] = next((r["price"] for r in out["ladder"]
                             if r["key"] == "attractive"), None)

    # The engine already refuses to underwrite a price implying growth past
    # its ceiling. When that fires, the whole ladder is arithmetic on trailing
    # cash flow rather than a set of levels to wait for.
    # A company whose cash flows are SHRINKING discounts to almost nothing,
    # and the ladder built off it stops being a set of prices to wait for.
    # TXN delivered -24%/yr and the model returned a $3.51 value on a $279
    # stock, with "buy below $3.40" and a +7,865% margin-of-safety reading.
    # Every figure is the arithmetic working correctly on an input that does
    # not support a five-year projection.
    if growth <= 0:
        out["caveat"] = (
            f"Projected growth is {growth:+.0f}%/yr — the model is "
            f"discounting a shrinking cash flow, so the prices below collapse "
            f"toward zero. They are arithmetic on a declining base, not "
            f"levels to wait for. Valuation cannot be read this way until "
            f"growth stabilises.")
        out["not_a_target"] = True
        return out

    implied = f(val.get("implied_growth_pct"))
    if implied is not None and implied >= V.IMPLAUSIBLE_IMPLIED_GROWTH:
        out["caveat"] = (
            f"The price implies {implied:.0f}% growth — past the "
            f"{V.IMPLAUSIBLE_IMPLIED_GROWTH:.0f}% ceiling this model will "
            f"underwrite at any delivered rate. Read the prices below as what "
            f"the arithmetic returns on trailing cash flow, not as targets.")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# THE INTERSECTION
# ─────────────────────────────────────────────────────────────────────────────
# An investment zone requires every leg. A failure is a rejection, not an
# annotation — the point of the rewrite.

INVESTMENT_TIERS = (
    ("excellent", "Excellent", "🟢🟢", EXCEPTIONAL_ABOVE_HURDLE),
    ("preferred", "Preferred", "🟢", 0.0),
    ("aggressive", "Aggressive", "🟡", -FAIR_BELOW_HURDLE),
)


def _investment_zones(technical, fundamental, quality, row, val,
                      risk_free, price=None) -> list[dict]:
    """Where a technical zone and a qualifying price actually overlap."""
    hurdle = fundamental.get("hurdle_pct")
    lq = f((quality or {}).get("score"))
    if hurdle is None or lq is None or fundamental.get("blocked"):
        return []

    # The band gates the zone, not just the action. Expected return and the
    # band read the same model through different growth legs and can
    # disagree; letting a zone exist while the band says OVERVALUED would put
    # the contradiction back one level up, which is the whole complaint this
    # rewrite answers. Valuation decides WHETHER — so it decides here.
    if not (val or {}).get("acceptable"):
        return []

    growth = fundamental.get("projection_growth_pct")
    out = []
    for key, label, icon, offset in INVESTMENT_TIERS:
        if lq < TIER_QUALITY[key]:
            continue
        ceiling = V.price_for_expected_cagr(row, hurdle + offset, growth,
                                            risk_free)
        if ceiling is None:
            continue
        # The first zone price would reach on the way down that also clears
        # this tier's return bar.
        for zone in technical:
            if zone["low"] > ceiling:
                continue                    # whole zone is too expensive
            # Tiers run best-first, so a support already claimed by a higher
            # tier is not worth restating: BMY's 8/21 EMA cleared Preferred
            # and then appeared again as Aggressive over the identical
            # $62-64, which reads as two findings and is one.
            if any(z["support"] == zone["label"] for z in out):
                break
            low, high = zone["low"], min(zone["high"], ceiling)
            out.append({
                "key": key, "label": label, "icon": icon,
                "low": round(low, 2), "high": round(high, 2),
                "min_cagr_pct": round(hurdle + offset, 1),
                "support": zone["label"], "support_basis": zone["basis"],
                "downside_pct": zone["downside_pct"],
                "min_quality": TIER_QUALITY[key],
                # A zone the price has not reached is a level to wait for,
                # not an order to place — the action below turns on this.
                "reached": price is not None and low <= price <= high,
            })
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────

def compute(row: dict, pullback: dict, val: dict, quality: dict, trend: dict,
            volume: dict, price: float | None,
            risk_free: float = V.DEFAULT_RISK_FREE) -> dict:
    candidates = [c for c in (pullback or {}).get("candidates", [])
                  if c.get("price")]
    atr_pct = f(row.get("ATR_Pct")) or FALLBACK_BAND_PCT

    technical = _technical_zones(candidates, price, atr_pct)
    fundamental = _fundamental(row, val, quality, price, risk_free)

    # Each technical zone gets the valuation reading AT ITS OWN PRICE, so the
    # table can say "support at $368, and $368 is still Extreme" in one line
    # instead of making the reader hold two panels in their head.
    growth = fundamental.get("projection_growth_pct")
    for zone in technical:
        cagr = (V.expected_cagr_at_price(row, zone["mid"], growth, risk_free)
                if growth is not None else None)
        label, icon = value_zone(cagr, fundamental.get("hurdle_pct"))
        zone["expected_cagr_pct"] = cagr
        zone["value_zone"] = label
        zone["value_icon"] = icon
        zone["fundamental_downside_pct"] = (
            None if not fundamental.get("intrinsic") else
            round((fundamental["intrinsic"] / zone["mid"] - 1) * 100, 1))

    investment = _investment_zones(technical, fundamental, quality, row, val,
                                   risk_free, price)
    return {
        "price": price,
        "display_zone": _display_zone(investment, technical, price),
        "technical": technical,
        "inverted": _inversion_note(technical),
        "fundamental": fundamental,
        "investment": investment,
        "verdict": _verdict(technical, fundamental, investment, quality,
                            trend, volume, val, price),
    }


def _display_zone(investment, technical, price) -> dict | None:
    """The one zone to put in a table cell, for EVERY name.

    A qualifying investment zone when there is one — 18 names of 552. For
    everything else, the nearest technical zone the price would actually
    reach on a pullback, flagged as technical-only.

    Showing nothing for the other 534 was the wrong answer to the right
    question: "there is no price at which this qualifies today" and "there
    is no support below this" are different statements, and a blank cell
    made them look identical. GOOGL at $345.90 has no investment zone and a
    200 MA band at $328-334; the band is worth knowing and is not a buy
    signal, so it is shown and labelled.
    """
    if investment:
        top = investment[0]
        return {"low": top["low"], "high": top["high"], "kind": "investment",
                "label": top["label"], "basis": top["support"],
                "qualifies": True,
                "distance_pct": (None if not price else
                                 round((top["high"] / price - 1) * 100, 1))}
    # The DEEPEST tracked band, which is the one the verdict sentence
    # already cites ("support runs down to $227"). Taking the nearest band
    # instead made the same panel say $227 in prose and $277 in the column
    # for TXN — two numbers for one idea. Deepest is also the more useful
    # answer: the shallow EMA band under today's price is where a pullback
    # pauses, and the structural level below it is where you would actually
    # want to accumulate.
    zone = (technical or [])[-1] if technical else None
    if not zone:
        return None
    return {"low": zone["low"], "high": zone["high"], "kind": "technical",
            "label": zone["label"], "basis": zone["basis"],
            "qualifies": False,
            "distance_pct": zone.get("distance_pct")}


def _inversion_note(zones) -> str | None:
    """Whether the support ladder runs cheapest-last, and what that is
    entitled to claim. The 50-under-200 case is readable straight off the two
    levels; the EMA case has no single cause (MU had price 6.6% ABOVE its 8
    EMA), so that branch states the ordering and stops."""
    mid_of = {z["key"]: (z["label"], z["mid"]) for z in zones}
    notes = []
    if "50ma" in mid_of and "200ma" in mid_of:
        (l50, m50), (l200, m200) = mid_of["50ma"], mid_of["200ma"]
        if m200 > m50:
            notes.append(f"The {l200} (${m200:,.0f}) sits above the {l50} "
                         f"(${m50:,.0f}) — the 50 has crossed under the 200, "
                         f"which is a broken long-term trend rather than a "
                         f"discount.")
    if "ema" in mid_of and "50ma" in mid_of:
        (lema, mema), (l50, m50) = mid_of["ema"], mid_of["50ma"]
        if m50 > mema:
            notes.append(f"The {l50} (${m50:,.0f}) is a higher price than the "
                         f"{lema} (${mema:,.0f}); zones are listed most "
                         f"expensive first.")
    return " ".join(notes) or None


# ─────────────────────────────────────────────────────────────────────────────
# THE VERDICT
# ─────────────────────────────────────────────────────────────────────────────

def _verdict(technical, fundamental, investment, quality, trend, volume,
             val, price) -> dict:
    """The checklist, the action, and what would change it.

    Every check reports pass / fail / unmeasured separately, because "the
    valuation says no" and "there is no valuation" lead to different
    decisions and the old output collapsed them.
    """
    lq = f((quality or {}).get("score"))
    hurdle = fundamental.get("hurdle_pct")
    cagr = fundamental.get("expected_cagr_now")
    gap = fundamental.get("fair_value_gap_pct")

    checks = [
        {"name": "Quality",
         "ok": None if lq is None else lq >= 85,
         "detail": (f'LQuality {lq:.0f} · {fundamental.get("quality_tier")}'
                    if lq is not None else "not scored")},
        {"name": "Long-term trend",
         "ok": None if not (trend or {}).get("state") else
               (trend or {}).get("state") in ("CONFIRMED", "PARTIAL"),
         "detail": (trend or {}).get("state") or "not measured"},
        {"name": "Technical support",
         "ok": bool(technical),
         "detail": (f'{technical[0]["label"]} ${technical[0]["low"]:,.0f}'
                    f'–${technical[0]["high"]:,.0f}' if technical
                    else "no tracked levels")},
        {"name": "Valuation",
         "ok": None if not (val or {}).get("band") else
               bool((val or {}).get("acceptable")),
         "detail": (val or {}).get("band") or "not priced"},
        # Tested against the LOWEST tier's bar, not the headline hurdle: the
        # Aggressive tier exists precisely to take a smaller position at a
        # return a few points under it, and failing the check for a name that
        # qualifies for that tier would contradict its own zone. The detail
        # spells out all three bars so the softer test is visible rather than
        # implied.
        {"name": "Expected return",
         "ok": (None if cagr is None or hurdle is None
                else cagr >= hurdle - FAIR_BELOW_HURDLE),
         "detail": (f"{cagr:+.0f}%/yr from ${price:,.2f} — Aggressive needs "
                    f"{hurdle - FAIR_BELOW_HURDLE:.0f}%, Preferred "
                    f"{hurdle:.0f}%, Excellent "
                    f"{hurdle + EXCEPTIONAL_ABOVE_HURDLE:.0f}%"
                    if cagr is not None and hurdle
                    else fundamental.get("blocked") or "not computable")},
        {"name": "Margin of safety",
         "ok": None if gap is None else gap <= 0,
         "detail": (f'{gap:+.0f}% vs the model value '
                    f'${fundamental["intrinsic"]:,.2f}' if gap is not None
                    else "no model value")},
    ]

    failed = [c["name"] for c in checks if c["ok"] is False]
    reached = [z for z in investment if z.get("reached")]
    action = "BUY" if reached and not failed else "WAIT"

    if reached and not failed:
        top = reached[0]
        what = (f'Price is in the {top["label"]} zone '
                f'(${top["low"]:,.0f}–${top["high"]:,.0f}).')
    elif investment and not failed:
        top = investment[0]
        what = (f'Everything qualifies except the price: the {top["label"]} '
                f'zone is ${top["low"]:,.0f}–${top["high"]:,.0f} and the '
                f'stock has not reached it.')
    elif investment:
        # A zone whose price qualifies while something else fails. Announcing
        # only the zone here would recreate the contradiction this module was
        # rewritten to remove, one level up.
        top = investment[0]
        blocking = " and ".join(c["detail"] for c in checks
                                if c["ok"] is False)
        what = (f'The price qualifies — {top["label"]} zone '
                f'${top["low"]:,.0f}–${top["high"]:,.0f} — but '
                f'{" and ".join(failed).lower()} does not: {blocking}.')
    elif fundamental.get("blocked"):
        what = fundamental["blocked"]
    elif fundamental.get("not_a_target"):
        # Quoting "the hurdle is not met until $3.40" on a $279 stock reads
        # as a target 99% below. It is the model discounting a shrinking
        # cash flow, and the honest sentence says that instead of the price.
        what = fundamental.get("caveat") or "Valuation is not readable here."
    elif fundamental.get("buy_below") and technical:
        cheapest = technical[-1]
        what = (f'No overlap: support runs down to ${cheapest["low"]:,.0f}, '
                f'and the return hurdle is not met until '
                f'${fundamental["buy_below"]:,.2f}. Either the price falls '
                f'that far, or growth accelerates enough to lift the model '
                f'value to meet it.')
    else:
        what = "No qualifying zone."

    return {"action": action, "checks": checks, "failed": failed,
            "what_would_change": what,
            "confidence": _confidence(fundamental, trend, volume, technical,
                                      investment)}


# Volume is a confirmation, never a gate. Heavy distribution lowers the
# confidence in a zone; it does not delete a zone that valuation, quality and
# support all agree on.
def _confidence(fundamental, trend, volume, technical, investment) -> dict:
    if not investment:
        return {"level": None, "note": "no zone to be confident about"}
    agree, notes = 0, []
    if fundamental.get("confidence") == "HIGH":
        agree += 1
        notes.append("cash-flow model on filed statements")
    if (trend or {}).get("state") == "CONFIRMED":
        agree += 1
        notes.append("trend confirmed")
    if any(z.get("tested") for z in technical):
        agree += 1
        notes.append("support has been defended")
    vol_score = f((volume or {}).get("score"))
    if vol_score is not None and vol_score >= 50:
        agree += 1
        notes.append("volume not distributing")
    elif vol_score is not None:
        notes.append(f"volume distributing ({vol_score:.0f}/100) — size down "
                     f"or wait for a reversal, rather than skipping the zone")
    level = "High" if agree >= 3 else "Medium" if agree == 2 else "Low"
    return {"level": level, "agree": agree, "note": "; ".join(notes)}
