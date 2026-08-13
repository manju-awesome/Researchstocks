"""
csp_view.py
===========
The Cash-Secured Put page. Presentation only — every score, level, greek
and verdict comes from core.csp and is read back out of the snapshot
core.csp.store wrote. Nothing here recomputes a number, so each expanded
row can claim to show "why" and be right.

Why a page and not a section of /longterm
------------------------------------------
The company verdict is /longterm's; this page does not second-guess it,
it consumes it. What it adds is an options layer — chains, greeks,
volatility context, strike selection and assignment analysis — which has
its own scan (minutes of network), its own snapshot, its own staleness
rules and about twenty columns of its own. Folding that into /longterm
would have buried a slow options scan inside a fast equity page and left
both harder to read.

What the layout is arguing
--------------------------
The table leads with the COMPANY (quality, valuation, margin of safety)
and only then the CONTRACT (strike, delta, premium, yield). That order is
the thesis: the objective is not premium, it is buying a good company at
a good effective cost basis while being paid to wait. A layout that led
with yield would be quietly recommending the opposite.

Annualised return is shown in muted type next to the period yield rather
than as the headline number, for the same reason. It is a comparison aid
across different DTEs, not a return anyone actually earns.
"""

from __future__ import annotations

from stockanalysis.core.csp import store as csp_store

from .views import badge, card, empty, esc, fmt_money, fmt_pct, tv_url

DASH = "—"

_FINAL_STATUS = {"SELL": "good", "SELL_DIP": "good", "VERIFY": "watch",
                 "WAIT_IV": "watch", "WAIT_LEVEL": "watch",
                 "WATCH": "info", "REJECT": "bad"}
_ELIG_STATUS = {"CSP APPROVED": "good", "CSP WATCHLIST": "watch",
                "CSP REJECTED": "bad"}
_BAND_STATUS = {"UNDERVALUED": "good", "FAIR": "watch", "OVERVALUED": "bad"}


def _n(v, nd=2, dash=DASH):
    return dash if v is None else f"{v:,.{nd}f}"


def _sub(text, colour="#898781"):
    return (f'<div style="font-size:10px;color:{colour};margin-top:2px">'
            f'{esc(text)}</div>')


def _score_cell(v, out_of=100):
    if v is None:
        return f'<span style="color:#b5b3ad">{DASH}</span>'
    colour = ("#0F6E56" if v >= 70 else "#8a6d1a" if v >= 55 else "#A32D2D")
    return (f'<span style="font-weight:700;color:{colour}">{v:.0f}</span>'
            f'<span style="font-size:10px;color:#b5b3ad">/{out_of}</span>')


# ─────────────────────────────────────────────────────────────────────────
# DETAIL — the audit behind one row
# ─────────────────────────────────────────────────────────────────────────

def _levels_block(row):
    levels = row.get("levels") or []
    anchor = ((row.get("selection") or {}).get("anchor") or {})
    if not levels:
        return _sub("no support level below spot")

    out = []
    for i, lv in enumerate(levels, 1):
        is_anchor = lv.get("price") == anchor.get("price")
        mark = " ← strike anchored here" if is_anchor else ""
        notes = ", ".join(lv.get("notes") or []) or "—"
        out.append(
            f'<div style="display:flex;justify-content:space-between;gap:8px;'
            f'padding:3px 0;font-size:11px'
            f'{";font-weight:600" if is_anchor else ""}">'
            f'<span>S{i} · {esc(lv.get("name") or "")}'
            f'<span style="color:#898781"> {esc(notes)}</span>'
            f'<span style="color:#0F6E56">{esc(mark)}</span></span>'
            f'<span>${_n(lv.get("price"))} '
            f'<span style="color:#898781">({_n(lv.get("distance_pct"), 1)}%)</span> '
            f'<span style="color:#b5b3ad">conf {lv.get("confidence")}</span>'
            f'</span></div>')
    return "".join(out)


def _conditions_block(chosen):
    fit = (chosen or {}).get("fit") or {}
    out = []
    for c in fit.get("conditions") or []:
        ok = c.get("ok")
        mark, colour = (("✓", "#0F6E56") if ok else
                        ("✗", "#A32D2D") if ok is False else ("·", "#898781"))
        out.append(f'<div style="font-size:11px;padding:2px 0;color:{colour}">'
                   f'{mark} <span style="color:#0b0b0b">{esc(c.get("text") or "")}'
                   f'</span></div>')
    return "".join(out) or _sub("no strike conditions evaluated")


def _assignment_block(row):
    a = row.get("assignment") or {}
    if not a.get("tests"):
        return _sub(a.get("reason") or "not assessed")

    verdict = a.get("happy_to_own")
    text, status = (("YES — this is a price worth owning", "good")
                    if verdict is True else
                    ("NO — the basis is not a price worth owning", "bad")
                    if verdict is False else
                    ("CANNOT TELL — missing valuation or level data", "watch"))

    tests = "".join(
        f'<div style="font-size:11px;padding:2px 0">'
        f'<span style="color:{"#0F6E56" if t.get("ok") else "#A32D2D"}">'
        f'{"✓" if t.get("ok") else "✗"}</span> {esc(t.get("text") or "")}</div>'
        for t in a["tests"])

    return (f'<div style="margin-bottom:6px">{badge(text, status)}</div>'
            f'<div style="font-size:11px;color:#898781;margin-bottom:4px">'
            f'"If assigned tomorrow, would I be happy owning 100 shares at '
            f'${_n(a.get("basis"))}?"</div>{tests}')


def _ladder_block(row):
    """The delta ladder — the choice shown against its alternatives."""
    sel = row.get("selection") or {}
    considered = sel.get("considered") or []
    if not considered:
        return ""
    chosen_k = (row.get("chosen") or {}).get("strike")
    lo, hi = sel.get("band") or (None, None)

    head = ("<tr style='font-size:10px;color:#898781;text-align:right'>"
            "<th style='text-align:left'>Strike</th><th>Δ</th><th>Bid</th>"
            "<th>Limit</th><th>Yield</th><th>Ann.</th><th>OI</th>"
            "<th>Liq</th></tr>")
    body = []
    for c in considered:
        is_chosen = c.get("strike") == chosen_k
        d = abs(c.get("delta") or 0)
        in_band = lo is not None and lo <= d <= hi
        bg = "#F1F7F4" if is_chosen else "transparent"
        colour = "#0b0b0b" if in_band else "#b5b3ad"
        body.append(
            f"<tr style='background:{bg};color:{colour};text-align:right;"
            f"font-size:11px'>"
            f"<td style='text-align:left;font-weight:{700 if is_chosen else 400}'>"
            f"${_n(c.get('strike'))}{' ←' if is_chosen else ''}</td>"
            f"<td>{_n(c.get('delta'), 3)}</td>"
            f"<td>{_n(c.get('bid'))}</td>"
            f"<td>{_n(c.get('limit_price'))}</td>"
            f"<td>{_n(c.get('yield_pct'), 2)}%</td>"
            f"<td>{_n(c.get('annualised'), 1)}%</td>"
            f"<td>{_n(c.get('open_interest'), 0)}</td>"
            f"<td>{c.get('liquidity') if c.get('liquidity') is not None else DASH}</td>"
            f"</tr>"
            f"<tr style='background:{bg}'><td colspan='8' "
            f"style='font-size:10px;color:#898781;padding:0 0 4px'>"
            f"{esc(c.get('note') or '')}</td></tr>")
    return (f"<table style='width:100%;border-collapse:collapse'>{head}"
            f"{''.join(body)}</table>"
            + _sub(f"greyed rows sit outside the {lo:.2f}-{hi:.2f} delta band "
                   f"this name qualifies for" if lo is not None else ""))


def _score_block(row):
    d = row.get("score_detail") or {}
    comps = d.get("components") or []
    if not comps:
        return _sub("not scored")
    rows_html = []
    last_group = None
    for c in comps:
        sc = c.get("score")
        if c.get("group") != last_group:
            last_group = c.get("group")
            totals = (d.get(last_group) or {}).get("score")
            rows_html.append(
                f'<div style="font-size:10px;font-weight:700;color:#0b0b0b;'
                f'margin:6px 0 2px;text-transform:uppercase">'
                f'{esc(last_group or "")} — {totals if totals is not None else "—"}'
                f'/100</div>')
        bar = "" if sc is None else (
            f'<div style="height:4px;background:#eceae4;border-radius:2px;'
            f'width:70px;display:inline-block;vertical-align:middle">'
            f'<div style="height:4px;border-radius:2px;width:{sc}%;'
            f'background:{"#0F6E56" if sc >= 70 else "#8a6d1a" if sc >= 45 else "#A32D2D"}">'
            f'</div></div>')
        rows_html.append(
            f'<div style="display:flex;justify-content:space-between;gap:8px;'
            f'font-size:11px;padding:2px 0">'
            f'<span>{esc(c["name"].title())} '
            f'<span style="color:#b5b3ad">{c["weight"]}%</span></span>'
            f'<span>{bar} '
            f'{"<span style=\'color:#b5b3ad\'>not available</span>" if sc is None else sc}'
            f'</span></div>')
    cov = d.get("coverage")
    note = ("" if cov == 100 else
            _sub(f"score built on {cov}% of the weights — the rest were "
                 f"unavailable and are excluded, not scored zero", "#8a6d1a"))
    return "".join(rows_html) + note



def _paywall_block(row):
    """Is the option worth selling — the hurdle, and what cleared it."""
    req, adq = row.get("required") or {}, row.get("adequacy") or {}
    eff = row.get("efficiency") or {}
    ret = row.get("returns") or {}
    if not req:
        return _sub("not assessed")

    out = [f'<div style="font-size:11px;line-height:1.7">'
           f'{esc(req.get("detail") or "")}</div>']
    if adq.get("ratio") is not None:
        r = adq["ratio"]
        status = "good" if r >= 1.15 else "watch" if r >= 1.0 else "bad"
        out.append(
            f'<div style="margin:6px 0">'
            f'{badge(esc(adq.get("label") or ""), status)}</div>'
            f'<div style="font-size:11px">Pays {_n(ret.get("yield_pct"), 2)}% '
            f'against a {_n(req.get("period_pct"), 2)}% requirement — '
            f'<b>{r:.2f}×</b></div>')
        if adq.get("shortfall_pct"):
            out.append(_sub(f"short by {adq['shortfall_pct']:.2f} percentage "
                            f"points of yield", "#A32D2D"))
    if req.get("binding") == "static floor":
        out.append(_sub("the flat minimum is binding here, not the "
                        "risk-based hurdle"))
    if eff.get("label"):
        out.append(f'<div style="font-size:11px;margin-top:6px">'
                   f'{esc(eff["label"])} — {esc(eff.get("detail") or "")}</div>')
        if eff.get("edge_dollars") is not None:
            out.append(_sub(f"edge over cash: ${eff['edge_dollars']:,.0f} "
                            f"for the period"))
    return "".join(out)


def _downside_block(row):
    """Premium measured against how far the stock actually moves."""
    d = row.get("downside") or {}
    mos = row.get("margin_at_assignment") or {}
    out = []
    if d.get("per_atr") is not None:
        out.append(f'<div style="font-size:11px">Premium is '
                   f'<b>{d["per_atr"]:.2f}×</b> one ATR '
                   f'(${_n(row.get("atr"))})</div>')
    if d.get("per_expected_move") is not None:
        out.append(f'<div style="font-size:11px">Premium covers '
                   f'<b>{d["per_expected_move"]*100:.0f}%</b> of a '
                   f'one-sigma move</div>')
    if d.get("technical_cushion_pct") is not None:
        out.append(f'<div style="font-size:11px">Basis sits '
                   f'<b>{d["technical_cushion_pct"]:.1f}%</b> above '
                   f'{esc(d.get("cushion_level") or "the next level")}</div>')
    if mos.get("pct") is not None:
        unit = "pp" if mos.get("basis_kind") == "growth" else "%"
        out.append(f'<div style="font-size:11px;margin-top:4px">Margin of '
                   f'safety at assignment: <b>{mos["pct"]:+.1f}{unit}</b></div>'
                   + _sub(mos.get("detail") or ""))
    return "".join(out) or _sub("no downside measures available")


def _ideal_block(row):
    """What this name WOULD be worth selling — shown even with no trade."""
    z = row.get("ideal_zone") or {}
    if not z:
        return _sub("not computed")
    lo, hi = z.get("strike_low"), z.get("strike_high")
    tl, th = z.get("target_delta") or (None, None)
    rows = [
        ("Ideal strike", f"${_n(lo)} – ${_n(hi)}" if hi else DASH),
        ("Ideal expiry", f"{z.get('dte_low')}–{z.get('dte_high')} DTE"),
        ("Minimum premium", f"${_n(z.get('min_premium'))}"),
        ("Ideal premium", f"${_n(z.get('ideal_premium'))}"),
        ("Max spread", f"{_n(z.get('max_spread_pct'), 0)}% of mid"),
        ("Target delta", f"{tl:.2f}–{th:.2f}" if tl else DASH),
        ("Target IV/realised", f"≥ {_n(z.get('target_iv_rv'), 2)}×"),
        ("Required yield", f"{_n(z.get('min_required_yield_pct'), 2)}%"),
    ]
    return "".join(
        f'<div style="display:flex;justify-content:space-between;gap:8px;'
        f'font-size:11px;padding:2px 0"><span style="color:#898781">'
        f'{esc(k)}</span><span>{v}</span></div>' for k, v in rows)


def _reference_block(row):
    """The chain for a name with no qualifying contract.

    Carries no verdict on purpose. The engine already said REJECT or
    "no strike qualifies"; this answers the different question of what
    the market is actually paying, which the verdict alone does not.
    Everything here is labelled reference so it cannot be mistaken for
    the recommendation it deliberately is not.
    """
    ref = row.get("reference") or {}
    if not ref:
        return ""
    if not ref.get("available"):
        return _sub(ref.get("why") or "chain not available")

    best = ref.get("best") or {}
    ratio = (ref.get("iv_vs_hv") or {}).get("ratio")

    head = (f'<div style="margin-bottom:6px">'
            f'{badge("REFERENCE ONLY — not a recommendation", "bad")}</div>'
            f'<div style="font-size:11px;color:#898781;margin-bottom:6px">'
            f'{esc(ref.get("why") or "")}</div>'
            f'<div style="font-size:11px">Expiry {esc(ref.get("expiry"))} '
            f'({ref.get("dte")}d) · {len(ref.get("strikes") or [])} OTM '
            f'strikes, {ref.get("fillable", 0)} fillable'
            + (f' · IV/realised {ratio:.2f}×' if ratio else '')
            + '</div>')

    if best:
        head += (
            f'<div style="margin-top:8px;padding:8px;background:#fff;'
            f'border:1px solid #eceae4;border-radius:8px;font-size:12px;'
            f'line-height:1.7">'
            f'<b>Best fillable premium</b><br>'
            f'${_n(best.get("strike"))} put · limit <b>${_n(best.get("limit_price"))}</b> '
            f'· {_n(best.get("yield_pct"), 2)}% '
            f'<span style="color:#898781">({_n(best.get("annualised"), 1)}% ann.)</span><br>'
            f'Δ {_n(best.get("delta"), 3)} '
            f'<span style="color:#898781">{esc(best.get("delta_class") or "")}</span> '
            f'· breakeven ${_n(best.get("breakeven"))} '
            f'({_n(best.get("basis_vs_spot_pct"), 1)}% vs spot)<br>'
            f'liquidity {best.get("liquidity")}/100</div>'
            + _sub("the richest premium is always the strike closest to the "
                   "money — read the delta class beside it, not the yield "
                   "alone"))
    else:
        head += _sub("no strike on this expiry is fillable — every quote is "
                     "either bidless or too wide to sell into", "#8a6d1a")

    rows_html = []
    for c in ref.get("strikes") or []:
        tradable = c.get("liquidity_tradable")
        colour = ("#b5b3ad" if tradable is False else "#0b0b0b")
        is_best = best and c.get("strike") == best.get("strike")
        bg = "#F1F7F4" if is_best else "transparent"
        rows_html.append(
            f"<tr style='background:{bg};color:{colour};text-align:right;"
            f"font-size:11px'>"
            f"<td style='text-align:left;font-weight:{700 if is_best else 400}'>"
            f"${_n(c.get('strike'))}{' ←' if is_best else ''}</td>"
            f"<td>{_n(c.get('delta'), 3)}</td>"
            f"<td style='text-align:left;color:#898781'>"
            f"{esc(c.get('delta_class') or '')}</td>"
            f"<td>{_n(c.get('bid'))}</td>"
            f"<td>{_n(c.get('ask'))}</td>"
            f"<td>{_n(c.get('limit_price'))}</td>"
            f"<td>{_n(c.get('yield_pct'), 2)}%</td>"
            f"<td>{_n(c.get('annualised'), 1)}%</td>"
            f"<td>${_n(c.get('breakeven'))}</td>"
            f"<td>{_n(c.get('spread_pct'), 1)}%</td>"
            f"<td>{_n(c.get('open_interest'), 0)}</td>"
            f"<td>{c.get('liquidity') if c.get('liquidity') is not None else DASH}</td>"
            f"</tr>")

    head += (
        f'<div style="overflow-x:auto;margin-top:8px">'
        f'<table style="width:100%;border-collapse:collapse">'
        f"<tr style='font-size:10px;color:#898781;text-align:right'>"
        f"<th style='text-align:left'>Strike</th><th>Δ</th>"
        f"<th style='text-align:left'>Class</th><th>Bid</th><th>Ask</th>"
        f"<th>Limit</th><th>Yield</th><th>Ann.</th><th>Breakeven</th>"
        f"<th>Spread</th><th>OI</th><th>Liq</th></tr>"
        f'{"".join(rows_html)}</table></div>'
        + _sub("greyed rows are not fillable — bidless, or quoted too wide "
               "to sell into"))
    return head


def _detail(row):
    chosen = row.get("chosen") or {}
    elig = row.get("eligibility") or {}
    disc = row.get("discount") or {}
    ret = row.get("returns") or {}

    def panel(title, body):
        return (f'<div style="flex:1;min-width:260px">'
                f'<div style="font-size:10px;font-weight:700;color:#898781;'
                f'text-transform:uppercase;letter-spacing:.04em;'
                f'margin-bottom:4px">{esc(title)}</div>{body}</div>')

    # Why the company qualifies.
    why = "".join(f'<div style="font-size:11px;padding:2px 0">✓ {esc(r)}</div>'
                  for r in elig.get("reasons") or [])
    for b in elig.get("blockers") or []:
        why += (f'<div style="font-size:11px;padding:2px 0;color:#A32D2D">'
                f'✗ {esc(b)}</div>')
    for sft in elig.get("softs") or []:
        why += (f'<div style="font-size:11px;padding:2px 0;color:#8a6d1a">'
                f'! {esc(sft)}</div>')
    why += _sub(f"{esc(disc.get('method') or '')} · {esc(disc.get('detail') or '')}")

    # Volatility.
    ivr, ratio = row.get("iv_rank") or {}, row.get("iv_vs_hv") or {}
    op = row.get("iv_opportunity") or {}
    if ivr.get("available"):
        vol_html = (f'<div style="font-size:11px">IV Rank '
                    f'<b>{_n(ivr.get("rank"), 0)}</b> over '
                    f'{ivr.get("observations")} days '
                    f'({_n(ivr.get("low"), 0)}%–{_n(ivr.get("high"), 0)}%)</div>')
    else:
        vol_html = (f'<div style="font-size:11px;color:#8a6d1a">IV Rank '
                    f'unavailable — {esc(ivr.get("reason") or "")}</div>')
    if ratio.get("ratio") is not None:
        vol_html += (f'<div style="font-size:11px;margin-top:3px">'
                     f'{esc(ratio.get("label") or "")} — IV {_n(ratio.get("iv"), 1)}% '
                     f'vs realised {_n(ratio.get("hv"), 1)}% '
                     f'({ratio["ratio"]:.2f}×)</div>')
    vol_html += _sub(f"scored on: {esc(op.get('source') or 'nothing available')}")

    # The contract.
    if chosen:
        contract = (
            f'<div style="font-size:12px;line-height:1.7">'
            f'<b>Sell 1 {esc(row.get("ticker"))} {esc(row.get("expiry") or "")} '
            f'${_n(chosen.get("strike"), 2)} PUT</b><br>'
            f'Limit <b>${_n(chosen.get("limit_price"))}</b> '
            f'<span style="color:#898781">(bid {_n(chosen.get("bid"))} / '
            f'ask {_n(chosen.get("ask"))}, mid {_n(chosen.get("mid"))})</span><br>'
            f'Collateral ${_n(ret.get("collateral"), 0)} · '
            f'credit ${_n(ret.get("premium_total"), 0)}<br>'
            f'Breakeven <b>${_n(chosen.get("breakeven"))}</b> '
            f'({_n(chosen.get("breakeven_pct"), 1)}% vs spot)<br>'
            f'Δ {_n(chosen.get("delta"), 3)} · θ {_n(chosen.get("theta"), 3)}/day · '
            f'vega {_n(chosen.get("vega"), 3)} · γ {_n(chosen.get("gamma"), 4)}<br>'
            f'Model P(profit) {_n((chosen.get("prob_profit") or 0) * 100, 1)}% · '
            f'P(assigned) {_n((chosen.get("prob_itm") or 0) * 100, 1)}%<br>'
            f'Expected move ±${_n(chosen.get("expected_move"))} over '
            f'{chosen.get("dte")}d</div>')
        liq_notes = chosen.get("liquidity_notes") or []
        if liq_notes:
            contract += _sub("liquidity: " + "; ".join(liq_notes), "#8a6d1a")
    else:
        contract = _sub(row.get("no_trade_reason") or "no contract selected")

    skipped = row.get("skipped_expiries") or []
    if skipped:
        contract += "".join(
            _sub(f"skipped {s.get('expiry')}: {s.get('why')}", "#8a6d1a")
            for s in skipped)

    panels = (panel("Why this company", why)
              + panel("Support levels", _levels_block(row))
              + panel("Why this strike", _conditions_block(chosen))
              + panel("Is the option worth selling?", _paywall_block(row))
              + panel("Volatility", vol_html)
              + panel("Premium vs downside", _downside_block(row))
              + panel("The contract", contract)
              + panel("If assigned", _assignment_block(row))
              + panel("Ideal CSP zone", _ideal_block(row))
              + panel("Score breakdown", _score_block(row))
              + panel("Strikes considered", _ladder_block(row)))

    ref = _reference_block(row)
    ref_html = (f'<div style="flex:1 1 100%;border-top:1px solid #eceae4;'
                f'padding-top:10px;margin-top:2px">'
                f'<div style="font-size:10px;font-weight:700;color:#898781;'
                f'text-transform:uppercase;letter-spacing:.04em;'
                f'margin-bottom:4px">What the chain is paying anyway</div>'
                f'{ref}</div>') if ref else ""

    return (f'<div style="display:flex;flex-wrap:wrap;gap:18px;padding:12px 14px;'
            f'background:#faf9f7;border-top:1px solid #eceae4">'
            f'{panels}{ref_html}</div>')


# ─────────────────────────────────────────────────────────────────────────
# TABLE
# ─────────────────────────────────────────────────────────────────────────

# Company columns first, contract columns second, the two scores side by
# side. The split is the argument: an excellent stock and a mediocre
# option should be legible as exactly that at a glance.
_COLUMNS = ("Ticker", "Quality", "Valuation", "Margin", "Price",
            "Strike", "Δ", "Class", "Expiry", "DTE", "ER",
            "Limit", "Yield", "vs req.", "IV/RV", "Spread", "Basis",
            "STOCK", "OPTION", "CSP", "Action")


def _row(row, idx):
    chosen = row.get("chosen") or {}
    elig = row.get("eligibility") or {}
    disc = row.get("discount") or {}
    ret = row.get("returns") or {}
    final = row.get("final") or {}
    adq = row.get("adequacy") or {}
    assign = row.get("assignment") or {}

    tk = row.get("ticker") or "?"
    band = elig.get("valuation_band")
    dte_v = chosen.get("dte")
    er = row.get("days_to_earnings")

    margin = disc.get("margin_pct")
    margin_txt = (DASH if margin is None else
                  f"{margin:+.1f}{'pp' if disc.get('basis') == 'growth' else '%'}")

    ratio = (row.get("iv_vs_hv") or {}).get("ratio")
    iv_txt = DASH if ratio is None else (
        f'<span style="color:'
        f'{"#0F6E56" if ratio >= 1.0 else "#8a6d1a" if ratio >= 0.85 else "#A32D2D"}">'
        f'{ratio:.2f}×</span>')

    # Adequacy is the option's headline: yield against the hurdle it had
    # to clear, not the yield on its own.
    adq_txt = DASH if adq.get("ratio") is None else (
        f'<span style="font-weight:600;color:'
        f'{"#0F6E56" if adq["ratio"] >= 1.15 else "#8a6d1a" if adq["ratio"] >= 1.0 else "#A32D2D"}">'
        f'{adq["ratio"]:.2f}×</span>'
        + _sub(f"need {_n((row.get('required') or {}).get('period_pct'), 2)}%"))

    sp = chosen.get("spread_pct")
    sv = chosen.get("spread_verdict")
    sp_colour = {"EXCELLENT": "#0F6E56", "ACCEPTABLE": "#0F6E56",
                 "CAUTION": "#8a6d1a", "REJECT": "#A32D2D",
                 "UNKNOWN": "#898781"}.get(sv, "#898781")
    sp_txt = (DASH if sp is None else
              f'<span style="color:{sp_colour}">{sp:.1f}%</span>'
              + (_sub("closed — unverified") if sv == "UNKNOWN" else ""))

    er_txt = (DASH if er is None else
              f"<span style='color:{'#A32D2D' if er <= (dte_v or 0) else '#0b0b0b'}'>"
              f"{er:.0f}d</span>")

    cells = [
        (f'<a href="{tv_url(tk)}" target="_blank" style="font-weight:700;'
         f'color:#0b0b0b;text-decoration:none">{esc(tk)}</a>'
         + _sub(row.get("sector") or "")),
        _score_cell(elig.get("quality_score")) + _sub(elig.get("quality_tier") or ""),
        badge(band or DASH, _BAND_STATUS.get(band, "muted")),
        margin_txt,
        f"${_n(row.get('price'))}",
        (f"<b>${_n(chosen.get('strike'))}</b>" if chosen else DASH),
        _n(chosen.get("delta"), 3),
        _sub(chosen.get("delta_class") or "") if chosen else DASH,
        esc(row.get("expiry") or DASH),
        str(dte_v) if dte_v is not None else DASH,
        er_txt,
        (f"<b>${_n(chosen.get('limit_price'))}</b>" if chosen else DASH),
        ((f"{_n(ret.get('yield_pct'), 2)}%"
          + _sub(f"{_n(ret.get('annualised'), 1)}% ann.")) if ret.get("yield_pct")
         is not None else DASH),
        adq_txt,
        iv_txt,
        sp_txt,
        (f"${_n(assign.get('basis'))}" if assign.get("basis") else DASH),
        _score_cell(row.get("stock_score")),
        _score_cell(row.get("option_score")),
        _score_cell(row.get("csp_score")),
        badge(final.get("action") or DASH,
              _FINAL_STATUS.get(final.get("key"), "muted")),
    ]

    tds = "".join(f'<td style="padding:7px 8px;vertical-align:top;'
                  f'font-size:12px">{c}</td>' for c in cells)

    head = row.get("headline")
    why = esc(final.get("why") or "")
    summary = ((f'<b style="color:#0b0b0b">{esc(head)}</b> — ' if head else "")
               + why)
    return (
        f'<tr onclick="cspToggle({idx})" style="cursor:pointer;'
        f'border-top:1px solid #eceae4">{tds}</tr>'
        f'<tr><td colspan="{len(_COLUMNS)}" style="padding:0 8px 6px;'
        f'font-size:11px;color:#898781">{summary}</td></tr>'
        f'<tr id="csp-d-{idx}" style="display:none"><td colspan="{len(_COLUMNS)}" '
        f'style="padding:0">{_detail(row)}</td></tr>')


def _rejected_block(rows):
    """Rejections as a compact list, grouped by the rule that fired.

    These are rendered separately from the main table rather than as
    more rows in it. On a typical run they outnumber the candidates
    fifty to one, and giving each a full audit panel produced a
    multi-megabyte page that buried the handful of names worth reading.

    They are still shown, because "what did the engine throw out, and on
    what rule" is most of the value on a day when nothing qualifies —
    just shown at the density that volume deserves.
    """
    if not rows:
        return ""

    def bucket(r):
        why = ((r.get("final") or {}).get("why") or "").lower()
        if "overvalued" in why:                     return "Overvalued"
        if "lquality" in why or "quality" in why:   return "Quality below the floor"
        if "stage 4" in why:                        return "Stage 4 markdown"
        if "spread" in why or "liquidity" in why or "fillable" in why:
            return "Options too illiquid"
        if "earnings" in why:                       return "Earnings inside the expiry"
        if "trend" in why:                          return "Trend broken"
        if "no listed options" in why:              return "No listed options"
        if "happy owning" in why:                   return "Cost basis not worth owning"
        if "event pricing" in why:                  return "Premium is event-priced"
        return "Other"

    groups = {}
    for r in rows:
        groups.setdefault(bucket(r), []).append(r)

    blocks = []
    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        tickers = ", ".join(
            f'<span title="{esc((i.get("final") or {}).get("why") or "")}">'
            f'{esc(i.get("ticker") or "?")}</span>'
            for i in sorted(items, key=lambda x: x.get("ticker") or ""))
        blocks.append(
            f'<details style="margin-bottom:6px">'
            f'<summary style="cursor:pointer;font-size:12px;font-weight:600">'
            f'{esc(name)} <span style="color:#898781;font-weight:400">'
            f'({len(items)})</span></summary>'
            f'<div style="font-size:11px;color:#898781;line-height:1.9;'
            f'padding:6px 0 2px">{tickers}</div></details>')

    return ("".join(blocks)
            + _sub("hover a ticker for the exact rule that rejected it"))


def _table(rows, start=0):
    if not rows:
        return empty("No candidates in this snapshot.")
    head = "".join(f'<th style="padding:6px 8px;text-align:left;font-size:10px;'
                   f'color:#898781;text-transform:uppercase;'
                   f'letter-spacing:.04em">{esc(c)}</th>' for c in _COLUMNS)
    body = "".join(_row(r, start + i) for i, r in enumerate(rows))
    return (f'<div style="overflow-x:auto"><table style="width:100%;'
            f'border-collapse:collapse"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


# ─────────────────────────────────────────────────────────────────────────
# PORTFOLIO / CONTROLS / PAGE
# ─────────────────────────────────────────────────────────────────────────

def _portfolio_block(pf):
    if not pf or not pf.get("positions"):
        return empty("No SELL-rated trades to size.")
    rows = "".join(
        f'<tr style="border-top:1px solid #eceae4;font-size:12px">'
        f'<td style="padding:5px 8px"><b>{esc(p["ticker"])}</b></td>'
        f'<td style="padding:5px 8px;color:#898781">{esc(p["sector"])}</td>'
        f'<td style="padding:5px 8px;text-align:right">{p["contracts"]}</td>'
        f'<td style="padding:5px 8px;text-align:right">'
        f'${_n(p["collateral_each"], 0)}</td>'
        f'<td style="padding:5px 8px;text-align:right">'
        f'${_n(p["committed"], 0)}</td>'
        f'<td style="padding:5px 8px;text-align:right">'
        f'{_n(p.get("pct_of_capital"), 1)}%</td>'
        f'<td style="padding:5px 8px;text-align:right;color:#0F6E56">'
        f'${_n(p.get("premium"), 0)}</td></tr>' for p in pf["positions"])

    warn = "".join(f'<div style="margin-top:6px">{badge(esc(w), "bad")}</div>'
                   for w in pf.get("warnings") or [])

    return (
        f'<table style="width:100%;border-collapse:collapse">'
        f'<tr style="font-size:10px;color:#898781;text-transform:uppercase">'
        f'<th style="text-align:left;padding:4px 8px">Ticker</th>'
        f'<th style="text-align:left;padding:4px 8px">Sector</th>'
        f'<th style="text-align:right;padding:4px 8px">Contracts</th>'
        f'<th style="text-align:right;padding:4px 8px">Collateral each</th>'
        f'<th style="text-align:right;padding:4px 8px">Committed</th>'
        f'<th style="text-align:right;padding:4px 8px">% capital</th>'
        f'<th style="text-align:right;padding:4px 8px">Credit</th></tr>'
        f'{rows}</table>'
        f'<div style="margin-top:8px;font-size:12px">'
        f'Total collateral <b>${_n(pf.get("total_collateral"), 0)}</b> of '
        f'${_n(pf.get("capital"), 0)} '
        f'({_n(pf.get("utilisation_pct"), 1)}% utilised) · '
        f'total credit <b style="color:#0F6E56">'
        f'${_n(pf.get("total_premium"), 0)}</b></div>{warn}')


def _controls(meta, typed=""):
    """The scan form. The ticker box does double duty.

    Typing names filters the stored snapshot instantly — no network, no
    job — because most of the time the question is "what did the last
    scan say about NEM" and re-scanning to answer it is absurd. Pressing
    Run with names in the box scans only those, which is the answer to
    the other question: "the snapshot is stale / this name was never
    scanned, go look now."
    """
    return (
        f'<form onsubmit="return cspRun(event)" '
        f'style="display:flex;gap:10px;align-items:end;flex-wrap:wrap">'
        f'<label style="font-size:11px;color:#898781;flex:1;min-width:240px">'
        f'Tickers<br>'
        f'<input name="tickers" value="{esc(typed)}" '
        f'placeholder="NEM, RMD — blank scans the whole library" '
        f'style="width:100%;padding:6px 9px;border:1px solid #d9d7ce;'
        f'border-radius:6px;font-size:13px"></label>'
        f'<label style="font-size:11px;color:#898781">Min DTE<br>'
        f'<input name="min_dte" type="number" value="{meta.get("min_dte", 20)}" '
        f'style="width:70px;padding:5px;border:1px solid #d9d7ce;'
        f'border-radius:6px"></label>'
        f'<label style="font-size:11px;color:#898781">Max DTE<br>'
        f'<input name="max_dte" type="number" value="{meta.get("max_dte", 45)}" '
        f'style="width:70px;padding:5px;border:1px solid #d9d7ce;'
        f'border-radius:6px"></label>'
        f'<label style="font-size:11px;color:#898781">Max names<br>'
        f'<input name="limit" type="number" value="25" '
        f'style="width:70px;padding:5px;border:1px solid #d9d7ce;'
        f'border-radius:6px"></label>'
        f'<label style="font-size:11px;color:#898781;display:flex;gap:5px;'
        f'align-items:center;padding-bottom:6px">'
        f'<input name="allow_earnings" type="checkbox" '
        f'{"checked" if meta.get("allow_earnings") else ""}> '
        f'allow expiries spanning earnings</label>'
        f'<button type="button" onclick="cspFilter()" class="btn secondary" '
        f'style="padding:7px 14px">Filter</button>'
        f'<button type="submit" class="btn" style="padding:7px 16px">'
        f'Run CSP scan</button>'
        + (f'<a href="/csp" class="btn secondary" style="text-decoration:none;'
           f'padding:7px 14px">Clear</a>' if typed else "")
        + f'<span id="csp-msg" style="font-size:11px;color:#898781"></span>'
        f'</form>')


def _lookup_block(typed, wanted, shown, slim_only, missing):
    """What the snapshot can and cannot answer for the typed names."""
    if not wanted:
        return ""
    bits = []
    if shown:
        bits.append(badge(f"{len(shown)} found", "good"))
    if slim_only:
        bits.append(badge(f"{len(slim_only)} rejected — audit not stored",
                          "watch"))
    if missing:
        bits.append(badge(f"{len(missing)} not in the last scan", "bad"))

    notes = []
    if slim_only:
        # Rejected rows are pruned on save, so the detail panel genuinely
        # is not there to render. Say so rather than showing an empty one.
        notes.append(
            f'<b>{esc(", ".join(slim_only))}</b> — the last scan rejected '
            f'these and stored only the rule that fired, not the full '
            f'audit. Press <b>Run CSP scan</b> with them in the box to '
            f're-scan and keep the whole reasoning.')
    if missing:
        notes.append(
            f'<b>{esc(", ".join(missing))}</b> — not in the last scan. '
            f'Either outside the research library, or past the scan\'s '
            f'name cap. Press <b>Run CSP scan</b> to fetch chains for them '
            f'now; it merges into the snapshot rather than replacing it.')

    return (f'<div style="margin-top:8px;display:flex;gap:6px;'
            f'flex-wrap:wrap">{"".join(bits)}</div>'
            + "".join(f'<div style="font-size:11px;color:#898781;'
                      f'margin-top:5px;line-height:1.6">{n}</div>'
                      for n in notes))


def csp_page(query: dict | None = None) -> tuple[str, str]:
    from stockanalysis.webapp.longterm_view import parse_tickers

    snap = csp_store.load()
    meta = snap or {}
    all_rows = (snap or {}).get("rows") or []

    typed = ((query or {}).get("tickers") or [""])[0]
    wanted = parse_tickers(typed)

    rows = all_rows
    slim_only, missing, shown = [], [], []
    if wanted:
        by_ticker = {str(r.get("ticker") or "").upper(): r for r in all_rows}
        rows = []
        for tk in wanted:
            r = by_ticker.get(tk)
            if r is None:
                missing.append(tk)
                continue
            rows.append(r)
            # `eligibility` is the marker, NOT `score_detail`. A rejected
            # company never gets a score at all — evaluate() returns
            # before scoring — so score_detail is absent on a FULL
            # rejected row too, and using it reported every stored
            # rejection as "audit not stored" when the audit was there.
            (shown if r.get("eligibility") else slim_only).append(tk)

    age_text, age_status = csp_store.age_note(snap)

    counts = {}
    for r in rows:
        k = (r.get("final") or {}).get("key") or "?"
        counts[k] = counts.get(k, 0) + 1

    pills = "".join(badge(f"{counts.get(k, 0)} {lbl}", st)
                    for k, lbl, st in (
                        ("SELL", "sell", "good"),
                        ("VERIFY", "verify at open", "watch"),
                        ("SELL_DIP", "sell on dip", "good"),
                        ("WAIT_IV", "wait for IV", "watch"),
                        ("WAIT_LEVEL", "wait for level", "watch"),
                        ("WATCH", "watch", "info"),
                        ("REJECT", "reject", "bad")) if counts.get(k))

    eligible = f"{meta.get('eligible', 0)}/{meta.get('universe', 0)} eligible"
    header = (
        f'<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;'
        f'margin-bottom:8px">'
        f'{badge(age_text, age_status)}'
        f'{badge("regime " + str(meta.get("regime") or "?"), "info")}'
        + (badge(f"filtered to {len(rows)} of {len(all_rows)}", "info")
           if wanted else badge(eligible, "muted"))
        + f'{pills}</div>')

    thesis = (
        '<div style="font-size:11px;color:#898781;line-height:1.6;'
        'margin-bottom:10px">'
        'The objective is <b>not</b> to maximise premium: it is to buy a '
        'high-quality, undervalued company at an attractive effective cost '
        'basis while being paid to wait. Eligibility is decided on the '
        'company alone, before any option chain is fetched — so a rich '
        'premium can never rescue a name that failed on quality or '
        'valuation. Strikes are anchored to support levels the Long-Term '
        'engine computed, then checked against a delta band; delta is a '
        'constraint here, not the selector. Click any row for the full '
        'audit.<br><br>'
        '<b>STOCK and OPTION are scored separately and multiplied.</b> '
        '"Would I want to own this company?" and "is this put worth '
        'selling today?" are different questions, and a single blended '
        'score lets an excellent answer to the first carry a poor answer '
        'to the second — which is exactly how a great business becomes a '
        'mediocre trade. A product means neither half can rescue the '
        'other.</div>')

    live = [r for r in rows if (r.get("final") or {}).get("key") != "REJECT"]
    rejected = [r for r in rows if (r.get("final") or {}).get("key") == "REJECT"]

    body = (
        card("Cash-Secured Put Engine",
             header + thesis + _controls(meta, typed)
             + _lookup_block(typed, wanted, shown, slim_only, missing),
             icon="🪙")
        + card("Opportunities", _table(live), icon="📋")
        + card("Collateral & concentration",
               _portfolio_block(meta.get("portfolio")), icon="🧮")
        + card(f"Rejected ({len(rejected)})",
               # A named lookup gets the full table: you asked about this
               # ticker, so "rejected, and here is the reading" is the
               # answer, not a name in a grouped list.
               _table(rejected, len(live)) if wanted
               else _rejected_block(rejected),
               icon="🚫"))

    js = """
function cspToggle(i){
  var el=document.getElementById('csp-d-'+i);
  if(el) el.style.display = el.style.display==='none' ? '' : 'none';
}
function cspFilter(){
  var v=document.querySelector('input[name=tickers]').value.trim();
  window.location = '/csp' + (v ? '?tickers=' + encodeURIComponent(v) : '');
}
function cspRun(e){
  e.preventDefault();
  var f=e.target, msg=document.getElementById('csp-msg');
  var b=new URLSearchParams(new FormData(f)); b.append('action','csp_scan');
  msg.textContent='starting…';
  fetch('/run',{method:'POST',body:b})
    .then(function(r){return r.json()})
    .then(function(d){
      msg.textContent=d.message||'';
      if(d.ok) msg.textContent='Scan started — this takes a few minutes. '
        +'Reload when the job tray clears.';
    })
    .catch(function(){msg.textContent='could not start the scan'});
  return false;
}
"""
    return body, js
