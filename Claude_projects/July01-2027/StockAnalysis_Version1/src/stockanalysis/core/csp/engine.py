"""
The Cash-Secured Put engine — orchestration.

Order of operations is the design, not an implementation detail:

    1. Eligibility on the COMPANY, with no option data in scope at all.
    2. Only for names that survive, fetch chains (the slow, networked step).
    3. Price, greek and rank the strikes.
    4. Assignment test.
    5. Score and rank.

Fetching chains only for survivors is partly a speed decision — a chain
is one network round trip per expiry per ticker — but mainly a
correctness one: a rejected company has no strike worth computing, and
computing one invites it to be looked at.

Earnings handling deserves its own note. An expiry that spans earnings is
rejected by default rather than penalised. Selling a put through an
earnings print on a position you intend to be assigned into is the one
combination where the tail actually bites: the premium is richest exactly
because the gap risk is real, and a gap through your strike hands you
stock at a price the market no longer believes in.
"""

from __future__ import annotations

import datetime as _dt

from stockanalysis.core.longterm._common import f, s

from . import chain as C
from . import eligibility as EL
from . import greeks as G
from . import premium as PR
from . import score as SC
from . import strike as ST
from . import volatility as V

DEFAULT_MIN_DTE = 20
DEFAULT_MAX_DTE = 45
# Fallback when the long-term engine cannot resolve a rate; the greeks
# are barely sensitive to r over 20-45 days, but a wrong sign would show.
FALLBACK_RISK_FREE = 0.04


def _closes(ticker: str, days: int = 200) -> list[float]:
    """Daily closes for realised-vol. Never tz-converts: daily bars carry
    a date, and converting shifts them back a day, which silently
    corrupts every window that starts from 'the previous close'."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=f"{days}d", interval="1d",
                                      auto_adjust=False)
        if h is None or h.empty:
            return []
        return [float(x) for x in h["Close"].tolist() if x == x]
    except Exception as e:
        print(f"[CSP] {ticker}: price history unavailable ({e})")
        return []


def _earnings_conflict(result, expiry, today=None) -> str | None:
    """Whether earnings land on or before `expiry`. None means clear."""
    days = f(result.get("days_to_earnings"))
    if days is None:
        return None                       # unknown, reported separately
    d = C.dte(expiry, today)
    if d is None:
        return None
    if days <= d:
        return (f"earnings in {days:.0f} day(s), before the {expiry} "
                f"expiry ({d}d)")
    return None


def evaluate(result: dict, regime: str = "SELECTIVE", risk_free=None,
             min_dte=DEFAULT_MIN_DTE, max_dte=DEFAULT_MAX_DTE,
             allow_earnings=False, today=None, raw=None,
             quotes_live=None) -> dict:
    """One long-term engine result -> one full CSP verdict.

    `raw` is the scan row the result was built from. It carries ATR,
    which the engine result does not, and ATR is what makes premium
    comparable across names of different volatility.
    """
    ticker = s(result.get("ticker")) or "?"
    atr = f((raw or {}).get("ATR20"))
    spot = f(result.get("price"))
    r = f(risk_free)
    if r is None:
        r = FALLBACK_RISK_FREE
    elif r > 1:                            # given as a percent
        r = r / 100.0

    elig = EL.classify(result)
    discount = EL.discount_view(result)

    base = {
        "ticker": ticker,
        "name": s(result.get("name")) or ticker,
        "sector": s(result.get("sector")),
        "price": spot,
        "eligibility": elig,
        "discount": discount,
        "regime": regime,
        "levels": ST.support_levels(result),
        "atr": atr,
        "days_to_earnings": f(result.get("days_to_earnings")),
        "earnings_risk": result.get("earnings_risk") or {},
        "lt_action": s(result.get("action")),
        "lt_score": f(result.get("lt_score")),
        "_lt": result,
    }

    # Step 1 is a gate. A rejected company never reaches an option chain.
    if elig["status"] == "CSP REJECTED":
        return {**base, "chosen": None, "trade": None,
                "final": {"action": "🔴 REJECT", "key": "REJECT",
                          "why": elig["blockers"][0]},
                "csp_score": None,
                "no_trade_reason": elig["blockers"][0]}

    if not spot:
        return {**base, "chosen": None, "trade": None, "csp_score": None,
                "final": {"action": "🟠 WATCH", "key": "WATCH",
                          "why": "no spot price"},
                "no_trade_reason": "no spot price"}

    # ── Chains ──────────────────────────────────────────────────────────
    all_exp = C.expiries(ticker)
    if not all_exp:
        return {**base, "chosen": None, "trade": None, "csp_score": None,
                "final": {"action": "🟠 WATCH", "key": "WATCH",
                          "why": "no listed options"},
                "no_trade_reason": "no listed options for this ticker"}

    picked = C.pick_expiries(all_exp, min_dte, max_dte, limit=3, today=today)
    if not picked:
        return {**base, "chosen": None, "trade": None, "csp_score": None,
                "final": {"action": "🟠 WATCH", "key": "WATCH",
                          "why": f"no expiry between {min_dte} and {max_dte} DTE"},
                "no_trade_reason": f"no expiry in the {min_dte}-{max_dte} DTE window"}

    # Quote quality depends on whether the book is live. Resolved once
    # per evaluation rather than per contract.
    from .store import market_open
    quotes_live = market_open() if quotes_live is None else quotes_live

    hv = V.realised_vol(_closes(ticker))
    best, per_expiry, skipped = None, [], []

    for expiry in picked:
        conflict = _earnings_conflict(result, expiry, today)
        if conflict and not allow_earnings:
            skipped.append({"expiry": expiry, "why": conflict})
            continue

        rows = C.fetch_puts(ticker, expiry)
        if not rows:
            skipped.append({"expiry": expiry, "why": "chain unavailable"})
            continue

        t = C.year_fraction(expiry, today)
        d = C.dte(expiry, today)
        if not t or not d:
            continue

        atm = C.atm_iv(rows, spot)
        V.record(ticker, atm)

        candidates = []
        for row in rows:
            if row["strike"] >= spot:      # cash-secured puts are OTM
                continue
            iv = row["iv"]
            if iv is None and row.get("mid"):
                iv = G.implied_vol(row["mid"], spot, row["strike"], t, r)
                row["iv_source"] = "backsolved" if iv else "unusable"
            if iv is None:
                continue

            gk = G.put_greeks(spot, row["strike"], t, r, iv)
            if gk["delta"] is None:
                continue

            limit = C.limit_price(row)
            ret = SC.returns(row["strike"], limit, d)
            liq = C.liquidity_score(row, quotes_live)
            be = ret.get("breakeven")

            candidates.append({
                **row, **gk, "iv": iv, "expiry": expiry, "dte": d, "t": t,
                "limit_price": limit,
                "liquidity": liq["score"],
                "liquidity_notes": liq["notes"],
                "liquidity_tradable": liq["tradable"],
                "spread_verdict": liq["spread_verdict"],
                "_liq": liq,
                "expected_move": G.expected_move(spot, t, iv),
                # Probability of PROFIT is measured from the breakeven,
                # not the strike: the premium is kept either way.
                "prob_profit": G.prob_above(spot, be, t, r, iv) if be else None,
                "breakeven": be,
                "breakeven_pct": (round((be - spot) / spot * 100, 1)
                                  if be and spot else None),
                "distance_pct": round((row["strike"] - spot) / spot * 100, 1),
                **{k: v for k, v in ret.items() if k != "breakeven"},
            })

        sel = ST.select(candidates, result, regime, spot)
        per_expiry.append({"expiry": expiry, "dte": d, "atm_iv": atm,
                           "selection": sel, "candidates": len(candidates)})

        if sel["chosen"] and (best is None or
                              (sel["chosen"]["fit"]["score"],
                               sel["chosen"].get("annualised") or 0) >
                              (best[1]["chosen"]["fit"]["score"],
                               best[1]["chosen"].get("annualised") or 0)):
            best = (expiry, sel, atm)

    if best is None:
        why = (skipped[0]["why"] if skipped else
               next((p["selection"]["no_trade_reason"] for p in per_expiry
                     if p["selection"].get("no_trade_reason")),
                    "no strike satisfied the support and buy-zone conditions"))
        blocked = next((p["selection"].get("blocked_on") for p in per_expiry
                        if p["selection"].get("blocked_on")), None)
        # Even with no contract, the stock half is scoreable and the ideal
        # zone is computable — that is what makes "wait for X" actionable
        # rather than just "nothing today".
        stock = SC.stock_score(result, discount, None, None)
        req = PR.required(0.20, (min_dte + max_dte) // 2, r,
                          (result.get("quality") or {}).get("score"),
                          discount.get("margin_pct"),
                          (ST.anchor_level(base["levels"]) or {}).get("confidence"),
                          regime)
        sinfo = {"score": None, "stock": stock, "option": {"score": None},
                 "components": [], "coverage": stock["coverage"],
                 "rejections": []}
        final = SC.final_action(sinfo, elig, {"happy_to_own": None}, why,
                                blocked_on=blocked)
        return {**base, "chosen": None, "trade": None, "csp_score": None,
                "per_expiry": per_expiry, "skipped_expiries": skipped,
                "stock_score": stock["score"], "option_score": None,
                "score_detail": sinfo,
                "required": req,
                "ideal_zone": PR.ideal_zone(
                    spot, base["levels"], ST.anchor_level(base["levels"]),
                    None, req, min_dte, max_dte),
                "final": final,
                "no_trade_reason": why}

    expiry, sel, atm = best
    chosen = sel["chosen"]

    ivr = V.rank(ticker, atm)
    ratio = V.iv_vs_hv(atm, hv)
    iv_op = V.iv_opportunity(ivr, ratio)

    ret = SC.returns(chosen["strike"], chosen["limit_price"], chosen["dte"])
    assign = SC.assignment(chosen["strike"], chosen["limit_price"],
                           result, discount, sel["levels"])

    # ── Is the option itself worth selling? ─────────────────────────────
    anchor = sel.get("anchor") or {}
    req = PR.required(chosen.get("delta"), chosen.get("dte"), r,
                      (result.get("quality") or {}).get("score"),
                      discount.get("margin_pct"),
                      anchor.get("confidence"), regime,
                      iv_rv=ratio.get("ratio"))
    adq = PR.adequacy(ret.get("yield_pct"), req)
    eff = PR.capital_efficiency(ret.get("annualised"), r,
                                ret.get("collateral"),
                                ret.get("premium_total"), chosen.get("dte"))
    downside = PR.per_unit_downside(chosen.get("limit_price"), atr,
                                    chosen.get("expected_move"),
                                    assign.get("basis"), sel["levels"])
    mos = PR.margin_at_assignment(assign.get("basis"), discount)
    zone = PR.ideal_zone(spot, sel["levels"], anchor, sel.get("buy_zone"),
                         req, min_dte, max_dte)

    liq = chosen.get("_liq") or {}
    liq = {**liq, "spread_pct": chosen.get("spread_pct")}

    sinfo = SC.compute(result, elig, discount, chosen, ret, iv_op, liq,
                       regime, assign, fit_anchor=anchor, adq=adq, eff=eff)
    final = SC.final_action(sinfo, elig, assign, None, ret=ret, iv_op=iv_op,
                            adq=adq, liq=liq, blocked_on=sel.get("blocked_on"))

    return {
        **base,
        "expiry": expiry,
        "chosen": chosen,
        "selection": sel,
        "per_expiry": per_expiry,
        "skipped_expiries": skipped,
        "atm_iv": atm,
        "hv": hv,
        "atr": atr,
        "iv_rank": ivr,
        "iv_vs_hv": ratio,
        "iv_opportunity": iv_op,
        "returns": ret,
        "assignment": assign,
        "required": req,
        "adequacy": adq,
        "efficiency": eff,
        "downside": downside,
        "margin_at_assignment": mos,
        "ideal_zone": zone,
        "liquidity": liq,
        "csp_score": sinfo["score"],
        "stock_score": (sinfo.get("stock") or {}).get("score"),
        "option_score": (sinfo.get("option") or {}).get("score"),
        "score_detail": sinfo,
        "final": final,
        "headline": SC.headline(sinfo, final),
        "no_trade_reason": None,
    }


def evaluate_universe(results, regime="SELECTIVE", risk_free=None,
                      min_dte=DEFAULT_MIN_DTE, max_dte=DEFAULT_MAX_DTE,
                      allow_earnings=False, limit=None, today=None,
                      raw_rows=None) -> list:
    """Every long-term result -> ranked CSP verdicts.

    Eligibility runs on all of them first and the chain work is done only
    for survivors, so a 46-name universe that yields six approved
    companies makes six chain passes, not forty-six.
    """
    ordered = sorted(
        results or [],
        key=lambda r: -(f((r.get("quality") or {}).get("score")) or 0))

    out, fetched = [], 0
    for res in ordered:
        elig = EL.classify(res)
        raw = (raw_rows or {}).get(res.get("ticker"))
        if elig["status"] == "CSP REJECTED":
            out.append(evaluate(res, regime, risk_free, min_dte, max_dte,
                                allow_earnings, today, raw))
            continue
        if limit is not None and fetched >= limit:
            continue
        fetched += 1
        try:
            out.append(evaluate(res, regime, risk_free, min_dte, max_dte,
                                allow_earnings, today, raw))
        except Exception as e:                      # one bad chain, not a run
            print(f"[CSP] {res.get('ticker')}: evaluation failed ({e})")

    rank_order = {"SELL": 0, "VERIFY": 1, "SELL_DIP": 2, "WAIT_IV": 3,
                  "WAIT_LEVEL": 4, "WATCH": 5, "REJECT": 6}
    out.sort(key=lambda r: (rank_order.get((r.get("final") or {}).get("key"), 9),
                            -(r.get("csp_score") or 0)))
    return out


def portfolio_view(rows, capital, max_single_pct=20.0,
                   max_sector_pct=35.0) -> dict:
    """Step 10 — what the SELL-rated set does to the account.

    Concentration is measured against the CSP collateral commitment, not
    against the existing portfolio: this answers "if I sold all of these
    today, what would I be on the hook for", which is the exposure a
    cash-secured put actually creates.
    """
    sells = [r for r in rows
             if (r.get("final") or {}).get("key") in ("SELL", "VERIFY",
                                                      "SELL_DIP")
             and r.get("chosen")]
    cap = f(capital) or 0.0

    positions, by_sector, total = [], {}, 0.0
    for r in sells:
        coll = (r.get("returns") or {}).get("collateral")
        if not coll:
            continue
        max_dollars = cap * max_single_pct / 100.0 if cap else None
        n = int(max_dollars // coll) if max_dollars else 1
        n = max(0, n)
        committed = n * coll
        total += committed
        sec = r.get("sector") or "Unknown"
        by_sector[sec] = by_sector.get(sec, 0.0) + committed
        positions.append({
            "ticker": r["ticker"], "sector": sec,
            "contracts": n, "collateral_each": coll,
            "committed": committed,
            "pct_of_capital": round(committed / cap * 100, 1) if cap else None,
            "premium": (r.get("returns") or {}).get("premium_total"),
        })

    warnings = []
    if cap and total > cap:
        warnings.append(f"total collateral ${total:,.0f} exceeds ${cap:,.0f} "
                        f"of capital — not all of these can be held at once")
    for sec, amt in by_sector.items():
        pct = (amt / cap * 100) if cap else 0
        if pct > max_sector_pct:
            warnings.append(f"{sec} would be {pct:.0f}% of capital "
                            f"(cap {max_sector_pct:.0f}%)")

    return {
        "positions": positions,
        "total_collateral": round(total, 2),
        "capital": cap,
        "utilisation_pct": round(total / cap * 100, 1) if cap else None,
        "by_sector": {k: round(v, 2) for k, v in by_sector.items()},
        "total_premium": round(sum(p["premium"] or 0 for p in positions), 2),
        "warnings": warnings,
    }
