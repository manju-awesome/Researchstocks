"""
moat.py
=======
Quantitative moat proxy for the research page's Company Overview: scores the
financial FINGERPRINT a durable competitive advantage leaves — high margins
held with high returns on capital, self-funding cash flow, scale — from
fields every scan row already carries. 0–100 with named drivers.

What this is not: a Morningstar-style Wide/Narrow/None verdict. Brand,
network effects, switching costs, and regulatory capture are qualitative
judgments no ratio confirms; a commodity cyclical at peak margins can score
high here for a year. That's why the output is labeled "moat signals"
(Strong/Moderate/Weak) with the inputs shown, not a moat "rating" — the
number says "the financials look like a moat's financials," the reader
judges whether the advantage is real and durable.

Weights (sum 100):
    Gross margin        25  — pricing power
    Operating margin    25  — cost structure / scale efficiency
    Return on equity    20  — returns on capital well above its cost
    FCF positive        10  — self-funding (no dilution treadmill)
    Market cap          10  — scale itself deters entry
    Institutional own   10  — sophisticated holders underwriting the story

Pure function, no network. Needs >= 3 of the 6 inputs, else returns the
"insufficient data" shape rather than a score built on two ratios.
"""

from __future__ import annotations

MIN_INPUTS = 3

LABELS = ((70, "Strong"), (45, "Moderate"), (0, "Weak"))


def _label(score: int) -> str:
    for floor, name in LABELS:
        if score >= floor:
            return name
    return "Weak"


def compute_moat(row: dict) -> dict:
    """
    row: a scan/research row (needs GrossMargin%, OperatingMargin%,
    ReturnOnEquity%, FCF_Positive, MarketCap, Inst_Own% — any subset).
    Returns {"score": int|None, "label": str|None, "drivers": [str, ...],
             "inputs_used": int}.
    """
    score, drivers, used = 0, [], 0

    gm = row.get("GrossMargin%")
    if gm is not None:
        used += 1
        pts = 25 if gm >= 60 else 15 if gm >= 40 else 8 if gm >= 25 else 0
        score += pts
        drivers.append(f"Gross margin {gm:.0f}% ({pts:+d})")

    om = row.get("OperatingMargin%")
    if om is not None:
        used += 1
        pts = 25 if om >= 25 else 15 if om >= 15 else 8 if om >= 8 else 0
        score += pts
        drivers.append(f"Operating margin {om:.0f}% ({pts:+d})")

    roe = row.get("ReturnOnEquity%")
    if roe is not None:
        used += 1
        pts = 20 if roe >= 25 else 12 if roe >= 15 else 6 if roe >= 8 else 0
        score += pts
        drivers.append(f"ROE {roe:.0f}% ({pts:+d})")

    fcf = row.get("FCF_Positive")
    if fcf is not None:
        used += 1
        pts = 10 if fcf else 0
        score += pts
        drivers.append(f"FCF {'positive' if fcf else 'negative'} ({pts:+d})")

    cap = row.get("MarketCap")
    if cap is not None:
        used += 1
        pts = 10 if cap >= 100e9 else 5 if cap >= 10e9 else 0
        score += pts
        drivers.append(f"Market cap ${cap / 1e9:.0f}B ({pts:+d})")

    inst = row.get("Inst_Own%")
    if inst is not None:
        used += 1
        pts = 10 if inst >= 40 else 0
        score += pts
        drivers.append(f"Institutional ownership {inst:.0f}% ({pts:+d})")

    if used < MIN_INPUTS:
        return {"score": None, "label": None,
                "drivers": [f"only {used} of 6 inputs available"],
                "inputs_used": used}

    return {"score": score, "label": _label(score),
            "drivers": drivers, "inputs_used": used}
