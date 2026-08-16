"""
units.py
========
Indian land-measure and money parsing. Every other module works in two
canonical units — **acres** for area, **rupees** for money — and this is the
only place that knows how to get there from what a listing actually says.

Why this needs its own module: Karnataka land listings mix at least four area
units in one sentence ("2 acre 15 gunta, 1.2 lakh sq ft plot adjacent") and
two money scales ("45L per acre, total 1.8 Cr"). Getting acres wrong by a
factor of 40 (guntas) or price wrong by 100x (lakh vs crore) corrupts every
downstream score silently — price-per-acre is the input to the comparables
engine, and a bad one looks like a spectacular bargain rather than a bug.

Conversions used:
    1 acre  = 40 guntas = 43,560 sq ft
    1 gunta = 1,089 sq ft
    1 lakh  = 100,000
    1 crore = 10,000,000 = 100 lakh

Parsing is deliberately conservative: anything it cannot read confidently
returns None rather than a guess. A missing acreage becomes a "missing
information" line on the property page, which is recoverable. A wrong one
propagates into the deal score, which is not.
"""

from __future__ import annotations

import re

SQFT_PER_ACRE = 43560.0
GUNTAS_PER_ACRE = 40.0
SQFT_PER_GUNTA = SQFT_PER_ACRE / GUNTAS_PER_ACRE   # 1089.0

LAKH = 100_000
CRORE = 10_000_000

# Listings write the same unit a dozen ways. Longest-first so "acres" wins
# over "acre" and we don't leave a stray "s" to confuse the number scan.
_ACRE_WORDS = ("acres", "acre", "ac.", "ac", "ekare", "ekre")
_GUNTA_WORDS = ("guntas", "gunta", "guntha", "gunthas", "gunte", "guntes")
_SQFT_WORDS = ("square feet", "square ft", "sq feet", "sq.ft", "sq ft",
               "sqft", "sft", "sq. ft")

_NUM = r"(\d+(?:[.,]\d+)?)"


def _f(text) -> float | None:
    """Float from a string that may carry Indian digit grouping (12,50,000)."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return None if text != text else float(text)
    s = str(text).strip().replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return None if v != v else v


# ---------------------------------------------------------------- area ----

def guntas_to_acres(guntas) -> float | None:
    g = _f(guntas)
    return None if g is None else g / GUNTAS_PER_ACRE


def sqft_to_acres(sqft) -> float | None:
    s = _f(sqft)
    return None if s is None else s / SQFT_PER_ACRE


def acres_to_guntas(acres) -> float | None:
    a = _f(acres)
    return None if a is None else a * GUNTAS_PER_ACRE


def acres_to_sqft(acres) -> float | None:
    a = _f(acres)
    return None if a is None else a * SQFT_PER_ACRE


def parse_area(text) -> tuple[float | None, str]:
    """Read an area phrase and return (acres, how_it_was_read).

    Handles the compound form Karnataka listings actually use — "2 acre 20
    gunta" means 2.5 acres, not two separate parcels — plus bare acres, bare
    guntas and square feet. The second return value is kept for the property
    page: when a number looks surprising the user needs to see which reading
    produced it, and "3 acre 10 gunta -> 3.25 ac" is self-checking in a way
    that a lone "3.25" is not.

    Returns (None, "") when nothing parses. An unreadable area is reported as
    missing, never guessed.
    """
    if text is None:
        return None, ""
    s = str(text).lower().strip()
    if not s:
        return None, ""

    acres = 0.0
    parts: list[str] = []
    found = False

    # Compound and bare acre: the acre term is read first so a following
    # gunta term is understood as an addition to it, not an alternative.
    for w in _ACRE_WORDS:
        m = re.search(_NUM + r"\s*" + re.escape(w) + r"\b", s)
        if m:
            v = _f(m.group(1))
            if v is not None:
                acres += v
                parts.append(f"{_trim(v)} acre")
                found = True
            break

    for w in _GUNTA_WORDS:
        m = re.search(_NUM + r"\s*" + re.escape(w) + r"\b", s)
        if m:
            v = _f(m.group(1))
            if v is not None:
                acres += v / GUNTAS_PER_ACRE
                parts.append(f"{_trim(v)} gunta")
                found = True
            break

    if found:
        return round(acres, 4), " + ".join(parts)

    # Square feet only. Common for the smaller "farm plot" listings, which
    # are usually layout plots rather than agricultural land — the size
    # sanity check downstream is what flags those, not this function.
    for w in _SQFT_WORDS:
        m = re.search(_NUM + r"\s*" + re.escape(w) + r"\b", s)
        if m:
            v = _f(m.group(1))
            if v is not None:
                return round(v / SQFT_PER_ACRE, 4), f"{_trim(v)} sq ft"
            break

    return None, ""


def _trim(v: float) -> str:
    return f"{v:.10g}"


def format_area(acres) -> str:
    """Acres for reading, with guntas spelled out below one acre.

    Sub-acre parcels are quoted and negotiated in guntas locally; printing
    "0.62 acres" to someone who was told "25 gunta" makes the two look like
    different parcels during a phone call.
    """
    a = _f(acres)
    if a is None:
        return "—"
    if a < 1:
        return f"{a * GUNTAS_PER_ACRE:.0f} gunta ({a:.2f} ac)"
    whole = int(a)
    rem_g = round((a - whole) * GUNTAS_PER_ACRE)
    if rem_g == 0:
        return f"{whole} ac"
    if rem_g == 40:            # rounding pushed it to a whole acre
        return f"{whole + 1} ac"
    return f"{whole} ac {rem_g} gunta ({a:.2f} ac)"


# --------------------------------------------------------------- money ----

def parse_price(text) -> float | None:
    """Read a price phrase into rupees.

    The scale word is the whole game: "45" next to "L"/"lakh" is 4.5 million
    rupees and next to "Cr"/"crore" is 450 million. When no scale word is
    present the bare number is read literally, which is why a listing saying
    just "45" yields ₹45 and gets caught by the sanity check rather than
    being silently promoted to lakhs.

    Returns None when no number is present at all.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return None if text != text else float(text)

    s = str(text).lower().replace("₹", " ").replace("rs.", " ").replace("rs", " ")
    s = s.replace("inr", " ").strip()
    if not s:
        return None

    m = re.search(_NUM + r"\s*(crore|crores|cr\b|c\b)", s)
    if m:
        v = _f(m.group(1))
        return None if v is None else v * CRORE

    m = re.search(_NUM + r"\s*(lakhs|lakh|lacs|lac|l\b)", s)
    if m:
        v = _f(m.group(1))
        return None if v is None else v * LAKH

    # Bare number with Indian grouping, e.g. "45,00,000".
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", s)
    if m:
        return _f(m.group(1))
    return None


def format_price(rupees) -> str:
    """Rupees in the scale a local buyer would say out loud."""
    v = _f(rupees)
    if v is None:
        return "—"
    if v >= CRORE:
        return f"₹{v / CRORE:.2f} Cr"
    if v >= LAKH:
        return f"₹{v / LAKH:.1f} L"
    if v >= 1000:
        return f"₹{v / 1000:.0f}K"
    return f"₹{v:.0f}"


def price_per_acre(total_price, acres) -> float | None:
    p, a = _f(total_price), _f(acres)
    if p is None or a is None or a <= 0:
        return None
    return p / a


# ------------------------------------------------------------- sanity ----

# Bounds for the Mysuru agricultural market as of 2026. These are not a
# valuation — they are a "this number cannot be right" filter for parse
# errors. A genuine ₹8L/acre parcel 30 km out is possible; a ₹8/acre one is a
# missing scale word, and a ₹40 Cr/acre one is a lakh read as a crore.
MIN_PLAUSIBLE_PER_ACRE = 200_000        # ₹2 L/acre
MAX_PLAUSIBLE_PER_ACRE = 200_000_000    # ₹20 Cr/acre
MAX_PLAUSIBLE_ACRES = 500.0


def price_sanity(total_price, acres) -> str | None:
    """Return a human-readable warning when a parsed price/area pair cannot
    be right, else None. The caller keeps the value and shows the warning —
    dropping it would hide a parse bug instead of surfacing it."""
    ppa = price_per_acre(total_price, acres)
    if ppa is None:
        return None
    if ppa < MIN_PLAUSIBLE_PER_ACRE:
        return (f"₹{ppa:,.0f}/acre is far below any plausible Mysuru price — "
                f"the listing probably omitted a 'lakh'/'crore' scale word.")
    if ppa > MAX_PLAUSIBLE_PER_ACRE:
        return (f"₹{ppa:,.0f}/acre is implausibly high — a 'lakh' was likely "
                f"read as a 'crore', or the price covers more land than stated.")
    return None


def area_sanity(acres) -> str | None:
    a = _f(acres)
    if a is None:
        return None
    if a <= 0:
        return "Parsed area is zero or negative — the size phrase did not read correctly."
    if a > MAX_PLAUSIBLE_ACRES:
        return (f"{a:,.0f} acres is far outside anything on offer around Mysuru — "
                f"a sq-ft figure was probably read as acres.")
    return None
