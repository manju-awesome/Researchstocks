"""
engine.py — the four gates, in order
====================================
This is where the hierarchy is enforced:

    business quality > valuation > long-term trend > support > entry trigger

Structurally, not by weighting. `evaluate()` walks the gates in that order
and a failure at any level stops the ones below it from mattering. A 100
technical score on a 62-quality company does not produce a buy, because the
technical gate is never reached.

That is the difference between this engine and a weighted composite. With
weights alone, a strong enough chart drags a mediocre business over any
threshold you set — you can push the threshold up, but you cannot stop the
substitution, and the whole framework exists to refuse that substitution.
`LT_Score` is still computed and still 40/20/25/15, but it ranks names that
have already passed the gates. It never decides whether they pass.

Actions
-------
    BUY NOW           at a qualifying level, with confirmation, now
    BUY ON 8/21 EMA   own it; wait for the shallow pullback
    BUY ON 50 MA      own it; wait for the core entry
    BUY ON 200 MA     own it; wait for the deep entry (elite only)
    BUY ON BREAKOUT RETEST   own it; wait for the prior breakout to be retested
    WATCH             something is missing that price alone will not fix
    WAIT              good business, wrong price or imminent earnings
    AVOID             fails the quality gate, or the trend is broken

Every BUY ON action names a dollar price. "Wait for a pullback to the 50 MA"
is not an instruction anyone can act on; "$206.05, 8.0% below here" is.

Regime, from §11
----------------
The market regime does not score. It changes how selective the gates are:

    FAVORABLE   normal operation
    SELECTIVE   quality bars rise by SELECTIVE_QUALITY_BUMP — corrections
                are when only the best businesses are worth adding to
    DEFENSIVE   no BUY NOW at any quality. Everything that would have been
                a buy becomes a watchlist entry, which is §11's "build
                watchlist + preserve cash + wait for confirmation" and the
                single most valuable thing this engine can do in a bear
                market: nothing.
"""

from __future__ import annotations

from stockanalysis.core.longterm import quality as Q
from stockanalysis.core.longterm import technicals as T
from stockanalysis.core.longterm import valuation as V
from stockanalysis.core.longterm._common import b, blend, f, s

# Minimum LQuality to enter at each zone. Straight from §4/§5/§6/§7: the
# deeper and more dangerous the entry, the better the business has to be,
# because a 200 MA pullback is the one that most often turns out to be
# fundamental deterioration rather than a correction.
ZONE_MIN_QUALITY = {"EMA": 85, "50MA": 85, "BREAKOUT": 85, "200MA": 90}

# Share of the intended full position each tranche takes (§7).
ZONE_TRANCHE = {"EMA": 22, "50MA": 28, "BREAKOUT": 28, "200MA": 25}

ZONE_ACTION = {"EMA": "BUY ON 8/21 EMA", "50MA": "BUY ON 50 MA",
               "200MA": "BUY ON 200 MA",
               "BREAKOUT": "BUY ON BREAKOUT RETEST"}

# A buy at any zone needs the support underneath it to be real. §6 STEP 6
# asks for "at least 2-3 confluences", and that is a COUNT of independent
# confirmations rather than a level on the weighted score.
#
# The distinction decides whether Zone A can ever fire. Gating on the
# weighted score at 50 requires price to sit on two major moving averages
# simultaneously, since the 50 MA and 200 MA carry 25 points each and the
# 8/21 EMA only 20. That is a deep pullback by definition — the exact
# opposite of the shallow, high-momentum entry Zone A exists to catch — so a
# score gate silently made §4 unreachable. Counting hits asks what the
# framework actually asks: is more than one thing agreeing here.
MIN_CONFLUENCE_HITS = 2
# ...and the pullback to look like rest rather than exit.
MIN_PULLBACK_VOLUME = 40

SELECTIVE_QUALITY_BUMP = 5

ACTIONS = ("BUY NOW", "BUY ON CONFIRMATION", "BUY ON 8/21 EMA",
           "BUY ON 50 MA", "BUY ON BREAKOUT RETEST", "BUY ON 200 MA",
           "BUY ON SUPPORT", "DEEP PULLBACK — WAIT FOR SUPPORT",
           "WATCH", "WAIT", "RESEARCH", "AVOID")

ACTION_ICONS = {"BUY NOW": "🟢", "BUY ON CONFIRMATION": "🟢",
                "BUY ON 8/21 EMA": "🟢", "BUY ON 50 MA": "🟢",
                "BUY ON BREAKOUT RETEST": "🟢", "BUY ON 200 MA": "🟢",
                "BUY ON SUPPORT": "🟢",
                "DEEP PULLBACK — WAIT FOR SUPPORT": "🟡",
                "WATCH": "🔵", "WAIT": "⏳", "RESEARCH": "🔎", "AVOID": "🔴"}

# A buy that is not yet actionable needs the trend CONFIRMED, not merely
# un-broken. PARTIAL means something structural was never measured, and the
# most a name can earn on unmeasured structure is "buy when this confirms".
CONFIRMED_ONLY_ACTIONS = ("BUY NOW",)

# Readiness bands (core.longterm.technicals.READINESS_BANDS) mapped to what
# the engine is willing to do about them.
READY_BUY = 80
READY_CONFIRM = 65
READY_WATCH = 50

REGIME_SCORE = {"FAVORABLE": 100.0, "SELECTIVE": 55.0, "DEFENSIVE": 15.0}

# An imminent report is gap risk no setup quality offsets — the same guard
# decision_engine applies, for the same reason.
EARNINGS_BLOCK_DAYS = 7


def _earnings_days(row):
    return f(row.get("Days_To_Earnings"))


# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE SCORE — §14. Ranks names that already passed the gates.
# ─────────────────────────────────────────────────────────────────────────────

def compute_lt_score(lq, val, tech_sub, market_sub) -> dict:
    return blend([
        ("Fundamental quality", 40, None if lq.get("score") is None
         else float(lq["score"]), lq.get("tier") or "unrated"),
        ("Valuation", 20, V.valuation_sub_score(val),
         val.get("band") or "not priced"),
        ("Technical setup", 25, tech_sub, "trend, support, volume, RS"),
        ("Market & sector", 15, market_sub, "regime and sector strength"),
    ])


def _market_sub_score(row, regime) -> tuple[float | None, str]:
    """The 15% market/sector leg: the regime, plus how the stock's sector is
    ranking against the rest of the library."""
    parts, notes = [], []
    reg = REGIME_SCORE.get(str(regime or "").upper())
    if reg is not None:
        parts.append(reg)
        notes.append(f"regime {regime}")
    sector_rank = f(row.get("Sector_Strength_Rank"))
    if sector_rank is not None:
        parts.append(max(0.0, min(100.0, sector_rank)))
        notes.append(f"sector strength {sector_rank:.0f}")
    if not parts:
        return None, "no market context"
    return sum(parts) / len(parts), " · ".join(notes)


# ─────────────────────────────────────────────────────────────────────────────
# THE GATES
# ─────────────────────────────────────────────────────────────────────────────

def _entry_prices(pullback, price) -> list[dict]:
    """Every tracked level below the current price, nearest first, as prices
    you could leave a resting order at."""
    below = [c for c in pullback.get("candidates", [])
             if c["distance_pct"] is not None and c["distance_pct"] > 0]
    below.sort(key=lambda c: c["distance_pct"])
    out = []
    for c in below:
        move = (c["price"] / price - 1) * 100.0 if price else None
        out.append({"name": c["name"], "zone": c["zone"], "price": c["price"],
                    "move_pct": None if move is None else round(move, 1),
                    "tranche_pct": ZONE_TRANCHE.get(c["zone"])})
    return out


def _confirmation(row, pullback, volume) -> tuple[bool | None, list[str]]:
    """§5: touch → stabilization → confirmation → entry. A touch is not an
    entry, and this is the check that keeps the engine from buying one.

    Returns (confirmed, missing_reasons). None means the confirming inputs
    were never measured — which is not a confirmation, and is reported as
    such rather than assumed either way.
    """
    missing = []
    reversal = row.get("Reversal_Candle")
    rsi = f(row.get("RSI_14"))
    vol_score = volume.get("score")

    have_any = False
    confirmed = True

    if reversal is None:
        missing.append("No candle data — reversal cannot be confirmed")
        confirmed = None
    else:
        have_any = True
        pattern = str(reversal).strip()
        if not pattern or pattern.lower() in ("none", "false"):
            missing.append("No bullish reversal candle yet")
            confirmed = False

    if vol_score is None:
        missing.append("Pullback volume not measured")
        if confirmed is not False:
            confirmed = None
    else:
        have_any = True
        if vol_score < MIN_PULLBACK_VOLUME:
            missing.append(f"Pullback volume {vol_score}/100 — "
                           f"{volume.get('label')}")
            confirmed = False

    if rsi is not None and rsi > 70:
        have_any = True
        missing.append(f"RSI {rsi:.0f} — overbought into the level")
        confirmed = False

    if not have_any:
        return None, missing
    return confirmed, missing


def evaluate(row: dict, peers: dict | None = None,
             regime: str = "FAVORABLE",
             risk_free: float = V.DEFAULT_RISK_FREE,
             sector_stats: dict | None = None) -> dict:
    """
    One verdict for one company. `row` is a scan / research `raw` row.

    `peers` and `sector_stats` are universe-level context — the sector
    multiples the valuation fallback prices against, and the sector
    percentiles the moat check compares to. Both are optional and both
    degrade explicitly rather than silently; `evaluate_universe()` builds
    them and is the normal entry point.

    Returns a dict carrying every intermediate score plus the action, the
    reasoning that produced it, and — for every BUY ON action — the price
    to wait for and the tranche to take there.
    """
    ticker = s(row.get("Ticker")) or s(row.get("ticker"))
    price = f(row.get("Current Price")) or f(row.get("price"))

    lq = Q.compute_lquality(row, sector_stats)
    val = V.compute_valuation(row, peers, risk_free)
    trend = T.compute_trend(row)
    pullback = T.compute_pullback(row)
    confluence = T.compute_support_confluence(row)
    volume = T.compute_pullback_volume(row)
    rs = T.relative_strength(row)
    readiness = T.compute_entry_readiness(row, pullback, rs, regime)
    insider = Q.insider_signal(row)

    tech_sub = T.technical_sub_score(trend, pullback, confluence, volume, rs)
    market_sub, market_note = _market_sub_score(row, regime)
    lt = compute_lt_score(lq, val, tech_sub, market_sub)

    regime_up = str(regime or "FAVORABLE").upper()
    bump = SELECTIVE_QUALITY_BUMP if regime_up == "SELECTIVE" else 0

    blockers, triggers = [], []
    entries = _entry_prices(pullback, price)

    def verdict(action, gate):
        return _assemble(ticker, action, gate, row, lq, val, trend, pullback,
                         confluence, volume, rs, lt, market_note, entries,
                         blockers, triggers, price, regime_up, readiness,
                         insider)

    # ── GATE 1 — business quality. Nothing below matters if this fails. ──
    if lq["score"] is None or not lq["reliable"]:
        blockers.append(
            f"Quality could not be assessed — {int(lq['coverage'] * 100)}% of "
            f"the factor weight had data" +
            (f" (missing {', '.join(lq['missing'][:3])})" if lq["missing"] else ""))
        triggers.append("Run a scan so the fundamental fields populate")
        return verdict("AVOID", "quality")

    if lq["score"] < Q.MIN_OWNABLE:
        blockers.append(f"LQuality {lq['score']} ({lq['tier']}) — below the "
                        f"{Q.MIN_OWNABLE} ownable bar. No chart pattern "
                        f"compensates for this.")
        return verdict("AVOID", "quality")

    # ── GATE 2 — valuation. A great company at any price is not a buy. ──
    if val["acceptable"] is False:
        # The headline is the only field both methods produce — the reverse
        # DCF deliberately has no fair value, and printing one it never
        # computed would be a number nobody could defend.
        blockers.append(f"{val['band_icon']} Overvalued — {val['headline']}")
        if val["fair_value"] is not None:
            triggers.append(f"Price falls toward ${val['fair_value']:,.2f}, "
                            f"or earnings grow into the multiple")
        elif val["implied_growth_pct"] is not None:
            triggers.append(
                f"The gap closes — either the price falls, or growth "
                f"accelerates toward the {val['implied_growth_pct']:.0f}% "
                f"the price already assumes")
        else:
            triggers.append("Valuation improves")
        return verdict("WAIT", "valuation")

    if val["acceptable"] is None:
        blockers.append("Could not be valued — " +
                        (val["notes"][0] if val["notes"] else "no method applied"))

    # ── GATE 3 — long-term trend. Buying weakness inside an uptrend only. ──
    if trend["pass"] is False:
        blockers.append("Trend broken: " + ", ".join(trend["required_failed"]))
        triggers.append("Trend repairs — price reclaims the 200 MA and the "
                        "50 MA crosses back above it")
        # Not AVOID: the business still passed gate 1, so this is a
        # watchlist name whose chart has to heal, not a company to discard.
        return verdict("WATCH", "trend")

    if trend["state"] == "PARTIAL":
        # Explicitly NOT a failure. Structure holds; something is unmeasured.
        # It costs the name a BUY NOW — that requires CONFIRMED — but it must
        # not eject it from the ladder, which is what "failed on trend" did
        # to Western Digital while it sat above a rising 200 MA structure
        # with only its slopes unscanned.
        blockers.append(
            f"Trend partially confirmed — {trend['confirmed_points']} points "
            f"confirmed, {trend['unknown_points']} unmeasured "
            f"({', '.join(trend['unknown'][:3])}). Structure is intact; "
            f"nothing has failed")

    # ── GATE 4 — stage, support and trigger. Where, and has it confirmed? ──
    stage = pullback["stage"]

    if regime_up == "DEFENSIVE":
        blockers.append("Market regime DEFENSIVE — §11 says stop adding, "
                        "build the watchlist and hold cash")
        triggers.append("Regime improves to SELECTIVE or FAVORABLE")
        return verdict("WATCH", "regime")

    days = _earnings_days(row)
    if days is not None and 0 <= days <= EARNINGS_BLOCK_DAYS:
        blockers.append(f"Earnings in {days:.0f} day"
                        f"{'s' if days != 1 else ''} — gap risk no setup "
                        f"quality offsets")
        triggers.append("Re-assess once the report is out")
        return verdict("WAIT", "earnings")

    triggers.extend(_buy_triggers(row, pullback, readiness, trend))

    # Below the ownable-but-not-elite bar, the framework says research it,
    # not buy it — §15's "<80 / cheap / confirmed" row.
    if lq["score"] < min(ZONE_MIN_QUALITY.values()) + bump:
        blockers.append(
            f"LQuality {lq['score']} ({lq['tier']}) — this engine requires "
            f"{min(ZONE_MIN_QUALITY.values()) + bump} to enter on a pullback"
            + (" in a SELECTIVE regime" if bump else ""))
        return verdict("RESEARCH", "entry")

    # STAGE 4 — below the 200 MA. Not a pullback; a thesis review.
    if stage == "STAGE4_BREAKDOWN":
        blockers.append(pullback["note"])
        return verdict("WATCH", "trend")

    # STAGE 3 — deep correction, long-term structure not broken. The state
    # that had no name before: too far below the 50 MA to be a normal
    # pullback, still above the 200 MA, and therefore neither a buy nor a
    # discard. What decides it is whether support has actually held.
    if stage == "STAGE3_DEEP":
        if readiness["score"] >= READY_CONFIRM and trend["state"] != "BROKEN":
            return verdict("BUY ON CONFIRMATION", "trigger")
        near = (pullback.get("supports") or {}).get("near")
        if near:
            blockers.append(
                f"Nearest support is {near['name']} at ${near['price']:,.2f}, "
                f"{abs(near['distance_pct']):.1f}% below — not tested yet")
        blockers.append(f"Entry readiness {readiness['score']}/100 "
                        f"({readiness['label']})")
        return verdict("DEEP PULLBACK — WAIT FOR SUPPORT", "readiness")

    # EXTENDED or AT_HIGHS — nothing to buy here; name the price to wait for.
    if stage in ("EXTENDED", "AT_HIGHS"):
        blockers.append(pullback["note"] if pullback["extended"]
                        else "Not at a support level — no entry to take yet")
        if entries:
            first = entries[0]
            if lq["score"] >= ZONE_MIN_QUALITY.get(first["zone"], 85) + bump:
                return verdict(ZONE_ACTION.get(first["zone"], "WATCH"), "entry")
        return verdict("WATCH", "entry")

    # STAGE 1 / STAGE 2 — price is on a tracked level.
    zone = pullback["zone"]
    min_q = ZONE_MIN_QUALITY.get(zone, 85) + bump
    if lq["score"] < min_q:
        blockers.append(f"LQuality {lq['score']} — entering at the "
                        f"{pullback['level']} requires {min_q}"
                        + (" in a SELECTIVE regime" if bump else ""))
        return verdict("WATCH", "entry")

    hits = len(confluence["hits"])
    if hits < MIN_CONFLUENCE_HITS:
        only = confluence["hits"][0]["name"] if hits else "nothing"
        blockers.append(f"Only {hits} support confirmation"
                        f"{'' if hits == 1 else 's'} here ({only}) — "
                        f"confluence {confluence['score']}/100. One level "
                        f"alone is a coordinate, not support")
        return verdict("WATCH", "support")

    confirmed, missing = _confirmation(row, pullback, volume)
    if confirmed is not True:
        blockers.extend(missing)
        if readiness["score"] >= READY_CONFIRM:
            return verdict("BUY ON CONFIRMATION", "trigger")
        return verdict("WATCH", "trigger")

    # Everything holds. A BUY NOW additionally needs the trend CONFIRMED —
    # acting today on structure that was never measured is the one thing the
    # PARTIAL state exists to prevent.
    if trend["state"] != "CONFIRMED":
        return verdict("BUY ON CONFIRMATION", "trigger")

    triggers.insert(0, f"Take the {ZONE_TRANCHE.get(zone, 25)}% tranche here; "
                       f"add on the next level down or on trend resumption")
    return verdict("BUY NOW", "confirmed")


# ─────────────────────────────────────────────────────────────────────────────
# BUY TRIGGERS — what would actually make this a buy, in prices
# ─────────────────────────────────────────────────────────────────────────────
# "Re-scan to populate the moving-average slopes" is a note about the
# software, not about the stock. A trigger has to be something the tape can
# do: a level tested and held, an average reclaimed, volume drying up. Each
# one below names a price wherever the data supports naming one.

def _buy_triggers(row, pullback, readiness, trend) -> list[str]:
    out = []
    supports = pullback.get("supports") or {}
    by_level = pullback.get("by_level") or {}
    near, major = supports.get("near"), supports.get("major")
    price = f(row.get("Current Price")) or f(row.get("price"))

    if near and near["distance_pct"] < 0:
        out.append(
            f"A — Support buy: price tests {near['name']} at "
            f"${near['price']:,.2f} ({near['distance_pct']:+.1f}%), holds it, "
            f"volume contracts, and a bullish reversal prints")

    ema8 = (by_level.get("8EMA") or {}).get("price")
    ema21 = (by_level.get("21EMA") or {}).get("price")
    if ema8 and price and price < ema8:
        reclaim = f"${ema8:,.2f}"
        if ema21:
            reclaim += f" then the 21 EMA at ${ema21:,.2f}"
        out.append(f"B — Momentum repair: price reclaims the 8 EMA at "
                   f"{reclaim} on improving volume")

    ma50 = (by_level.get("50MA") or {}).get("price")
    if ma50 and price and price < ma50:
        out.append(f"C — Trend repair: price reclaims the 50 MA at "
                   f"${ma50:,.2f} and the 50 MA slope turns positive")

    if major and major["distance_pct"] < -1:
        out.append(f"D — Deep-value entry: only near the 200 MA at "
                   f"${major['price']:,.2f} ({major['distance_pct']:+.1f}%), "
                   f"and only if the fundamentals still hold")

    if major:
        out.append(f"Invalidation: a break below ${major['price']:,.2f} on "
                   f"heavy volume with deteriorating fundamentals — that is "
                   f"a thesis review, not a cheaper entry")

    for u in readiness.get("unknown", []):
        if u["name"] == "Bullish reversal":
            out.append("Re-scan to measure the reversal candle — it cannot be "
                       "confirmed from the current data")
    if trend["state"] == "PARTIAL" and trend["unknown"]:
        out.append("Re-scan to populate " + ", ".join(trend["unknown"][:2])
                   + " — the only structural checks still unmeasured")
    return out


def _assemble(ticker, action, gate, row, lq, val, trend, pullback, confluence,
              volume, rs, lt, market_note, entries, blockers, triggers, price,
              regime, readiness=None, insider=None) -> dict:
    """The verdict with its whole audit attached — never a score without the
    reasoning that produced it."""
    zone = pullback["zone"]
    tranche = (ZONE_TRANCHE.get(zone) if action == "BUY NOW"
               else (entries[0]["tranche_pct"] if entries
                     and action.startswith("BUY ON") else None))

    why = []
    if lq["tier"]:
        why.append(f"{lq['tier_icon']} {lq['tier']} business — LQuality "
                   f"{lq['score']}/100")
    if val["band"]:
        why.append(f"{val['band_icon']} {val.get('band_label') or val['band']} "
                   f"— {val['headline']}")
    if trend["state"] == "CONFIRMED":
        why.append("Long-term uptrend confirmed")
    elif trend["state"] == "PARTIAL":
        why.append(f"Long-term structure intact — {trend['confirmed_points']} "
                   f"points confirmed, nothing failed")
    n_hits = len(confluence["hits"])
    if n_hits >= MIN_CONFLUENCE_HITS:
        # Stated as the count, without the score's band label. The gate is a
        # count of confirmations and the label is a level on the weighted
        # score, so pairing them put "🔴 Weak — confluence 35/100" in the
        # list of reasons TO buy. Both readings are correct on their own
        # terms; asserting them together is the contradiction.
        names = ", ".join(h["name"] for h in confluence["hits"][:3])
        why.append(f"{n_hits} support levels hold here ({names})")
    if rs["strong"]:
        why.append(f"Relative strength — {rs['detail']}")
    if volume.get("score") is not None and volume["score"] >= 60:
        why.append(f"Pullback volume {volume['score']}/100 — {volume['label']}")

    return {
        "ticker": ticker,
        "name": s(row.get("LongName")) or ticker,
        "sector": s(row.get("Sector")),
        "price": price,
        "action": action,
        "icon": ACTION_ICONS.get(action, ""),
        # Which gate produced this verdict — the whole point of the ordering
        # is that you can see where a name stopped.
        "gate": gate,
        "lt_score": lt["score"],
        "lt_coverage": lt["coverage"],
        "lt_components": lt["components"],
        "quality": lq,
        "valuation": val,
        "trend": trend,
        "pullback": pullback,
        "confluence": confluence,
        "volume": volume,
        "rs": rs,
        "readiness": readiness or {},
        # Reported beside the verdict, never inside the quality score.
        "insider": insider or {},
        "regime": regime,
        "market_note": market_note,
        "tranche_pct": tranche,
        "entries": entries,
        "why": why,
        "blockers": blockers,
        "triggers": triggers,
        "days_to_earnings": _earnings_days(row),
    }


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSE — the two things that cannot be computed from one row
# ─────────────────────────────────────────────────────────────────────────────

def attach_sector_context(rows) -> None:
    """In place: Sector_RS_Rank and Sector_Strength_Rank.

    Sector_RS_Rank is the ticker's percentile of raw RS WITHIN its own
    sector — §9's point, that a name lagging the market while leading its
    group is a different animal from one lagging both.

    Sector_Strength_Rank is the percentile of the sector's own median RS
    across all sectors, which is the "sector trend" term §14 asks for.
    Sectors with fewer than MIN_SECTOR_MEMBERS names in the library are left
    None rather than ranked off two tickers.
    """
    MIN_SECTOR_MEMBERS = 4
    by_sector: dict[str, list] = {}
    for row in rows:
        sector, rs = s(row.get("Sector")), f(row.get("RS"))
        if sector and rs is not None:
            by_sector.setdefault(sector, []).append(rs)

    medians = {}
    for sector, vals in by_sector.items():
        if len(vals) >= MIN_SECTOR_MEMBERS:
            ordered = sorted(vals)
            n = len(ordered)
            medians[sector] = (ordered[n // 2] if n % 2
                               else (ordered[n // 2 - 1] + ordered[n // 2]) / 2)

    ranked_sectors = sorted(medians, key=lambda k: medians[k])
    n_sec = len(ranked_sectors)
    sector_strength = {sec: round(i / max(1, n_sec - 1) * 100)
                       for i, sec in enumerate(ranked_sectors)} if n_sec > 1 else {}

    ordered_by_sector = {sec: sorted(vals) for sec, vals in by_sector.items()
                         if len(vals) >= MIN_SECTOR_MEMBERS}

    for row in rows:
        sector, rs = s(row.get("Sector")), f(row.get("RS"))
        row["Sector_Strength_Rank"] = sector_strength.get(sector or "")
        vals = ordered_by_sector.get(sector or "")
        if vals is None or rs is None:
            row["Sector_RS_Rank"] = None
            continue
        below = sum(1 for v in vals if v < rs)
        row["Sector_RS_Rank"] = round(below / max(1, len(vals) - 1) * 100) \
            if len(vals) > 1 else None


def evaluate_universe(rows, regime: str = "FAVORABLE",
                      risk_free: float = V.DEFAULT_RISK_FREE) -> list[dict]:
    """
    Evaluate the whole library. Does the three things `evaluate()` cannot do
    from a single row — build the sector peer multiples the valuation
    fallback needs, build the sector percentiles the moat check compares to,
    and rank each name against its own sector — then runs every row through
    the gates.

    Sorted by action priority, then LT score: the ranking a human reads
    top-down.
    """
    rows = list(rows)
    attach_sector_context(rows)
    peers = V.build_peer_stats(rows)
    sector_stats = Q.build_sector_stats(rows)
    out = [evaluate(row, peers, regime, risk_free, sector_stats)
           for row in rows]
    order = {a: i for i, a in enumerate(ACTIONS)}
    out.sort(key=lambda r: (order.get(r["action"], 99), -(r["lt_score"] or 0)))
    return out
