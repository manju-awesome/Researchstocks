"""
screen.py — rules over the Long-Term Buy Engine's own columns
=============================================================
Lets the /longterm page filter on what the engine computed — LQuality, the
valuation band, trend state, pullback stage, entry readiness, the S1/R1
levels — the same way /screener filters the research library.

It reuses core.screener's rule engine rather than growing a second one.
That engine is already a well-tested Condition/Group evaluator with
operators, per-condition explanations and match scoring; the only thing it
lacked was a description of these fields and rows shaped to match. So this
module supplies exactly two things:

    LONGTERM_FIELDS   Field specs for the engine's outputs
    flatten()         one evaluate() result -> one flat screenable row

Why the fields register into FIELD_BY_KEY but not into FIELDS
--------------------------------------------------------------
core.screener resolves a rule's field through FIELD_BY_KEY, and separately
iterates FIELDS to build the /screener picker and its natural-language
autocomplete. Those are different jobs, and here they need different answers.

Registering into the lookup makes the rule engine understand `lquality >=
85`. NOT registering into FIELDS keeps these fields out of the /screener
page — where they would appear as options over a universe that has no values
for them, so every rule would come back "no data" for all 545 rows. A field
offered in a picker that cannot match anything is worse than an absent one.

The nesting is the whole point of the flattening
------------------------------------------------
evaluate() returns a deliberately nested result — quality, valuation, trend
and pullback each keep their own sub-scores, coverage and reasoning, because
the reasoning panel needs all of it. A rule engine wants scalars. flatten()
is the seam, and it is the only place that knows both shapes.
"""

from __future__ import annotations

from stockanalysis.core import screener as S
from stockanalysis.core.longterm import engine as E
from stockanalysis.core.longterm import quality as Q
from stockanalysis.core.longterm import technicals as T
from stockanalysis.core.longterm import valuation as V

NUM, BOOL, ENUM = S.NUM, S.BOOL, S.ENUM
UP, DOWN = S.UP, S.DOWN

TIER_VALUES = tuple(name for _floor, name in Q.TIERS)
BAND_VALUES = V.BANDS
CONFIDENCE_VALUES = ("HIGH", "MODERATE", "LOW")
METHOD_VALUES = ("REVERSE_DCF", "PEER")
TREND_VALUES = T.TREND_STATES
STAGE_VALUES = T.STAGES
ACTION_VALUES = E.ACTIONS
INSIDER_VALUES = tuple(name for _floor, name in Q.INSIDER_BANDS)

# `src` is the key flatten() writes. Kept identical to `key` throughout so
# there is one name per concept — the screener allows them to differ and that
# freedom has no use here.
LONGTERM_FIELDS: tuple[S.Field, ...] = (
    # ── Business quality ────────────────────────────────────────────────────
    S.Field("lquality", "LQuality", "Quality", NUM, "lquality", "", UP,
            hint="The engine's own 100-point business score", decimals=0),
    S.Field("lq_tier", "Quality tier", "Quality", ENUM, "lq_tier",
            values=TIER_VALUES, hint="Elite / High Quality / Watchlist / Reject"),
    S.Field("lq_coverage", "Quality coverage", "Quality", NUM, "lq_coverage",
            "%", UP, hint="Share of factor weight that had data", decimals=0),
    S.Field("insider", "Insider signal", "Quality", ENUM, "insider",
            values=INSIDER_VALUES,
            hint="Reported beside the verdict, never inside LQuality"),

    # ── Valuation ───────────────────────────────────────────────────────────
    S.Field("valuation_band", "Valuation", "Valuation", ENUM, "valuation_band",
            values=BAND_VALUES, hint="Undervalued / Fair / Overvalued"),
    S.Field("valuation_method", "Valuation method", "Valuation", ENUM,
            "valuation_method", values=METHOD_VALUES,
            hint="Reverse DCF where cash flows allow, else a peer multiple"),
    S.Field("valuation_confidence", "Valuation confidence", "Valuation", ENUM,
            "valuation_confidence", values=CONFIDENCE_VALUES),
    S.Field("implied_growth", "Implied growth", "Valuation", NUM,
            "implied_growth", "%", DOWN,
            hint="FCF growth the current price already requires", decimals=0),
    S.Field("delivered_growth", "Delivered growth", "Valuation", NUM,
            "delivered_growth", "%", UP, decimals=0),
    S.Field("growth_gap", "Growth gap", "Valuation", NUM, "growth_gap", "pp",
            DOWN, hint="Implied minus delivered — negative is cheap",
            decimals=0),
    S.Field("upside", "Upside to fair value", "Valuation", NUM, "upside", "%",
            UP, hint="Peer method only", decimals=0),

    # ── Trend & stage ───────────────────────────────────────────────────────
    S.Field("trend_state", "Trend state", "Trend", ENUM, "trend_state",
            values=TREND_VALUES, hint="Confirmed / Partial / Broken"),
    S.Field("trend_score", "Trend score", "Trend", NUM, "trend_score", "",
            UP, hint="Points confirmed out of 100", decimals=0),
    S.Field("trend_unknown", "Trend unmeasured", "Trend", NUM,
            "trend_unknown", "", DOWN,
            hint="Points that could not be checked", decimals=0),
    S.Field("stage", "Pullback stage", "Trend", ENUM, "stage",
            values=STAGE_VALUES,
            hint="Stage 1 EMA / 2 50MA / 3 deep / 4 breakdown"),
    S.Field("extended", "Extended", "Trend", BOOL, "extended",
            hint="More than 4% above the 8 EMA"),

    # ── Levels ──────────────────────────────────────────────────────────────
    S.Field("s1_price", "S1 support price", "Levels", NUM, "s1_price", "$",
            None, decimals=2),
    S.Field("s1_distance", "S1 support distance", "Levels", NUM,
            "s1_distance", "%", None,
            hint="Negative — how far below the price support sits",
            decimals=1),
    S.Field("s1_tested", "S1 is tested support", "Levels", BOOL, "s1_tested",
            hint="A volume-confirmed shelf, not a derived moving average"),
    S.Field("s1_touches", "S1 touches", "Levels", NUM, "s1_touches", "", UP,
            decimals=0),
    S.Field("r1_price", "R1 resistance price", "Levels", NUM, "r1_price", "$",
            None, decimals=2),
    S.Field("r1_distance", "R1 resistance distance", "Levels", NUM,
            "r1_distance", "%", UP,
            hint="Positive — headroom before price meets sellers",
            decimals=1),
    S.Field("r1_tested", "R1 is tested resistance", "Levels", BOOL,
            "r1_tested"),
    S.Field("headroom_ratio", "Headroom vs downside", "Levels", NUM,
            "headroom_ratio", "x", UP,
            hint="Distance to R1 divided by distance to S1", decimals=2),
    S.Field("lt_pct_vs_8ema", "Distance from 8 EMA", "Levels", NUM,
            "lt_pct_vs_8ema", "%", None, decimals=1),
    S.Field("lt_pct_vs_21ema", "Distance from 21 EMA", "Levels", NUM,
            "lt_pct_vs_21ema", "%", None, decimals=1),
    S.Field("lt_pct_vs_50ma", "Distance from 50 MA", "Levels", NUM,
            "lt_pct_vs_50ma", "%", None, decimals=1),
    S.Field("lt_pct_vs_200ma", "Distance from 200 MA", "Levels", NUM,
            "lt_pct_vs_200ma", "%", None, decimals=1),

    # ── Entry ───────────────────────────────────────────────────────────────
    S.Field("readiness", "Entry readiness", "Entry", NUM, "readiness", "", UP,
            hint="Is now the moment — level, volume, reversal, market",
            decimals=0),
    S.Field("confluence_hits", "Levels agreeing", "Entry", NUM,
            "confluence_hits", "", UP, hint="Of 6 — the buy gate needs 2",
            decimals=0),
    S.Field("confluence_score", "Support confluence", "Entry", NUM,
            "confluence_score", "", UP, decimals=0),
    S.Field("volume_score", "Pullback volume", "Entry", NUM, "volume_score",
            "", UP, hint="Accumulation vs distribution", decimals=0),
    S.Field("reversal", "Bullish reversal", "Entry", BOOL, "reversal"),

    # ── Verdict ─────────────────────────────────────────────────────────────
    S.Field("action", "Action", "Verdict", ENUM, "action",
            values=ACTION_VALUES),
    S.Field("gate", "Stopped at gate", "Verdict", ENUM, "gate",
            values=("quality", "valuation", "trend", "regime", "earnings",
                    "entry", "support", "readiness", "trigger", "confirmed")),
    S.Field("lt_score", "LT score", "Verdict", NUM, "lt_score", "", UP,
            hint="Ranks names that already passed the gates", decimals=0),
    S.Field("tranche", "Tranche size", "Verdict", NUM, "tranche", "%", UP,
            decimals=0),

    # ── Context ─────────────────────────────────────────────────────────────
    S.Field("lt_price", "Price", "Context", NUM, "lt_price", "$", None,
            decimals=2),
    S.Field("lt_rs_rank", "RS rank", "Context", NUM, "lt_rs_rank", "", UP,
            decimals=0),
    S.Field("lt_sector_rs", "Sector RS rank", "Context", NUM, "lt_sector_rs",
            "", UP, hint="Rank within its own sector", decimals=0),
    S.Field("lt_days_to_earnings", "Days to earnings", "Context", NUM,
            "lt_days_to_earnings", "", None, decimals=0),
    S.Field("lt_sector", "Sector", "Context", ENUM, "lt_sector",
            values=("Technology", "Healthcare", "Financial Services",
                    "Consumer Cyclical", "Consumer Defensive", "Industrials",
                    "Energy", "Utilities", "Real Estate", "Basic Materials",
                    "Communication Services")),
)

LONGTERM_FIELD_BY_KEY = {f.key: f for f in LONGTERM_FIELDS}

# Make the shared rule engine able to resolve these keys. Deliberately does
# NOT touch S.FIELDS — see the module docstring.
S.FIELD_BY_KEY.update(LONGTERM_FIELD_BY_KEY)

FIELD_GROUPS = ("Quality", "Valuation", "Trend", "Levels", "Entry", "Verdict",
                "Context")


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def flatten(result: dict) -> dict:
    """One evaluate() result -> a flat row core.screener can test.

    Keeps `_result` so the caller can render the full nested verdict for
    whatever survives the filter, rather than re-running the engine.
    """
    q = result.get("quality") or {}
    v = result.get("valuation") or {}
    t = result.get("trend") or {}
    p = result.get("pullback") or {}
    conf = result.get("confluence") or {}
    vol = result.get("volume") or {}
    rs = result.get("rs") or {}
    ready = result.get("readiness") or {}
    ins = result.get("insider") or {}
    bz = p.get("buy_zone") or {}
    rz = p.get("resistance") or {}
    by = p.get("by_level") or {}

    def level_pct(key):
        return _num((by.get(key) or {}).get("distance_pct"))

    s1_dist, r1_dist = _num(bz.get("distance_pct")), _num(rz.get("distance_pct"))
    # Headroom against downside — how much room to the first overhead level
    # per unit of give-back to the first support. Only meaningful when the
    # levels straddle the price, which is the normal case; when support sits
    # above or resistance below, the ratio would invert its own meaning.
    headroom = None
    if s1_dist is not None and r1_dist is not None and s1_dist < 0 < r1_dist:
        headroom = round(r1_dist / abs(s1_dist), 2)

    return {
        "ticker": result.get("ticker"),
        "name": result.get("name"),
        "_result": result,

        "lquality": _num(q.get("score")),
        "lq_tier": q.get("tier"),
        "lq_coverage": None if q.get("coverage") is None
                       else round(q["coverage"] * 100),
        "insider": ins.get("label"),

        "valuation_band": v.get("band"),
        "valuation_method": v.get("method"),
        "valuation_confidence": v.get("confidence"),
        "implied_growth": _num(v.get("implied_growth_pct")),
        "delivered_growth": _num(v.get("delivered_growth_pct")),
        "growth_gap": _num(v.get("growth_gap_pp")),
        "upside": _num(v.get("upside_pct")),

        "trend_state": t.get("state"),
        "trend_score": _num(t.get("score")),
        "trend_unknown": _num(t.get("unknown_points")),
        "stage": p.get("stage"),
        "extended": p.get("extended"),

        "s1_price": _num(bz.get("price")),
        "s1_distance": s1_dist,
        "s1_tested": bz.get("actual_support"),
        "s1_touches": _num(bz.get("touches")),
        "r1_price": _num(rz.get("price")),
        "r1_distance": r1_dist,
        "r1_tested": rz.get("actual_resistance"),
        "headroom_ratio": headroom,
        "lt_pct_vs_8ema": level_pct("8EMA"),
        "lt_pct_vs_21ema": level_pct("21EMA"),
        "lt_pct_vs_50ma": level_pct("50MA"),
        "lt_pct_vs_200ma": level_pct("200MA"),

        "readiness": _num(ready.get("score")),
        "confluence_hits": _num(conf.get("agreeing")),
        "confluence_score": _num(conf.get("score")),
        "volume_score": _num(vol.get("score")),
        "reversal": _reversal_flag(result),

        "action": result.get("action"),
        "gate": result.get("gate"),
        "lt_score": _num(result.get("lt_score")),
        "tranche": _num(result.get("tranche_pct")),

        "lt_price": _num(result.get("price")),
        "lt_rs_rank": _num(rs.get("market_rank")),
        "lt_sector_rs": _num(rs.get("sector_rank")),
        "lt_days_to_earnings": _num(result.get("days_to_earnings")),
        "lt_sector": result.get("sector"),
    }


def _reversal_flag(result) -> bool | None:
    """True/False when the candle was measured, None when it was not.

    The readiness check already draws this distinction; reading it back off
    that result keeps one source of truth rather than re-parsing the raw
    column here.
    """
    ready = result.get("readiness") or {}
    for bucket, value in (("hits", True), ("misses", False),
                          ("unknown", None)):
        for item in ready.get(bucket) or []:
            if item.get("name") == "Bullish reversal":
                return value
    return None


# ─────────────────────────────────────────────────────────────────────────────
# RULE PARSING — rules live in the URL, like the rest of this page
# ─────────────────────────────────────────────────────────────────────────────
# "lquality:gte:85" — field, operator, value. The /screener page posts a JSON
# rule tree because it has a nested AND/OR builder; this page has a flat list,
# and a flat list in the query string keeps every filtered view a shareable
# link and the back button honest.

def parse_rule(text: str) -> S.Condition | None:
    """"lquality:gte:85" -> Condition. None when unparseable, so one bad
    rule in a pasted URL drops itself rather than erroring the page."""
    parts = (text or "").split(":")
    if len(parts) < 2:
        return None
    key, op = parts[0].strip(), parts[1].strip().lower()
    spec = LONGTERM_FIELD_BY_KEY.get(key)
    if spec is None or op not in S.OPS_FOR_KIND.get(spec.kind, ()):
        return None
    raw = ":".join(parts[2:]).strip() if len(parts) > 2 else ""
    value: object = raw
    value2 = None
    if spec.kind == NUM:
        if op == "between":
            lo, _, hi = raw.partition(",")
            value, value2 = _num(lo), _num(hi)
            if value is None or value2 is None:
                return None
        else:
            value = _num(raw)
            if value is None:
                return None
    elif spec.kind == BOOL:
        value = raw.lower() in ("1", "true", "yes", "y")
    return S.Condition(field=key, op=op, value=value, value2=value2)


def parse_rules(texts, op: str = "AND") -> S.Group:
    conds = [c for c in (parse_rule(t) for t in (texts or [])) if c]
    return S.Group(op="OR" if str(op).upper() == "OR" else "AND", items=conds)


def describe(cond: S.Condition) -> str:
    """A rule as a sentence, for the pill."""
    spec = LONGTERM_FIELD_BY_KEY.get(cond.field)
    if spec is None:
        return cond.field
    words = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<", "eq": "is",
             "ne": "is not", "between": "between", "within": "within",
             "in": "in", "has": "has"}
    op = words.get(cond.op, cond.op)
    if spec.kind == BOOL:
        return f"{spec.label} {'yes' if cond.value else 'no'}"
    if cond.op == "between":
        return (f"{spec.label} between {spec.format(cond.value)} and "
                f"{spec.format(cond.value2)}")
    return f"{spec.label} {op} {spec.format(cond.value)}"


def apply_rules(results, rule_texts, op: str = "AND", sort: str = "lt_score"):
    """Filter engine results by the rules. Returns (kept, conditions, stats).

    `stats` is core.screener's per-condition breakdown — how many rows each
    rule passed and how many had no data for it — which is what turns "0
    matches" from a dead end into a diagnosis.
    """
    conds = [c for c in (parse_rule(t) for t in (rule_texts or [])) if c]
    if not conds:
        return list(results), [], []
    group = S.Group(op="OR" if str(op).upper() == "OR" else "AND",
                    items=list(conds))
    rows = [flatten(r) for r in results]
    stats = S.condition_stats(rows, group)
    kept = []
    for row in rows:
        if S.eval_group(row, group, []):
            kept.append(row["_result"])
    return kept, conds, stats


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS — the screens a long-only quality manager actually runs
# ─────────────────────────────────────────────────────────────────────────────
# Grouped by the question being asked, because that is the order the work
# happens in: decide what deserves to be owned, then decide when to buy it,
# then check what would stop you. That is the framework's own hierarchy, and
# a preset list organised by field type instead would scatter it.
#
# Every preset below was measured against the live 545-row library and its
# count recorded in `note`. That is not decoration — three separate features
# in this engine were first built with thresholds that were empty by
# construction (the forward DCF, the confluence gate, the readiness bands),
# and a preset that returns nothing on every library is indistinguishable
# from a broken one.
#
# `needs_statements` marks the four screens that depend on the annual
# cash-flow and income statements. Those columns are 0% covered until a scan
# runs core.longterm.fundamentals, so these presets return nothing today —
# not because the rules are wrong but because the reverse DCF has no inputs
# and every valuation is falling back to a peer multiple. The UI says so
# rather than showing a bare zero.

PRESET_GROUPS = ("What to own", "When to buy", "What would stop me")

PRESETS: tuple[dict, ...] = (
    # ── What to own ─────────────────────────────────────────────────────────
    {"key": "quality_at_discount", "icon": "💎", "name": "Quality at a Discount",
     "group": "What to own", "desc": "The core screen: an elite business, not overpriced, trend not "
             "broken. Everything else here is a refinement of this one.",
     "rules": ["lquality:gte:85", "valuation_band:ne:OVERVALUED",
               "trend_state:ne:BROKEN"]},
    {"key": "wide_moat_cheap", "icon": "🏰", "name": "Wide Moat, Undervalued",
     "group": "What to own", "desc": "Top-decile quality trading below what the model says it is "
             "worth. Rare by design — if this list is long, check the "
             "valuation method before believing it.",
     "rules": ["lquality:gte:90", "valuation_band:eq:UNDERVALUED"]},
    {"key": "cashflow_verified", "icon": "🧾", "name": "Cash-Flow Verified Value",
     "group": "What to own", "needs_statements": True,
     "desc": "Undervalued on a reverse DCF built from filed statements, not "
             "on a peer multiple. The strongest valuation claim this engine "
             "can make.",
     "rules": ["valuation_method:eq:REVERSE_DCF",
               "valuation_confidence:eq:HIGH",
               "valuation_band:eq:UNDERVALUED"]},
    {"key": "garp", "icon": "📐", "name": "Growth at a Reasonable Price",
     "group": "What to own", "needs_statements": True,
     "desc": "Compounding at 15%+ while the price demands little more than "
             "that. The gap between implied and delivered growth is the "
             "whole test.",
     "rules": ["delivered_growth:gte:15", "growth_gap:lte:10",
               "lquality:gte:75"]},
    {"key": "sector_leaders", "icon": "🥇", "name": "Sector Leaders",
     "group": "What to own", "desc": "Top-quintile relative strength inside its OWN sector — a name "
             "leading its group while the group lags still leads.",
     "rules": ["lt_sector_rs:gte:80", "lquality:gte:85"]},

    # ── When to buy ─────────────────────────────────────────────────────────
    {"key": "ready_to_deploy", "icon": "🟢", "name": "Ready to Deploy",
     "group": "When to buy", "desc": "Entry readiness 65+ on a quality business — the level, the "
             "volume and the market all lining up now rather than eventually.",
     "rules": ["readiness:gte:65", "lquality:gte:85"]},
    {"key": "compounder_pullback", "icon": "🎯", "name": "Compounder Pullback",
     "group": "When to buy", "desc": "Stage 1: quality resting on the 8/21 EMA with a tested shelf "
             "underneath. The shallow, high-momentum entry.",
     "rules": ["lquality:gte:85", "stage:eq:STAGE1_EMA", "s1_tested:eq:true"]},
    {"key": "fifty_ma_entry", "icon": "🎣", "name": "50 MA Pullback",
     "group": "When to buy", "desc": "Stage 2 — the framework's preferred core entry for a quality "
             "name, and the only stage where every readiness point is "
             "reachable.",
     "rules": ["lquality:gte:85", "stage:eq:STAGE2_50MA"]},
    {"key": "deep_pullback_quality", "icon": "🪂", "name": "Deep Pullback in Quality",
     "group": "When to buy", "desc": "Elite businesses well below the 50 MA but still above the 200 "
             "MA, structure intact. Not a buy — a list to work support on.",
     "rules": ["lq_tier:eq:Elite", "stage:eq:STAGE3_DEEP",
               "trend_state:ne:BROKEN"]},
    {"key": "asymmetric_entry", "icon": "⚖️", "name": "Asymmetric Entry",
     "group": "When to buy", "desc": "Twice as much headroom to the first resistance as give-back to "
             "a TESTED support. Position sizing writes itself.",
     "rules": ["headroom_ratio:gte:2", "s1_tested:eq:true",
               "lquality:gte:85"]},
    {"key": "accumulation", "icon": "🧲", "name": "Quiet Accumulation",
     "group": "When to buy", "desc": "Pullback volume drying up while relative strength holds — the "
             "shape of institutions buying rather than retail selling.",
     "rules": ["volume_score:gte:60", "lt_rs_rank:gte:60",
               "lquality:gte:80"]},

    # ── What would stop me ──────────────────────────────────────────────────
    {"key": "priced_for_perfection", "icon": "🎈", "name": "Priced for Perfection",
     "group": "What would stop me", "needs_statements": True,
     "desc": "Great businesses whose price already requires 35%+ FCF growth "
             "for five years. The most expensive mistake in a quality "
             "portfolio is a quality company.",
     "rules": ["lquality:gte:85", "implied_growth:gte:35"]},
    {"key": "fallen_quality", "icon": "🩺", "name": "Fallen Quality — Thesis Review",
     "group": "What would stop me", "desc": "Businesses that still score well while price sits below the "
             "200 MA. Either the market knows something the fundamentals "
             "have not shown yet, or it is wrong. Worth deciding which.",
     # Expressed as "price below the 200 MA" rather than as a stage. The
     # stage split into UNCONFIRMED/BREAKDOWN when slope measurement arrived
     # and this preset silently emptied; the underlying question — a good
     # business trading under its long-term average — did not change.
     "rules": ["lquality:gte:85", "lt_pct_vs_200ma:lt:0"]},
    {"key": "dry_powder", "icon": "⏳", "name": "Dry Powder Watchlist",
     "group": "What would stop me", "desc": "Worth owning, priced acceptably, and extended above the 8 EMA. "
             "Nothing to do but wait for the pullback — which is the point.",
     "rules": ["lquality:gte:85", "valuation_band:ne:OVERVALUED",
               "extended:eq:true"]},
    {"key": "insider_aligned", "icon": "🤝", "name": "Insiders Buying",
     "group": "What would stop me", "desc": "Quality where the people who know it best are net buyers. A "
             "tiebreaker, never a thesis — it sits outside LQuality for "
             "exactly that reason.",
     "rules": ["lquality:gte:85", "insider:eq:Net buying"]},
    {"key": "earnings_clear", "icon": "📅", "name": "Clear of Earnings",
     "group": "What would stop me", "desc": "Quality names with no report inside two weeks — the gap risk "
             "that no amount of setup quality offsets.",
     "rules": ["lquality:gte:85", "lt_days_to_earnings:gte:14"]},
)

PRESET_BY_KEY = {p["key"]: p for p in PRESETS}


def preset_rules(key: str) -> list[str]:
    preset = PRESET_BY_KEY.get(str(key or ""))
    return list(preset["rules"]) if preset else []


def preset_counts(results) -> dict:
    """How many rows each preset currently matches, computed live.

    The counts used to be recorded in each preset as a measured note. That
    was wrong in a way that took one engine change to expose: when
    STAGE4_BREAKDOWN was split into "confirmed breakdown" and "unconfirmed",
    Fallen Quality went from 10 matches to 0 while still advertising 10, and
    Quality at a Discount went from 20 to 31. A number written down beside a
    rule is a claim about a moving target.

    Flattens the universe ONCE and reuses it across every preset — 16 groups
    over one row set rather than 16 passes of flatten().
    """
    rows = [flatten(r) for r in results]
    out = {}
    for preset in PRESETS:
        conds = [c for c in (parse_rule(t) for t in preset["rules"]) if c]
        if not conds:
            out[preset["key"]] = None
            continue
        group = S.Group(op="AND", items=conds)
        out[preset["key"]] = sum(1 for row in rows if S.eval_group(row, group))
    return out
