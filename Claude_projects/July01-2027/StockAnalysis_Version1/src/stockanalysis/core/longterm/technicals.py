"""
technicals.py — when to buy a company you have already decided to own
=====================================================================
Gates three and four. Nothing here asks whether the business is good; that
was settled in quality.py and valuation.py. This module answers only:

    compute_trend()               is the long-term uptrend intact?
    compute_pullback()            has price come back to a level worth
                                  buying, and which one?
    compute_support_confluence()  how many independent levels agree here?
    compute_pullback_volume()     is this pullback accumulation or
                                  distribution?

The distinction that shapes the file
------------------------------------
"Price is near the 50 MA" is not a signal. It is a coordinate. Every stock
in a downtrend passes through its 50 MA on the way down, and a screener
built on proximity alone cannot tell that pass-through from a bounce.

So no level is scored for being nearby. A level counts as SUPPORT only when
price is at or above it — a moving average the price has already fallen
through is resistance, and the sign of that difference is the entire
difference between a pullback and a breakdown. `_supports()` is where that
rule lives, and every level in the confluence score goes through it.

Tolerance is measured in the stock's own volatility
---------------------------------------------------
"Within 2% of the 50 MA" means something different for a utility and for a
semiconductor. Every proximity test here uses `_tolerance()`, which is a
multiple of the stock's ATR% with a floor, so "at the level" means the same
thing across the library. A fixed percentage would classify every
high-volatility name as permanently at every level at once.

Fields this module needs that older scan rows will not have
-----------------------------------------------------------
MA200_Slope%, MA50_Slope%, Reversal_Candle, Distribution_Days_25d and
Prior_Breakout_Level were added to metrics.py alongside this engine. Rows
scanned before that carry None for them, and every check reads None as
UNKNOWN rather than as a failure — an unscanned field is not a broken
trend. The cost is that the trend gate returns None instead of True for
those rows, which downgrades them to WATCH rather than promoting them, and
that is the correct direction to be wrong in.
"""

from __future__ import annotations

from stockanalysis.core.longterm._common import b, band, f, scale

# Proximity is ATR-scaled, but not without bounds: on a 0.5%-ATR name a pure
# multiple would demand price sit within a few cents of the average, and on
# a 15%-ATR name it would call a 20% gap "at the level".
TOLERANCE_ATR_MULT = 1.5
MIN_TOLERANCE_PCT = 1.5
MAX_TOLERANCE_PCT = 8.0

# Above this far over the 8 EMA there is no pullback to buy — this is a
# chase, whatever else scores well.
EXTENDED_ABOVE_8EMA = 4.0

ZONES = ("EMA", "50MA", "200MA", "BREAKOUT", "NONE")
ZONE_LABELS = {
    "EMA": "Zone A — 8/21 EMA",
    "50MA": "Zone B — 50 MA",
    "200MA": "Zone C — 200 MA",
    "BREAKOUT": "Prior breakout support",
    "NONE": "No pullback — not at a level",
}

# ── Pullback stages ──────────────────────────────────────────────────────────
# The zone above answers "is price sitting ON a tracked level". The stage
# answers "how deep is this pullback", and they are not the same question.
#
# The gap between them is what made Western Digital unreadable. At 21.9%
# below its 50 MA and 28.5% above its 200 MA, with an 8% tolerance, WDC is
# near nothing — zone NONE, "not at any tracked level" — which reads as "no
# setup" when the truth is "a very deep correction that has not broken the
# long-term trend". That is a specific, nameable state, and one of the more
# interesting ones a quality-on-pullback strategy can find.
STAGES = ("AT_HIGHS", "STAGE1_EMA", "STAGE2_50MA", "STAGE3_DEEP",
          "STAGE4_BREAKDOWN", "EXTENDED")
STAGE_LABELS = {
    "AT_HIGHS": "At highs — no pullback",
    "STAGE1_EMA": "Stage 1 — 8/21 EMA pullback",
    "STAGE2_50MA": "Stage 2 — 50 MA pullback",
    "STAGE3_DEEP": "Stage 3 — deep pullback, 200 MA approach",
    "STAGE4_BREAKDOWN": "Stage 4 — trend breakdown",
    "EXTENDED": "Extended above the 8 EMA",
}
STAGE_ICONS = {"AT_HIGHS": "⚪", "STAGE1_EMA": "🟢", "STAGE2_50MA": "🟢",
               "STAGE3_DEEP": "🟡", "STAGE4_BREAKDOWN": "🔴",
               "EXTENDED": "🟠"}


def classify_stage(row: dict, zone: str, extended: bool) -> str:
    """Which of the four pullback stages price occupies.

    Checked in order of severity: below the 200 MA is a breakdown whatever
    else is true, and only then does it matter which level price is resting
    on. A stock can be below its 50 MA and still be at a tradeable level
    (the prior breakout, a volume shelf), which is why the zone is consulted
    before the raw distance.
    """
    price = _price(row)
    ma50, ma200 = f(row.get("50MA")), f(row.get("200MA"))

    if price is not None and ma200 is not None and price < ma200:
        return "STAGE4_BREAKDOWN"
    if zone == "EMA":
        return "STAGE1_EMA"
    if zone == "50MA":
        return "STAGE2_50MA"
    if zone == "200MA":
        return "STAGE3_DEEP"
    if price is not None and ma50 is not None and price < ma50:
        # Below the 50 MA but still above the 200 MA — the deep-correction
        # state. Applies whether or not price is resting on a breakout shelf.
        return "STAGE3_DEEP"
    if extended:
        return "EXTENDED"
    if zone == "BREAKOUT":
        return "STAGE1_EMA" if price and ma50 and price >= ma50 else "STAGE3_DEEP"
    return "AT_HIGHS"

# Bands are set on the COUNT of levels agreeing, not on the weighted score.
#
# Two reasons. First, the count is what actually gates a buy
# (engine.MIN_CONFLUENCE_HITS), so a label drawn from the score described one
# thing while the decision used another — and the boundary between "adequate"
# and "weak" now falls exactly where the engine stops issuing buys.
#
# Second, the score cannot carry a label at all: measured across the 545-row
# library, the score ranges for adjacent counts OVERLAP (3 levels spans 35-70,
# 4 levels spans 60-75), because which levels agree matters as much as how
# many. A 50 MA plus 200 MA agreement scores 50 on two hits; the 8/21 EMA plus
# a key level scores 25 on the same two. The old score bands (80/65/50) put
# 448 of 545 rows in "Weak" and 14 above "Good" — a label four-fifths of the
# page shares is not telling you anything.
#
# Distribution on the live library: 4+ levels 11.7%, 3 levels 27.3%,
# 2 levels 23.5%, 0-1 levels 37.4%.
CONFLUENCE_BANDS = ((4, "🔥 Strong"), (3, "🟢 Good"),
                    (2, "🟡 Adequate"), (0, "🔴 Weak"))

# The support ladder, shallowest first: (row field, zone, display name).
# Ordered by lookback rather than by price, so S1..S4 name the same average
# on every ticker and a column of them is comparable down the page. Which
# level is actually nearest is a property of the tape and changes daily —
# see compute_pullback(), which picks the zone by distance, not by this order.
SUPPORT_LEVELS = (
    ("8EMA", "EMA", "8 EMA"),
    ("21EMA", "EMA", "21 EMA"),
    ("50MA", "50MA", "50 MA"),
    ("200MA", "200MA", "200 MA"),
    ("Prior_Breakout_Level", "BREAKOUT", "prior breakout"),
)
# S1..S4 in the UI map to the first four, by design: a fixed ladder is
# sortable and comparable across rows, which a "nearest support" numbering
# would not be.
SUPPORT_SLOTS = tuple(
    (f"S{i + 1}", key, name)
    for i, (key, _zone, name) in enumerate(SUPPORT_LEVELS[:4]))

VOLUME_BANDS = ((80, "Healthy — accumulation"), (60, "Acceptable"),
                (40, "Mixed"), (0, "Distribution — avoid"))


def _price(row):
    return f(row.get("Current Price")) or f(row.get("price"))


def _tolerance(row) -> float:
    """How close counts as "at the level", in percent, for this stock."""
    atr = f(row.get("ATR_Pct"))
    if atr is None:
        return MIN_TOLERANCE_PCT * 2      # unknown volatility: be permissive
                                          # about proximity, strict elsewhere
    return max(MIN_TOLERANCE_PCT,
               min(MAX_TOLERANCE_PCT, atr * TOLERANCE_ATR_MULT))


def _supports(price, level, tol_pct) -> tuple[bool, float | None]:
    """Is `level` acting as support for `price` right now?

    True only when price is AT or ABOVE the level and within tolerance of
    it. Price below the level means the level was lost — that is
    resistance overhead, and counting it as support is how a screener
    recommends a breakdown. Returns (is_support, signed % price sits above).
    """
    if price is None or level is None or level <= 0:
        return False, None
    dist = (price / level - 1) * 100.0
    return (0 <= dist <= tol_pct), dist


# ─────────────────────────────────────────────────────────────────────────────
# TREND — §3. The precondition for everything else.
# ─────────────────────────────────────────────────────────────────────────────

TREND_STATES = ("CONFIRMED", "PARTIAL", "BROKEN")
TREND_ICONS = {"CONFIRMED": "🟢", "PARTIAL": "🟡", "BROKEN": "🔴"}

# (name, weight, structural). STRUCTURAL checks answer "was this a healthy
# long-term uptrend"; the rest answer "where is price inside it right now".
# Only structural checks can break the trend — see the docstring.
_TREND_CHECKS = (
    ("Price above 200 MA", 20, True),
    ("50 MA above 200 MA", 20, True),
    ("200 MA rising", 20, True),
    ("50 MA rising", 15, True),
    ("Price above 50 MA", 15, False),
    ("Price above 21 EMA", 5, False),
    ("Price above 8 EMA", 5, False),
)


def compute_trend(row: dict) -> dict:
    """
    Trend as a THREE-state reading, not a pass/fail.

        🟢 CONFIRMED  every structural check known and holding
        🟡 PARTIAL    structure holds, but something is unmeasured
        🔴 BROKEN     a structural check actually failed

    Two distinctions do the work here, and collapsing either one produces
    the wrong answer on exactly the setups this engine hunts.

    UNKNOWN IS NOT FAILURE. Western Digital sits above its 200 MA with the
    50 MA above the 200 MA, and its moving-average slopes were never
    scanned. Reporting that as "failed on trend" states something the data
    does not support, and buries a live candidate among genuine breakdowns.
    It is PARTIAL: 40 points confirmed, 35 unknown, nothing failed.

    STRUCTURE IS NOT POSITION. "Price above the 50 MA" describes where price
    sits today, not whether the uptrend is intact, and requiring it inside a
    trend gate contradicts the whole strategy: a stock cannot pull back to
    its 50 MA while remaining comfortably above it. So price-vs-MA checks
    are scored — they are real information — but they can never break the
    trend. How far price has fallen is the PULLBACK STAGE's job; see
    compute_pullback().

    Returns {"state", "icon", "score", "confirmed_points", "unknown_points",
             "checks", "failed", "unknown", "structural_failed", "pass"}.
    `pass` is kept as a convenience tri-state (True/None/False) mapping to
    CONFIRMED/PARTIAL/BROKEN for callers that only need the coarse reading.
    """
    price = _price(row)
    ma50, ma200 = f(row.get("50MA")), f(row.get("200MA"))
    ema8, ema21 = f(row.get("8EMA")), f(row.get("21EMA"))
    slope200 = f(row.get("MA200_Slope%"))
    slope50 = f(row.get("MA50_Slope%"))
    vs50 = f(row.get("Price_vs_50MA%"))
    if vs50 is None and price and ma50:
        vs50 = (price / ma50 - 1) * 100.0
    above200 = b(row.get("Above_200MA"))
    if above200 is None and price is not None and ma200 is not None:
        above200 = price > ma200

    def _above(level):
        if price is None or level is None:
            return None, "unknown"
        return price > level, f"${price:,.2f} vs ${level:,.2f}"

    results = {
        "Price above 200 MA": (
            above200,
            "unknown" if above200 is None else
            (f"${price:,.2f} vs ${ma200:,.2f}" if price and ma200
             else ("above" if above200 else "below"))),
        "50 MA above 200 MA": (
            None if (ma50 is None or ma200 is None) else ma50 > ma200,
            "unknown" if (ma50 is None or ma200 is None)
            else f"${ma50:,.2f} vs ${ma200:,.2f}"),
        "200 MA rising": (
            None if slope200 is None else slope200 > 0,
            "not measured — re-scan to populate" if slope200 is None
            else f"{slope200:+.2f}% over 20 sessions"),
        "50 MA rising": (
            None if slope50 is None else slope50 > 0,
            "not measured — re-scan to populate" if slope50 is None
            else f"{slope50:+.2f}% over 20 sessions"),
        "Price above 50 MA": (
            None if vs50 is None else vs50 > 0,
            "unknown" if vs50 is None else f"{vs50:+.1f}%"),
        "Price above 21 EMA": _above(ema21),
        "Price above 8 EMA": _above(ema8),
    }

    checks, confirmed_pts, unknown_pts = [], 0, 0
    for name, weight, structural in _TREND_CHECKS:
        ok, detail = results[name]
        checks.append({"name": name, "ok": ok, "detail": detail,
                       "weight": weight, "structural": structural,
                       # kept for the existing UI, which renders "(required)"
                       "required": structural})
        if ok is None:
            unknown_pts += weight
        elif ok:
            confirmed_pts += weight

    failed = [c["name"] for c in checks if c["ok"] is False]
    unknown = [c["name"] for c in checks if c["ok"] is None]
    structural_failed = [c["name"] for c in checks
                         if c["structural"] and c["ok"] is False]
    structural_unknown = [c["name"] for c in checks
                          if c["structural"] and c["ok"] is None]

    if structural_failed:
        state = "BROKEN"
    elif structural_unknown:
        state = "PARTIAL"
    else:
        state = "CONFIRMED"

    return {
        "state": state,
        "icon": TREND_ICONS[state],
        # The score is out of a fixed 100, NOT renormalised over what was
        # measured. That is the point: "40 confirmed, 35 unknown" is the
        # honest reading, and renormalising would turn it into 53/100 and
        # lose the distinction between measured and merely absent.
        "score": confirmed_pts,
        "confirmed_points": confirmed_pts,
        "unknown_points": unknown_pts,
        "checks": checks,
        "failed": failed,
        "unknown": unknown,
        "structural_failed": structural_failed,
        "required_failed": structural_failed,     # legacy alias
        "pass": {"CONFIRMED": True, "PARTIAL": None, "BROKEN": False}[state],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PULLBACK ZONE — §4/5/6. Which level is price actually at?
# ─────────────────────────────────────────────────────────────────────────────

def compute_pullback(row: dict) -> dict:
    """
    Which of the framework's entry zones price currently occupies.

    Zones are assigned by which level price is nearest AND above, not by
    which moving average is conventionally "deeper". After a fast move the
    averages do not stay in textbook order — a stock can sit below its 8 EMA
    and above its 50 MA at the same time — so the zone follows the tape.

    Returns {"zone", "label", "level", "level_price", "distance_pct",
             "extended", "depth_from_high", "candidates", "by_level",
             "range_52w", "note"}. `by_level` is keyed by row field so a
    caller can render a fixed S1..S4 ladder without re-deriving distances.
    """
    price = _price(row)
    tol = _tolerance(row)
    pct8 = f(row.get("Pct_vs_8EMA"))

    candidates = []
    by_level = {}
    for key, zone, name in SUPPORT_LEVELS:
        value = f(row.get(key))
        ok, dist = _supports(price, value, tol)
        entry = {"key": key, "zone": zone, "name": name,
                 "price": None if value is None else round(value, 2),
                 "distance_pct": None if dist is None else round(dist, 2),
                 # Above the level is support underfoot; below it the level
                 # is overhead resistance. The sign carries that, and it is
                 # the single most important thing on this row.
                 "held": None if dist is None else dist >= 0,
                 "supporting": bool(ok)}
        by_level[key] = entry
        if dist is not None:
            candidates.append(entry)

    extended = pct8 is not None and pct8 > EXTENDED_ABOVE_8EMA
    supporting = [c for c in candidates if c["supporting"]]
    # Nearest supporting level wins. Ties go to the tighter distance, which
    # is what "price is sitting on it" means.
    supporting.sort(key=lambda c: c["distance_pct"])

    depth = f(row.get("Dist_52W_High%"))

    if extended:
        zone, chosen = "NONE", None
        note = (f"Extended {pct8:.1f}% above the 8 EMA — buying here pays the "
                f"top of the move, whatever the level score says")
    elif supporting:
        chosen = supporting[0]
        zone = chosen["zone"]
        note = (f"At the {chosen['name']} — price ${price:,.2f} is "
                f"{chosen['distance_pct']:+.1f}% above ${chosen['price']:,.2f} "
                f"(within {tol:.1f}% tolerance for this stock's volatility)")
    else:
        zone, chosen = "NONE", None
        below = [c for c in candidates if c["distance_pct"] < 0]
        if below and price is not None:
            nearest = max(below, key=lambda c: c["distance_pct"])
            note = (f"Below the {nearest['name']} "
                    f"(${nearest['price']:,.2f}, {nearest['distance_pct']:+.1f}%) "
                    f"— that is resistance overhead, not support underfoot")
        else:
            note = "Not at any tracked level — no entry to price yet"

    stage = classify_stage(row, zone, extended)
    supports = compute_supports(row)

    # The stage's own sentence wins where it knows more than the zone did.
    # "Not at any tracked level" is true of a deep correction and tells you
    # nothing; naming the correction and the level under it is the finding.
    if stage == "STAGE3_DEEP" and zone == "NONE":
        vs50 = f(row.get("Price_vs_50MA%"))
        vs200 = f(row.get("Price_vs_200MA%"))
        near = supports.get("near")
        note = (f"Deep pullback — "
                + (f"{abs(vs50):.1f}% below the 50 MA" if vs50 is not None
                   else "below the 50 MA")
                + (f", still {vs200:+.1f}% above the 200 MA"
                   if vs200 is not None else "")
                + (f". Nearest support ${near['price']:,.2f} "
                   f"({near['distance_pct']:+.1f}% away)" if near else ""))
    elif stage == "STAGE4_BREAKDOWN":
        # Derived from the same price and level the stage decision used, not
        # read from Price_vs_200MA%. Where the scan column disagrees with the
        # levels on the row — a partially refreshed row, a CSV round trip —
        # trusting it prints "Below the 200 MA (+25.0%)", a sentence that
        # contradicts itself inside eight words.
        ma200 = f(row.get("200MA"))
        vs200 = ((price / ma200 - 1) * 100.0
                 if price and ma200 else f(row.get("Price_vs_200MA%")))
        note = ("Below the 200 MA"
                + (f" ({vs200:+.1f}%)" if vs200 is not None else "")
                + " — this is a trend breakdown, not a pullback to buy")

    return {
        "zone": zone,
        "label": ZONE_LABELS[zone],
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_icon": STAGE_ICONS[stage],
        "level": None if chosen is None else chosen["name"],
        "level_price": None if chosen is None else chosen["price"],
        "distance_pct": None if chosen is None else chosen["distance_pct"],
        "extended": extended,
        "pct_vs_8ema": pct8,
        "depth_from_high": depth,
        "tolerance_pct": round(tol, 2),
        "candidates": candidates,
        "by_level": by_level,
        "supports": supports,
        "buy_zone": compute_buy_zone_level(row),
        "range_52w": compute_52w_range(row),
        "note": note,
    }


def compute_buy_zone_level(row: dict) -> dict:
    """The price to actually plan an entry around, and how much it is worth.

    Two very different things can fill this slot, and conflating them is the
    trap:

      A TESTED level — the key-level engine's S1, a shelf the market has
      traded heavily at and defended before. Western Digital's $420.26 has
      329 touches and volume confirmation. That is a real place to work an
      order.

      A DERIVED level — a moving average that happens to be the next line
      under the price. Nobody has defended it; it is arithmetic on the last
      50 closes. It is still the most useful number available when no tested
      level exists, but presenting it in the same voice would turn "here is
      where support probably is" into "here is where support is".

    So `actual_support` is returned on every result and the caller is
    expected to render the two differently. 425 of 545 library rows have a
    key level and 348 are volume-confirmed, so the derived case is roughly a
    third of the page — common enough that mislabelling it would matter.
    """
    price = _price(row)
    out = {"price": None, "distance_pct": None, "source": None,
           "touches": None, "volume_confirmed": None, "actual_support": False,
           "label": None, "note": "no level beneath the current price"}
    if price is None or price <= 0:
        return out

    def fill(level, source, label, actual, note, touches=None, confirmed=None):
        out.update({"price": round(level, 2),
                    "distance_pct": round((level / price - 1) * 100.0, 1),
                    "source": source, "label": label, "actual_support": actual,
                    "note": note, "touches": touches,
                    "volume_confirmed": confirmed})
        return out

    s1 = f(row.get("S1"))
    if s1 is not None and 0 < s1 <= price:
        touches = f(row.get("Touches"))
        confirmed = b(row.get("Volume_Confirmation"))
        bits = []
        if touches:
            bits.append(f"{touches:.0f} touches")
        if confirmed:
            bits.append("volume-confirmed")
        return fill(s1, "volume_shelf",
                    " · ".join(bits) or "prior support",
                    bool(confirmed),
                    ("tested support — the market has defended this price"
                     if confirmed else
                     "prior support, but not volume-confirmed"),
                    touches, confirmed)

    # Fall back to the nearest moving average below price. Named after the
    # average it came from so the card can say where it came from rather
    # than presenting a computed line as a level someone defended.
    below = []
    for key, _zone, label in SUPPORT_LEVELS:
        level = f(row.get(key))
        if level is not None and 0 < level <= price:
            below.append((level, label))
    if below:
        level, label = max(below)
        return fill(level, "moving_average", label, False,
                    f"no tested level — this is the {label}, not support "
                    f"anyone has defended")
    return out


def compute_supports(row: dict) -> dict:
    """Near-term support and major support, as two separate answers.

    They are not interchangeable. For Western Digital the 200 MA sits at
    $341 — 22% below the tape — while a volume-confirmed shelf at $420 is
    4.1% away. Only one of those is a level you can plan an entry around
    this week, and a system that reports the moving average because it is
    the one with a name is answering the wrong question.

    "Near" is the closest level beneath price from any method (the key-level
    engine's volume-confirmed S1, a moving average, a prior breakout).
    "Major" is the 200 MA, the structural floor the whole thesis rests on.
    """
    price = _price(row)
    out = {"near": None, "major": None}
    if price is None or price <= 0:
        return out

    def entry(name, level, kind, confirmed=None):
        if level is None or level <= 0 or level > price:
            return None
        return {"name": name, "price": round(level, 2),
                "distance_pct": round((level / price - 1) * 100.0, 1),
                "kind": kind,
                "volume_confirmed": confirmed}

    candidates = []
    s1 = entry("volume shelf", f(row.get("S1")), "key_level",
               b(row.get("Volume_Confirmation")))
    if s1:
        touches = f(row.get("Touches"))
        if touches:
            s1["name"] = f"volume shelf ({touches:.0f} touches)"
        candidates.append(s1)
    for key, _zone, label in SUPPORT_LEVELS:
        got = entry(label, f(row.get(key)), "moving_average")
        if got:
            candidates.append(got)

    if candidates:
        # Nearest below price — the one a pullback reaches first.
        out["near"] = max(candidates, key=lambda c: c["distance_pct"])

    ma200 = f(row.get("200MA"))
    if ma200 is not None and ma200 > 0:
        out["major"] = {"name": "200 MA", "price": round(ma200, 2),
                        "distance_pct": round((ma200 / price - 1) * 100.0, 1),
                        "kind": "moving_average", "volume_confirmed": None}
    return out


def compute_52w_range(row: dict) -> dict:
    """Where price sits in its own 52-week range.

    The two endpoints are not interchangeable readings. Distance from the
    high says how much of a drawdown you are buying; distance from the low
    says how much of a recovery you are paying for. A stock 8% off its high
    and one 8% off its low can carry the same LQuality and are not the same
    purchase, and `position_pct` — where in the range price actually sits —
    is the one number that separates them at a glance.
    """
    price = _price(row)
    high, low = f(row.get("52W High")), f(row.get("52W Low"))
    from_high = f(row.get("Dist_52W_High%"))
    if from_high is None and price and high:
        from_high = (price / high - 1) * 100.0
    from_low = f(row.get("Pct_From_52W_Low%"))
    if from_low is None and price and low:
        from_low = (price / low - 1) * 100.0

    position = None
    if price is not None and high is not None and low is not None and high > low:
        position = max(0.0, min(100.0, (price - low) / (high - low) * 100.0))

    return {
        "high": high, "low": low, "price": price,
        "from_high_pct": None if from_high is None else round(from_high, 1),
        "from_low_pct": None if from_low is None else round(from_low, 1),
        "position_pct": None if position is None else round(position, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SUPPORT CONFLUENCE — §8. How many independent levels agree.
# ─────────────────────────────────────────────────────────────────────────────
# The weights are the framework's. What matters more than the weights is
# what each one is allowed to count: only levels price is currently holding
# above (see _supports), so the score cannot be run up by a stock in free
# fall passing through four averages at once.

CONFLUENCE_POINTS = (
    ("8/21 EMA", 20),
    ("50 MA", 25),
    ("200 MA", 25),
    ("Prior breakout", 15),
    ("High-volume level", 10),
    ("Key-level confluence", 5),
)


def compute_support_confluence(row: dict) -> dict:
    """
    Returns {"score": 0-100, "label", "hits": [...], "misses": [...]}.

    Unlike the other scores in this package this one does NOT renormalise
    over measured weight, and that is deliberate. Confluence is a count of
    confirmations present; a level that could not be measured is a
    confirmation you do not have, which is the same practical position as
    one that is absent. Renormalising would let a row with two of six
    inputs measured score 100 for a single agreement.
    """
    price = _price(row)
    tol = _tolerance(row)
    hits, misses = [], []
    score = 0

    def award(name, points, ok, detail):
        nonlocal score
        if ok:
            score += points
            hits.append({"name": name, "points": points, "detail": detail})
        else:
            misses.append({"name": name, "points": points, "detail": detail})

    # 8/21 EMA — either one holding counts once, not twice. They are the
    # same short-term signal at two lookbacks.
    ok8, d8 = _supports(price, f(row.get("8EMA")), tol)
    ok21, d21 = _supports(price, f(row.get("21EMA")), tol)
    best = min((d for d, ok in ((d8, ok8), (d21, ok21)) if ok),
               default=None)
    award("8/21 EMA", 20, ok8 or ok21,
          f"holding, {best:+.1f}% above" if best is not None
          else "price is not on the short-term averages")

    ok50, d50 = _supports(price, f(row.get("50MA")), tol)
    award("50 MA", 25, ok50,
          f"holding, {d50:+.1f}% above" if ok50
          else ("below it" if d50 is not None and d50 < 0
                else f"{d50:+.1f}% away" if d50 is not None else "no 50 MA"))

    ok200, d200 = _supports(price, f(row.get("200MA")), tol)
    award("200 MA", 25, ok200,
          f"holding, {d200:+.1f}% above" if ok200
          else ("below it" if d200 is not None and d200 < 0
                else f"{d200:+.1f}% away" if d200 is not None else "no 200 MA"))

    okbo, dbo = _supports(price, f(row.get("Prior_Breakout_Level")), tol)
    award("Prior breakout", 15, okbo,
          f"retesting the breakout, {dbo:+.1f}% above" if okbo
          else ("breakout level lost" if dbo is not None and dbo < 0
                else "not at the prior breakout"))

    # A level the market traded heavily at is a level the market remembers.
    # Volume_Confirmation and Touches come from core/key_levels.
    s1 = f(row.get("S1"))
    oks1, ds1 = _supports(price, s1, tol)
    vol_conf = b(row.get("Volume_Confirmation"))
    award("High-volume level", 10, bool(oks1 and vol_conf),
          f"volume-confirmed support at ${s1:,.2f}" if oks1 and vol_conf
          else ("support found but not volume-confirmed" if oks1
                else "no volume-confirmed level here"))

    # The fifth point is for genuine agreement between an independently
    # derived level (key_levels' swing/volume-profile S1) and a moving
    # average — two different methods pointing at the same price.
    touches = f(row.get("Touches"))
    ma_near_s1 = False
    if s1 is not None:
        for key in ("8EMA", "21EMA", "50MA", "200MA"):
            lv = f(row.get(key))
            if lv and abs(lv / s1 - 1) * 100 <= tol:
                ma_near_s1 = True
                break
    award("Key-level confluence", 5, bool(oks1 and ma_near_s1),
          f"S1 ${s1:,.2f} coincides with a moving average"
          f"{f' ({touches:.0f} touches)' if touches else ''}"
          if oks1 and ma_near_s1 else "no independent level agrees here")

    n_hits = len(hits)
    label = next(name for floor, name in CONFLUENCE_BANDS if n_hits >= floor)
    return {"score": score, "label": label, "hits": hits, "misses": misses,
            # The headline number. `score` is kept because WHICH levels agree
            # still matters — a 50 MA plus 200 MA agreement is worth more than
            # the 8/21 EMA plus a key level, and both are two hits — but it
            # ranks within a count rather than replacing it.
            "agreeing": n_hits, "possible": len(CONFLUENCE_POINTS)}


# ─────────────────────────────────────────────────────────────────────────────
# PULLBACK VOLUME — §10. Is this a rest or a run for the exit?
# ─────────────────────────────────────────────────────────────────────────────

VOLUME_POINTS = (
    ("Volume below 20-day average", 20),
    ("Volume declining into the pullback", 20),
    ("No recent distribution", 20),
    ("Bullish volume reversal", 20),
    ("Accumulation at support", 20),
)


def compute_pullback_volume(row: dict) -> dict:
    """
    Returns {"score": 0-100|None, "label", "hits", "misses", "unknown",
             "measured"}.

    Renormalised over the checks that had data — unlike confluence, because
    here a missing input really is unknown rather than absent: a row without
    a distribution-day count has not been shown to be distributing.
    `measured` reports how many of the five actually answered, so a 100 from
    two checks is legible as the weaker claim it is.
    """
    vs20 = f(row.get("Vol_vs_20D"))
    pull_ratio = f(row.get("Pullback_Vol_Ratio"))
    drying = b(row.get("VolumeDryingUp"))
    dist_days = f(row.get("Distribution_Days_25d"))
    reversal = row.get("Reversal_Candle")
    rvol = f(row.get("RVOL"))

    hits, misses, unknown = [], [], []
    earned, possible = 0, 0

    def check(name, points, ok, detail):
        nonlocal earned, possible
        if ok is None:
            unknown.append({"name": name, "points": points, "detail": detail})
            return
        possible += points
        if ok:
            earned += points
            hits.append({"name": name, "points": points, "detail": detail})
        else:
            misses.append({"name": name, "points": points, "detail": detail})

    check("Volume below 20-day average", 20,
          None if vs20 is None else vs20 < 1.0,
          "no volume ratio" if vs20 is None else f"{vs20:.2f}× the 20-day average")

    check("Volume declining into the pullback", 20,
          None if pull_ratio is None else pull_ratio <= 0.9,
          "no pullback volume ratio" if pull_ratio is None
          else f"pullback volume {pull_ratio:.2f}× normal")

    # A distribution day is a down session on above-average volume — one is
    # noise, a cluster is institutions leaving.
    check("No recent distribution", 20,
          None if dist_days is None else dist_days <= 2,
          "not measured" if dist_days is None
          else f"{dist_days:.0f} distribution days in the last 25 sessions")

    # The reversal is the trigger, and volume is what makes it credible: a
    # hammer on 0.4× volume is a quiet day, not a decision by anyone.
    if reversal is None:
        check("Bullish volume reversal", 20, None, "candle pattern not measured")
    else:
        pattern = str(reversal).strip()
        bullish = bool(pattern) and pattern.lower() not in ("none", "false", "")
        if not bullish:
            check("Bullish volume reversal", 20, False, "no reversal candle")
        elif rvol is None:
            check("Bullish volume reversal", 20, None,
                  f"{pattern} but volume unknown")
        else:
            check("Bullish volume reversal", 20, rvol >= 1.0,
                  f"{pattern} on {rvol:.2f}× volume")

    check("Accumulation at support", 20,
          None if drying is None else bool(drying),
          "not measured" if drying is None
          else ("volume drying up into the level" if drying
                else "volume not contracting"))

    if not possible:
        return {"score": None, "label": None, "hits": hits, "misses": misses,
                "unknown": unknown, "measured": 0}

    score = int(round(earned / possible * 100))
    label = next(name for floor, name in VOLUME_BANDS if score >= floor)
    return {"score": score, "label": label, "hits": hits, "misses": misses,
            "unknown": unknown, "measured": len(hits) + len(misses)}


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY READINESS — "is now the moment", scored separately from "is this
# support"
# ─────────────────────────────────────────────────────────────────────────────
# Support confluence asks how many levels agree at this price. Entry
# readiness asks whether the conditions for acting are actually present:
# the level, the volume behaviour, the reversal, the market. A name can have
# excellent confluence and zero readiness — sitting on a great level while
# selling is still accelerating — and those must not collapse into one
# number, because the first tells you WHERE and the second tells you WHEN.

READINESS_BANDS = ((80, "🔥 Buy"), (65, "🟢 Buy on confirmation"),
                   (50, "🟡 Watch support"), (0, "🔴 Wait"))

# Weights. "Moving-average support" is ONE slot covering the 8/21 EMA, the
# 50 MA and the 200 MA, awarded for whichever price is actually resting on.
#
# Scored as separate 15-point rows for "Near 50 MA" and "Near 200 MA" — the
# obvious transcription — the top band is unreachable by construction,
# because price cannot be at both at once. That capped a Stage 1 EMA
# pullback at 70 and a deep pullback at 70, so "🔥 Buy" could only ever be
# reached by a stock sitting exactly on its 50 MA. There was also no row at
# all for the 8/21 EMA, which is the framework's own Entry 1. Collapsing
# them into one mutually-exclusive slot and adding the missing rung fixes
# both without touching any other weight.
READINESS_CHECKS = (
    ("At major support", 25),
    ("Moving-average support", 15),
    ("Prior breakout support", 15),
    ("Volume contraction", 10),
    ("Bullish reversal", 10),
    ("Relative strength stabilising", 5),
    ("Market supportive", 5),
)
# What a perfect setup can earn. The reported score is rescaled to 0-100
# against this so the framework's 80/65/50 band boundaries mean what they
# say; `earned` and `possible` are returned raw for anyone checking.
READINESS_MAX = sum(w for _n, w in READINESS_CHECKS)

# Nearest first — the order proximity is tested in, so a stock at the 8 EMA
# is credited for the EMA rather than for a 200 MA far below it.
_READINESS_LEVELS = (("8EMA", "8 EMA"), ("21EMA", "21 EMA"),
                     ("50MA", "50 MA"), ("200MA", "200 MA"))


def compute_entry_readiness(row: dict, pullback: dict, rs: dict,
                            regime: str | None = None) -> dict:
    """
    0-100 with the framework's weights. Returns {"score", "label", "hits",
    "misses", "unknown"}.

    Not renormalised: a confirmation that could not be measured is a
    confirmation you do not have, and this score exists to decide whether to
    act now. Unknowns are listed so the gap is visible rather than inferred
    from a low number.
    """
    hits, misses, unknown = [], [], []
    score = 0

    def award(name, points, ok, detail):
        nonlocal score
        entry = {"name": name, "points": points, "detail": detail}
        if ok is None:
            unknown.append(entry)
        elif ok:
            score += points
            hits.append(entry)
        else:
            misses.append(entry)

    by_level = pullback.get("by_level") or {}
    supports = pullback.get("supports") or {}
    tol = pullback.get("tolerance_pct") or MIN_TOLERANCE_PCT

    # "At major support" is the volume-confirmed shelf the key-level engine
    # found, not simply the nearest moving average — the whole point of the
    # 25-point weight is that the market has defended this price before.
    near = supports.get("near")
    at_major = bool(near and near.get("kind") == "key_level"
                    and near.get("volume_confirmed")
                    and abs(near["distance_pct"]) <= tol)
    award("At major support", 25, at_major,
          (f"{near['name']} at ${near['price']:,.2f}, "
           f"{near['distance_pct']:+.1f}% away" if near
           else "no volume-confirmed level beneath price"))

    def near_level(key):
        lv = by_level.get(key) or {}
        d = lv.get("distance_pct")
        if d is None:
            return None, None, None
        return abs(d) <= tol, d, lv.get("price")

    # One slot, awarded for whichever moving average price is actually on.
    resting, measured = None, False
    for key, label in _READINESS_LEVELS:
        ok, dist, level_price = near_level(key)
        if ok is None:
            continue
        measured = True
        if ok:
            resting = (label, dist, level_price)
            break
    if not measured:
        award("Moving-average support", 15, None, "no moving averages")
    elif resting:
        label, dist, level_price = resting
        award("Moving-average support", 15, True,
              f"at the {label}" + (f" (${level_price:,.2f}, {dist:+.1f}%)"
                                   if level_price else ""))
    else:
        award("Moving-average support", 15, False,
              "not resting on any moving average")

    ok, dist, level_price = near_level("Prior_Breakout_Level")
    award("Prior breakout support", 15, ok,
          "no prior breakout level" if ok is None
          else (f"retesting ${level_price:,.2f} ({dist:+.1f}%)" if ok
                else f"{dist:+.1f}% away"))

    vs20 = f(row.get("Vol_vs_20D"))
    drying = b(row.get("VolumeDryingUp"))
    pull_ratio = f(row.get("Pullback_Vol_Ratio"))
    if vs20 is None and drying is None and pull_ratio is None:
        award("Volume contraction", 10, None, "no volume data")
    else:
        contracting = bool((drying is True)
                           or (vs20 is not None and vs20 < 1.0)
                           or (pull_ratio is not None and pull_ratio <= 0.9))
        bits = []
        if vs20 is not None:
            bits.append(f"{vs20:.2f}x the 20-day average")
        if pull_ratio is not None:
            bits.append(f"pullback volume {pull_ratio:.2f}x")
        award("Volume contraction", 10, contracting,
              "; ".join(bits) or "volume not contracting")

    reversal = row.get("Reversal_Candle")
    if reversal is None:
        award("Bullish reversal", 10, None, "candle not measured")
    else:
        pattern = str(reversal).strip()
        found = bool(pattern) and pattern.lower() not in ("none", "false")
        award("Bullish reversal", 10, found,
              pattern if found else "no reversal candle yet")

    rs_score = rs.get("score")
    award("Relative strength stabilising", 5,
          None if rs_score is None else rs_score >= 40,
          "no relative strength data" if rs_score is None
          else rs.get("detail") or f"rank {rs_score:.0f}")

    reg = str(regime or "").upper()
    award("Market supportive", 5,
          None if reg not in ("FAVORABLE", "SELECTIVE", "DEFENSIVE")
          else reg != "DEFENSIVE",
          f"regime {reg}" if reg else "regime unknown")

    scaled = int(round(score / READINESS_MAX * 100)) if READINESS_MAX else 0
    label = next(name for floor, name in READINESS_BANDS if scaled >= floor)
    return {"score": scaled, "label": label, "earned": score,
            "possible": READINESS_MAX, "hits": hits, "misses": misses,
            "unknown": unknown}


# ─────────────────────────────────────────────────────────────────────────────
# RELATIVE STRENGTH — §9
# ─────────────────────────────────────────────────────────────────────────────

def relative_strength(row: dict) -> dict:
    """Market-wide RS rank plus, when the universe supplied it, the rank
    within the stock's own sector.

    Both matter and they say different things: a semiconductor at the 55th
    percentile of the whole market during a semiconductor rout may be the
    strongest name in its group. `Sector_RS_Rank` is attached by
    engine.evaluate_universe(); it cannot be computed from one row.
    """
    market = f(row.get("RS_Rank"))
    sector = f(row.get("Sector_RS_Rank"))
    parts = []
    if market is not None:
        parts.append(f"market rank {market:.0f}")
    if sector is not None:
        parts.append(f"sector rank {sector:.0f}")
    # Both are percentiles, so averaging them is meaningful where both exist.
    have = [v for v in (market, sector) if v is not None]
    score = sum(have) / len(have) if have else None
    return {"score": None if score is None else round(score),
            "market_rank": market, "sector_rank": sector,
            "detail": " · ".join(parts) or "no relative strength data",
            "strong": None if score is None else score >= 70}


def technical_sub_score(trend: dict, pullback: dict, confluence: dict,
                        volume: dict, rs: dict) -> float | None:
    """The 25% technical leg of the composite LT score.

    Trend and confluence carry the most weight because they are the two the
    framework treats as preconditions rather than preferences. The pullback
    term scores being AT a level at all — a stock with perfect trend and
    volume that is nowhere near an entry should not score as a ready setup.
    """
    parts = []
    if trend.get("score") is not None:
        parts.append((35, float(trend["score"])))
    if confluence.get("score") is not None:
        parts.append((25, float(confluence["score"])))
    if volume.get("score") is not None:
        parts.append((15, float(volume["score"])))
    if rs.get("score") is not None:
        parts.append((15, float(rs["score"])))
    zone = pullback.get("zone")
    if zone is not None:
        parts.append((10, 0.0 if zone == "NONE" else 100.0))
    if not parts:
        return None
    total = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / total
