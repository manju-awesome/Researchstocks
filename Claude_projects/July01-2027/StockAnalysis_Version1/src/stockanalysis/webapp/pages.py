"""
pages.py
========
The five page bodies (Dashboard, Scanner, Research, Portfolio, Automation).
Each function returns an HTML string that views.render_page() wraps in the
shared layout. Reads whatever structured data is available (snapshot.json,
research_index.json, the latest scan CSV, portfolio.csv) and always has a
friendly empty state when nothing has been generated yet — a fresh checkout
should never show a stack trace.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import jobstore
from .views import (
    OUTPUT_DIR, DATA_DIR, esc, badge, stars, action_badge, progress_bar,
    card, empty, fmt_money, fmt_pct,
)


def _latest(pattern: str | tuple[str, ...], n: int = 1,
           base: Path = OUTPUT_DIR) -> list[Path]:
    patterns = (pattern,) if isinstance(pattern, str) else pattern
    seen, files = set(), []
    for p in patterns:
        for f in base.glob(p):
            if f not in seen:
                seen.add(f)
                files.append(f)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:n]


# Dashboard filenames: "<universe>Report_<ts>.html" (current) — the legacy
# "dashboard_<ts>.html" is still matched so pre-existing files keep showing
# up in listings and remain eligible for cleanup after the rename.
DASHBOARD_PATTERNS = ("*Report_*.html", "dashboard_*.html")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD (home)
# ─────────────────────────────────────────────────────────────────────────────

def dashboard_page() -> tuple[str, str]:
    snap = _read_json(OUTPUT_DIR / "snapshot.json")
    if not snap:
        return card("", empty(
            "No scan yet. Click “+ New Scan” above to run your first scan — "
            "this page fills in with market status, opportunities, and alerts "
            "once a scan completes."), pad="40px"), ""

    regime = snap.get("regime") or {}
    opp = snap.get("opportunity") or {}
    market = snap.get("market") or {}
    pf = (snap.get("portfolio") or {}).get("totals") or {}
    alerts = (snap.get("portfolio") or {}).get("alerts") or []

    regime_status = {"Bullish": "good", "Neutral": "watch",
                     "Defensive": "bad"}.get(regime.get("regime"), "muted")

    # ── Market status strip ─────────────────────────────────────────────────
    def _idx_tile(label, price, chg, strength):
        color = "#0F6E56" if (chg or 0) >= 0 else "#A32D2D"
        return (f'<div style="flex:1;min-width:110px">'
                f'<div style="font-size:11px;color:#898781">{label}</div>'
                f'<div style="font-size:16px;font-weight:600">{fmt_money(price) if price else "—"} '
                f'<span style="color:{color};font-size:12px">{fmt_pct(chg)}</span></div>'
                f'{badge(strength, {"STRONG":"good","WEAK":"bad"}.get(strength,"watch"), "small") if strength else ""}'
                f'</div>')

    market_html = (
        '<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:center">'
        + _idx_tile("SPY", market.get("spy_price"), market.get("spy_chg_pct"), market.get("spy_strength"))
        + _idx_tile("QQQ", market.get("qqq_price"), market.get("qqq_chg_pct"), market.get("qqq_strength"))
        + f'<div style="flex:1;min-width:110px"><div style="font-size:11px;color:#898781">VIX</div>'
          f'<div style="font-size:16px;font-weight:600">{market.get("vix") if market.get("vix") is not None else "—"}</div></div>'
        + f'<div style="margin-left:auto">{badge(regime.get("regime", "Unknown").upper(), regime_status)}</div>'
        + '</div>'
        + f'<div style="font-size:11px;color:#898781;margin-top:8px">{esc(regime.get("guidance", ""))}</div>')

    # ── Hero: today's opportunity ───────────────────────────────────────────
    risk_status = {"LOW": "good", "MEDIUM": "watch", "HIGH": "bad"}.get(opp.get("risk"), "muted")
    hero = f"""
    <div style="display:flex;gap:28px;align-items:center;flex-wrap:wrap">
      <div>
        <div style="font-size:11px;font-weight:600;color:#898781">TODAY'S OPPORTUNITY</div>
        <div style="font-size:40px;font-weight:650;line-height:1.1">
          {opp.get('score', '—')}<span style="font-size:18px;color:#898781">/100</span></div>
        {stars(opp.get('stars', 0), 17)}
      </div>
      <div style="flex:1;min-width:180px">
        <div style="font-size:15px;font-weight:500">{esc(opp.get('label', ''))}</div>
        <div style="font-size:12px;color:#52514e;margin-top:3px">{opp.get('n_ready', 0)} name(s) ready 🟢</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;font-weight:600;color:#898781">RISK</div>
        {badge(opp.get('risk', '—'), risk_status)}
      </div>
    </div>"""

    # ── Portfolio summary card ──────────────────────────────────────────────
    gain = pf.get("total_gain")
    gain_color = "good" if (gain or 0) >= 0 else "bad"
    pf_body = (
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px">'
        f'<div><div style="font-size:11px;color:#898781">Portfolio Value</div>'
        f'<div style="font-size:18px;font-weight:600">{fmt_money(pf.get("portfolio_value"), 0)}</div></div>'
        f'<div><div style="font-size:11px;color:#898781">Invested</div>'
        f'<div style="font-size:18px;font-weight:600">{fmt_money(pf.get("total_value"), 0)} '
        f'<span style="font-size:11px;color:#898781">({pf.get("invested_pct") or 0:g}%)</span></div></div>'
        f'<div><div style="font-size:11px;color:#898781">Total Gain</div>'
        f'<div style="font-size:18px;font-weight:600">{badge(fmt_money(gain, 0) if gain is not None else "—", gain_color)}</div></div>'
        f'<div><div style="font-size:11px;color:#898781">Cash</div>'
        f'<div style="font-size:18px;font-weight:600">{fmt_money(pf.get("cash"), 0)}</div></div>'
        f'</div>'
        if pf.get("positions") is not None else empty("No portfolio configured — see the Portfolio page."))

    # ── Top opportunity cards ───────────────────────────────────────────────
    def _opp_col(title, icon, items):
        if not items:
            return f'<div style="flex:1;min-width:200px"><div style="font-size:12px;font-weight:600;margin-bottom:8px">{icon} {title}</div>{empty("none qualified")}</div>'
        rows = "".join(
            f'<a href="/research/{r["ticker"]}.html" style="display:block;text-decoration:none;color:#0b0b0b;'
            f'padding:8px 10px;border-radius:8px;background:#f9f9f7;margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<b>{r["ticker"]}</b>{action_badge(r.get("action"), "small")}</div>'
            f'<div style="font-size:11px;color:#898781;margin-top:2px">'
            f'{fmt_money(r.get("price"))} · score {r.get("score")} · {esc(r.get("action_reason") or "")}</div></a>'
            for r in items[:3])
        return f'<div style="flex:1;min-width:200px"><div style="font-size:12px;font-weight:600;margin-bottom:8px">{icon} {title}</div>{rows}</div>'

    opp_cols = (
        '<div style="display:flex;gap:16px;flex-wrap:wrap">'
        + _opp_col("Day Trade", "🔥", snap.get("top_day") or [])
        + _opp_col("Swing", "🚀", snap.get("top_swing") or [])
        + _opp_col("Long Term", "💎", snap.get("top_longterm") or [])
        + '</div>')

    # ── Alerts ───────────────────────────────────────────────────────────────
    if alerts:
        alerts_html = "".join(
            f'<div style="font-size:12px;padding:6px 0;border-top:0.5px solid #f1efea">'
            f'{badge(a["ticker"], "bad" if a["severity"]=="high" else "watch", "small")} '
            f'{esc(a["text"])}</div>' for a in alerts[:8])
    else:
        alerts_html = empty("No alerts — all monitored positions clear.")

    # ── Recovery watch + econ headlines (compact) ───────────────────────────
    recovery = snap.get("recovery") or []
    rec_html = "".join(
        f'<a href="/research/{r["ticker"]}.html" class="chip">'
        f'{ {"Bottoming":"🔴","Recovering":"🟡","Trend Confirmed":"🟢"}.get(r.get("stage"), "") } '
        f'{r["ticker"]}</a>' for r in recovery) or empty("none identified")

    econ = snap.get("econ_headlines") or []
    econ_html = "".join(
        f'<div style="font-size:11px;padding:5px 0;border-top:0.5px solid #f1efea">'
        f'<span style="color:#898781">{esc(h.get("when",""))}</span> {esc(h.get("title",""))[:110]}</div>'
        for h in econ[:4]) or empty("none captured this scan")

    # ── Recent research + dashboards ────────────────────────────────────────
    idx = _read_json(OUTPUT_DIR / "research_index.json") or {}
    recent_research = sorted(idx.values(), key=lambda r: r.get("updated_at") or "",
                             reverse=True)[:6]
    rr_html = "".join(
        f'<a href="/research/{r["ticker"]}.html" style="display:flex;justify-content:space-between;'
        f'text-decoration:none;color:#0b0b0b;font-size:12px;padding:5px 0;border-top:0.5px solid #f1efea">'
        f'<span><b>{r["ticker"]}</b> <span style="color:#898781">{esc(r.get("sector") or "")}</span></span>'
        f'{action_badge(r.get("conv_action"), "small")}</a>' for r in recent_research
    ) or empty("none yet")

    dashboards = _latest(DASHBOARD_PATTERNS, 5)
    dash_html = "".join(
        f'<div style="font-size:12px;padding:4px 0"><a href="/{f.name}">📊 {f.name}</a></div>'
        for f in dashboards) or empty("none yet")

    body = (
        card("Market Status", market_html, "🌐")
        + _ai_sentiment_teaser()
        + card("", hero, pad="20px 24px")
        + card("Portfolio", pf_body, "💼", right='<a href="/portfolio" style="font-size:11px">View all →</a>')
        + card("Today's Opportunities", opp_cols, "🎯",
              right='<a href="/scanner" style="font-size:11px">Run new scan →</a>')
        + f"""<div style="display:flex;gap:16px;flex-wrap:wrap">
             <div style="flex:1;min-width:260px">{card("Recent Alerts", alerts_html, "🔔")}
                {card("Turnaround Watch", rec_html, "🔧")}</div>
             <div style="flex:1;min-width:260px">{card("Latest News", econ_html, "📰")}
                {card("Recent Research", rr_html, "🔎", right='<a href="/research" style="font-size:11px">Library →</a>')}
                {card("Recent Dashboards", dash_html, "📊")}</div>
           </div>"""
    )
    extra_js = "function onJobFinished(j) { setTimeout(() => location.reload(), 1200); }"
    return body, extra_js


# ─────────────────────────────────────────────────────────────────────────────
# AI SENTIMENT
# ─────────────────────────────────────────────────────────────────────────────

def _ai_sentiment_teaser() -> str:
    """Compact score+link card for the home Dashboard — hidden until the
    first AI Sentiment refresh has run, same "no stack trace on fresh
    checkout" convention as the rest of this file."""
    snap = _read_json(OUTPUT_DIR / "ai_sentiment.json")
    if not snap:
        return ""
    s = snap.get("sentiment") or {}
    score = s.get("score")
    status = "good" if (score or 0) > 70 else ("watch" if (score or 0) >= 40 else "bad")
    body = (
        '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">'
        f'<div style="font-size:28px;font-weight:700">{score if score is not None else "—"}'
        f'<span style="font-size:13px;color:#898781">/100</span></div>'
        + badge(s.get("label", "—"), status)
        + '<a href="/ai-sentiment" style="margin-left:auto;font-size:11px">View AI Sentiment →</a>'
        + '</div>')
    return card("AI Sentiment", body, "🤖")


def _refresh_ai_sentiment_form(generated_at: str = "") -> str:
    note = (f'<span style="font-size:11px;color:#898781;margin-left:10px">'
            f'Last updated {esc(generated_at)}</span>' if generated_at else "")
    return (
        '<form onsubmit="submitJob(event, this, null); return false;">'
        '<input type="hidden" name="action" value="ai_sentiment">'
        '<button class="btn">Refresh AI Sentiment</button>'
        f'{note}</form>')


def _ticker_chip_ai(s: dict) -> str:
    chg = s.get("day_chg_pct")
    green = (chg or 0) >= 0
    color = "#0F6E56" if green else "#A32D2D"
    bg = "#E1F5EE" if green else "#FCEBEB"
    rsi = s.get("rsi_14")
    ema = s.get("above_20ema")
    ema_dot = "🟢" if ema else ("🔴" if ema is False else "")
    return (f'<a href="/research/{esc(s["ticker"])}.html" style="text-decoration:none;display:inline-block;'
            f'background:{bg};color:{color};border-radius:8px;padding:8px 12px;margin:0 6px 6px 0;min-width:88px">'
            f'<div style="font-weight:700;font-size:13px">{esc(s["ticker"])}</div>'
            f'<div style="font-size:11px">{fmt_pct(chg)}</div>'
            f'<div style="font-size:10px;color:{color};opacity:.85">RSI {rsi if rsi is not None else "—"} {ema_dot}</div>'
            f'</a>')


def _tier_card(title: str, icon: str, tier: dict) -> str:
    snaps = tier.get("tickers") or []
    status = tier.get("status") or {}
    chips = "".join(_ticker_chip_ai(s) for s in snaps) or empty("no data")
    all_red = badge("ALL RED", "bad", "small") if status.get("all_red") else ""
    header = (f'<div style="font-size:11px;color:#898781;margin-bottom:8px">'
              f'{status.get("green", 0)} green / {status.get("red", 0)} red {all_red}</div>')
    return card(title, header + f'<div>{chips}</div>', icon)


_SENTIMENT_STATUS = lambda score: ("good" if (score or 0) > 70
                                   else "watch" if (score or 0) >= 40 else "bad")
_RISK_STATUS = {"Aggressive buying": "good", "Selective buying": "good",
               "Neutral": "watch", "Reduce position size": "watch", "Defensive": "bad"}
_ROTATION_STATUS = {"Risk-On": "good", "Mixed": "watch", "Risk-Off": "bad", "Unknown": "muted"}


def ai_sentiment_page() -> tuple[str, str]:
    snap = _read_json(OUTPUT_DIR / "ai_sentiment.json")
    if not snap:
        body = card("", empty(
            "No AI sentiment data yet. Click “Refresh AI Sentiment” below to pull "
            "tier snapshots (Leadership / Networking / Power), macro inputs "
            "(10Y yield, DXY, SOXX), sector rotation, and an AI Health Index — "
            "this page fills in with a 0-100 sentiment score once the first "
            "refresh completes.") + f'<div style="margin-top:14px">{_refresh_ai_sentiment_form()}</div>',
            pad="40px")
        extra_js = "function onJobFinished(j) { if (j.kind === 'ai_sentiment') setTimeout(() => location.reload(), 1200); }"
        return body, extra_js

    sentiment = snap.get("sentiment") or {}
    risk = snap.get("risk") or {}
    rotation = snap.get("rotation") or {}
    health = snap.get("ai_health") or {}
    macro = snap.get("macro") or {}
    tiers = snap.get("tiers") or {}
    yld = snap.get("yield") or {}
    dxy = snap.get("dxy") or {}
    soxx = snap.get("soxx") or {}
    vwap = snap.get("nvda_above_vwap")

    # ── Hero: composite score ───────────────────────────────────────────────
    rotation_banner = (
        '<div style="background:#FCEBEB;color:#791F1F;padding:10px 14px;'
        'border-radius:8px;font-size:12px;margin-bottom:12px">'
        '⚠ All three AI tiers are red while the broader market (SPY) is flat — '
        'this looks like an AI-specific rotation, not a broad sell-off.</div>'
        if sentiment.get("ai_specific_rotation") else "")
    hero = (
        rotation_banner
        + '<div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">'
        + '<div><div style="font-size:11px;font-weight:600;color:#898781">AI MARKET SENTIMENT</div>'
        + f'<div style="font-size:40px;font-weight:650">{sentiment.get("score", "—")}'
        + '<span style="font-size:18px;color:#898781">/100</span></div></div>'
        + f'<div style="flex:1;min-width:220px">{badge(sentiment.get("label", "—"), _SENTIMENT_STATUS(sentiment.get("score")))}</div>'
        + '</div>')

    # ── Macro inputs strip ──────────────────────────────────────────────────
    yld_bps = yld.get("change_bps")
    yld_color = "#A32D2D" if (yld_bps or 0) > 0 else "#0F6E56"
    yld_level = yld.get("level_pct")
    yld_level_str = f"{yld_level:.2f}%" if yld_level is not None else "—"
    yld_bps_str = f"{yld_bps:+d}bp" if yld_bps is not None else ""
    dxy_chg = dxy.get("change_pct")
    inputs_html = (
        '<div style="display:flex;gap:24px;flex-wrap:wrap">'
        + f'<div><div style="font-size:11px;color:#898781">10Y Yield</div>'
          f'<div style="font-size:15px;font-weight:600">{yld_level_str} '
          f'<span style="font-size:11px;color:{yld_color}">{yld_bps_str}</span></div></div>'
        + f'<div><div style="font-size:11px;color:#898781">DXY</div>'
          f'<div style="font-size:15px;font-weight:600">{dxy.get("level", "—")} '
          f'<span style="font-size:11px">{fmt_pct(dxy_chg) if dxy_chg is not None else ""}</span></div></div>'
        + f'<div><div style="font-size:11px;color:#898781">SOXX</div>'
          f'<div style="font-size:15px;font-weight:600">{fmt_money(soxx.get("price")) if soxx.get("price") is not None else "—"} '
          + (badge("ABOVE 20DMA", "good", "small") if soxx.get("above_20ma")
             else badge("BELOW 20DMA", "bad", "small") if soxx.get("above_20ma") is False else "")
          + '</div></div>'
        + f'<div><div style="font-size:11px;color:#898781">NVDA vs VWAP</div>'
          f'<div style="font-size:15px;font-weight:600">'
          + (badge("ABOVE", "good", "small") if vwap else
             badge("BELOW", "bad", "small") if vwap is False else badge("N/A", "muted", "small"))
          + '</div></div>'
        + '</div>')

    # ── Tier cards ───────────────────────────────────────────────────────────
    tier_cols = (
        '<div style="display:flex;gap:16px;flex-wrap:wrap">'
        + f'<div style="flex:1;min-width:220px">{_tier_card("Tier 1 · Leadership", "🏆", tiers.get("tier1") or {})}</div>'
        + f'<div style="flex:1;min-width:220px">{_tier_card("Tier 2 · Networking", "🔌", tiers.get("tier2") or {})}</div>'
        + f'<div style="flex:1;min-width:220px">{_tier_card("Tier 3 · Power", "⚡", tiers.get("tier3") or {})}</div>'
        + '</div>')

    # ── Risk Score ───────────────────────────────────────────────────────────
    risk_drivers = "".join(
        f'<div style="font-size:11px;padding:3px 0;color:#52514e">· {esc(d)}</div>'
        for d in risk.get("drivers") or []) or empty("no data")
    risk_html = (
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">'
        + f'<div style="font-size:28px;font-weight:700">{risk.get("score", 0):+d}</div>'
        + badge(risk.get("label", "—"), _RISK_STATUS.get(risk.get("label"), "muted"))
        + '</div>' + risk_drivers)

    # ── Rotation Detection ───────────────────────────────────────────────────
    sector_chips = "".join(
        f'<span class="chip" style="border-left:3px solid {"#0F6E56" if (s.get("chg_pct") or 0) >= 0 else "#A32D2D"}">'
        f'{esc(s.get("label"))} {fmt_pct(s.get("chg_pct"))}</span>'
        for s in snap.get("sectors") or [] if s.get("chg_pct") is not None
    ) or empty("no sector data")
    rotation_html = (
        f'<div style="margin-bottom:10px">{badge(rotation.get("state", "—"), _ROTATION_STATUS.get(rotation.get("state"), "muted"))}</div>'
        f'<div>{sector_chips}</div>')

    # ── AI Health Index ──────────────────────────────────────────────────────
    idx = health.get("index")
    health_html = (
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">'
        + f'<div style="font-size:28px;font-weight:700">{idx if idx is not None else "—"}'
        + '<span style="font-size:14px;color:#898781">/100</span></div>'
        + badge(health.get("label", "—"), "good" if (idx or 0) > 60 else "watch" if (idx or 0) > 40 else "bad")
        + '</div>'
        + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;font-size:11px">'
        + f'<div><div style="color:#898781">Above 20 EMA</div><div style="font-weight:600">{health.get("pct_above_20ema", "—")}%</div></div>'
        + f'<div><div style="color:#898781">Avg RSI</div><div style="font-weight:600">{health.get("avg_rsi", "—")}</div></div>'
        + f'<div><div style="color:#898781">Avg Daily Return</div><div style="font-weight:600">{fmt_pct(health.get("avg_daily_return_pct"))}</div></div>'
        + f'<div><div style="color:#898781">Adv/Decl</div><div style="font-weight:600">{health.get("advancers", 0)}/{health.get("decliners", 0)} ({health.get("adv_decl_ratio", "—")})</div></div>'
        + '</div>')

    # ── Macro Event Filter ───────────────────────────────────────────────────
    macro_events = "".join(
        f'<div style="font-size:11px;padding:5px 0;border-top:0.5px solid #f1efea">'
        f'<b>{esc(ev.get("when", ""))}</b> {esc(ev.get("title", ""))} '
        f'<span style="color:#898781">[{esc(ev.get("impact", ""))}]</span></div>'
        for ev in macro.get("events") or []
    ) or empty("none in the next 48h")
    macro_html = (
        f'<div style="margin-bottom:8px">'
        + (badge("⚠ CAUTION", "bad") if macro.get("caution") else badge("CLEAR", "good"))
        + f' <span style="font-size:11px;color:#898781">{esc(macro.get("note", ""))}</span></div>'
        + macro_events)

    # ── Relative Strength ────────────────────────────────────────────────────
    rs = snap.get("relative_strength") or {}
    benches = ["SPY", "QQQ", "SMH"]
    if rs:
        rs_rows = ""
        for ticker, data in rs.items():
            cells = ""
            for b in benches:
                d = (data or {}).get(b)
                if not d:
                    cells += '<td style="text-align:right">—</td>'
                else:
                    color = ("#0F6E56" if d["trend"] == "rising"
                             else "#A32D2D" if d["trend"] == "falling" else "#898781")
                    arrow = "▲" if d["trend"] == "rising" else "▼" if d["trend"] == "falling" else "·"
                    cells += f'<td style="text-align:right;color:{color}">{arrow} {fmt_pct(d.get("chg_pct"))}</td>'
            rs_rows += f'<tr><td><b>{esc(ticker)}</b></td>{cells}</tr>'
        rs_html = (f'<table><thead><tr><th>Ticker</th>'
                  + "".join(f'<th style="text-align:right">vs {b}</th>' for b in benches)
                  + f'</tr></thead><tbody>{rs_rows}</tbody></table>')
    else:
        rs_html = empty("no data")

    # ── All AI Tickers (full data/watchlists.json "AI" universe) ────────────
    all_ai = snap.get("all_ai") or []
    if all_ai:
        research_idx = _read_json(OUTPUT_DIR / "research_index.json") or {}
        all_ai_rows = []
        for r in all_ai:
            ridx = research_idx.get(r["ticker"]) or {}
            ed = ridx.get("earnings_date")
            all_ai_rows.append({
                **r,
                "earnings_date": ed if ed and ed != "N/A" else None,
                "days_to_earnings": ridx.get("days_to_earnings"),
                "week52_low": ridx.get("week52_low"),
                "week52_high": ridx.get("week52_high"),
            })
        all_ai_html = '<div id="all-ai-root" style="overflow-x:auto"></div>'
        all_ai_js = f"""
        const ALL_AI_ROWS = {json.dumps(all_ai_rows)};
        let aiSortKey = 'ticker', aiSortDir = 1;
        function aiSetSort(key) {{
          aiSortDir = (aiSortKey === key) ? -aiSortDir : 1;
          aiSortKey = key;
          renderAllAI();
        }}
        function renderAllAI() {{
          const root = document.getElementById('all-ai-root');
          if (!root) return;
          const rows = [...ALL_AI_ROWS].sort((a, b) => {{
            const av = a[aiSortKey], bv = b[aiSortKey];
            if (av == null && bv == null) return 0;
            if (av == null) return 1;
            if (bv == null) return -1;
            return (av > bv ? 1 : av < bv ? -1 : 0) * aiSortDir;
          }});
          const arrow = key => aiSortKey === key ? (aiSortDir === 1 ? ' ▲' : ' ▼') : '';
          const th = (key, label) => `<th style="cursor:pointer;white-space:nowrap" onclick="aiSetSort('${{key}}')">${{label}}${{arrow(key)}}</th>`;
          root.innerHTML = `<table><thead><tr>
            ${{th('ticker', 'Ticker')}}${{th('price', 'Price')}}
            ${{th('week52_low', '52W Low')}}${{th('week52_high', '52W High')}}
            ${{th('day_chg_pct', 'Chg%')}}
            ${{th('rsi_14', 'RSI')}}${{th('above_20ema', 'Above 20 EMA')}}${{th('above_50ma', 'Above 50 MA')}}
            ${{th('days_to_earnings', 'DOE')}}
          </tr></thead><tbody>
          ${{rows.map(r => {{
            const chg = r.day_chg_pct;
            const color = (chg ?? 0) >= 0 ? '#0F6E56' : '#A32D2D';
            const flag = v => v === true ? '✓' : v === false ? '✗' : '—';
            return `<tr>
              <td><a href="/research/${{r.ticker}}.html"><b>${{r.ticker}}</b></a></td>
              <td>${{r.price != null ? '$' + r.price.toFixed(2) : '—'}}</td>
              <td>${{r.week52_low != null ? '$' + r.week52_low.toFixed(2) : '—'}}</td>
              <td>${{r.week52_high != null ? '$' + r.week52_high.toFixed(2) : '—'}}</td>
              <td style="color:${{color}}">${{chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '—'}}</td>
              <td>${{r.rsi_14 ?? '—'}}</td>
              <td>${{flag(r.above_20ema)}}</td>
              <td>${{flag(r.above_50ma)}}</td>
              <td style="white-space:nowrap">${{r.days_to_earnings ?? '—'}}</td>
            </tr>`;
          }}).join('')}}
          </tbody></table>`;
        }}
        document.addEventListener('DOMContentLoaded', renderAllAI);
        """
    else:
        all_ai_html = empty("no data")
        all_ai_js = ""

    body = (
        card("", hero, pad="20px 24px")
        + card("Macro Inputs", inputs_html, "📉")
        + tier_cols
        + f"""<div style="display:flex;gap:16px;flex-wrap:wrap">
             <div style="flex:1;min-width:280px">{card("Risk Score", risk_html, "🎯")}
                {card("Rotation Detection", rotation_html, "🔁")}</div>
             <div style="flex:1;min-width:280px">{card("AI Health Index", health_html, "❤️")}
                {card("Macro Event Filter", macro_html, "📅")}</div>
           </div>"""
        + card("Relative Strength (vs SPY / QQQ / SMH)", rs_html, "📐")
        + card(f"All AI Tickers ({len(all_ai)})", all_ai_html, "📋")
        + card("Refresh", _refresh_ai_sentiment_form(snap.get("generated_at", "")), "🔄")
    )
    extra_js = (
        "function onJobFinished(j) { if (j.kind === 'ai_sentiment') setTimeout(() => location.reload(), 1200); }"
        + all_ai_js)
    return body, extra_js


# ─────────────────────────────────────────────────────────────────────────────
# SCANNER
# ─────────────────────────────────────────────────────────────────────────────

SCAN_STEP_LABELS = [
    ("fetch_qqq", "Market Data"), ("scan", "Fundamentals + Technicals"),
    ("grade", "Grading & CANSLIM"), ("writing", "Strategy Scores"),
    ("research", "Research Pages"), ("done", "Dashboard Complete"),
]


def scanner_page() -> tuple[str, str]:
    steps_html = "".join(
        f'<div id="step-{key}" style="flex:1;text-align:center;padding:10px 6px;'
        f'border-radius:8px;background:#f1efea;font-size:11px;font-weight:600;'
        f'color:#898781;transition:.2s">{i+1}. {label}</div>'
        + ('<div style="align-self:center;color:#d9d7ce">→</div>' if i < len(SCAN_STEP_LABELS) - 1 else "")
        for i, (key, label) in enumerate(SCAN_STEP_LABELS))
    pipeline = (f'<div style="display:flex;align-items:stretch;gap:4px;margin-bottom:10px">{steps_html}</div>'
                f'<div id="scan-progress-wrap" style="display:none">'
                f'<div id="scan-progress-label" style="font-size:11px;color:#898781;margin-bottom:4px"></div>'
                f'{progress_bar(None)}</div>')

    watchlists = _read_json(DATA_DIR / "watchlists.json") or {}
    builtin_universes = ("daytrade", "watchlist", "longterm", "dividend", "sp500")
    universe_opts = '<optgroup label="Built-in">' + "".join(
        f'<option value="{u}">{u}</option>' for u in builtin_universes
    ) + '</optgroup>'
    if watchlists:
        universe_opts += '<optgroup label="Watchlists">' + "".join(
            f'<option value="{esc(name)}">{esc(name)} ({len(tickers)})</option>'
            for name, tickers in sorted(watchlists.items())
            if tickers and name not in builtin_universes
        ) + '</optgroup>'
    form = f"""
    <form onsubmit="submitJob(event, this, null); return false;" style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap">
      <input type="hidden" name="action" value="scan">
      <div>
        <select name="universe" multiple size="8" style="min-width:200px">{universe_opts}</select>
        <div style="font-size:10px;color:#898781;margin-top:3px">⌘/Ctrl-click to scan several categories at once (none selected = daytrade)</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <label style="font-size:12px;display:flex;gap:6px;align-items:center">
          <input type="checkbox" name="portfolio" checked> include Portfolio management</label>
        <button class="btn">Run Scan</button>
        <span style="font-size:11px;color:#898781">writes CSVs, research pages, and a fresh dashboard</span>
      </div>
    </form>"""

    csvs = _latest("stock_scan_*.csv", 8)
    csvs = [f for f in csvs if not any(f.stem.endswith(s) for s in
                                       ("_daytrade", "_swing", "_longterm"))]
    csv_html = "".join(
        f'<div style="font-size:12px;padding:5px 0;border-top:0.5px solid #f1efea;'
        f'display:flex;justify-content:space-between">'
        f'<a href="/{f.name}">🗂 {f.name}</a>'
        f'<span style="color:#898781">{datetime.fromtimestamp(f.stat().st_mtime):%b %d %H:%M}</span></div>'
        for f in csvs) or empty("none yet")

    extra_js = """
    function onJobRunning(j) {
      if (j.kind !== 'scan') return;
      document.getElementById('scan-progress-wrap').style.display = 'block';
      document.getElementById('scan-progress-label').textContent = j.stage + (j.pct != null ? ' · ' + j.pct + '%' : '');
      const bar = document.querySelector('#scan-progress-wrap div div');
      if (bar && j.pct != null) bar.style.width = Math.max(2, j.pct) + '%';
      const stepIdx = ['fetch_qqq','scan','grade','writing','research','done']
        .findIndex(s => j.stage.startsWith(s));
      document.querySelectorAll('[id^="step-"]').forEach((el, i) => {
        el.style.background = i <= stepIdx ? '#E6F1FB' : '#f1efea';
        el.style.color = i <= stepIdx ? '#0C447C' : '#898781';
      });
    }
    function onJobFinished(j) {
      if (j.kind !== 'scan') return;
      document.getElementById('scan-progress-wrap').style.display = 'none';
      document.querySelectorAll('[id^="step-"]').forEach(el => { el.style.background = '#f1efea'; el.style.color = '#898781'; });
      if (j.status === 'done') setTimeout(() => location.reload(), 1200);
    }
    """

    return (
        card("Scan Pipeline", pipeline, "📡")
        + card("Run a Scan", form, "▶️")
        + card("Recent Scan Files", csv_html, "🗂")
    ), extra_js


# ─────────────────────────────────────────────────────────────────────────────
# RESEARCH LIBRARY
# ─────────────────────────────────────────────────────────────────────────────

def research_page() -> tuple[str, str]:
    idx = _read_json(OUTPUT_DIR / "research_index.json") or {}
    watchlists = _read_json(DATA_DIR / "watchlists.json") or {}
    rows = sorted(idx.values(), key=lambda r: r.get("ticker") or "")
    rows_json = json.dumps(rows)
    watch_names = sorted(set(list(watchlists.keys()) or []) |
                        {"AI", "Dividend", "Swing", "Breakout", "Earnings"})
    watch_opts = "".join(f'<option value="{esc(w)}">{esc(w)}</option>' for w in watch_names)

    if not rows:
        body = card("", empty(
            "No research pages yet. Use “+ Refresh Research” above "
            "or run a scan to populate the library."), pad="40px")
        return body, ""

    controls = f"""
    <div id="action-tabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px"></div>
    <div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;margin-bottom:14px">
      <input id="rsearch" placeholder="Filter by ticker or sector…" style="min-width:220px"
             oninput="renderResearch()">
      <select id="rview" onchange="renderResearch()">
        <option value="table">Table view</option>
        <option value="grouped">Grouped by sector</option>
      </select>
      <div>
        <div style="display:flex;gap:6px;align-items:center">
          <select id="rwatch" multiple size="6" style="min-width:180px" onchange="renderResearch()">{watch_opts}</select>
          <button type="button" class="btn secondary" style="font-size:10px;padding:3px 8px"
                  onclick="document.getElementById('rwatch').selectedIndex=-1; renderResearch()">Clear</button>
        </div>
        <div style="font-size:10px;color:#898781;margin-top:3px">⌘/Ctrl-click to view several categories together (none = all tickers)</div>
      </div>
      <span style="font-size:11px;color:#898781;margin-left:auto">
        <span id="rcount">{len(rows)}</span> tickers</span>
    </div>
    <div id="research-root" style="overflow-x:auto"></div>
    <dialog id="modal-detail" style="max-width:640px;width:90vw">
      <div class="modal-body">
        <h3 id="detail-title">Detailed Metrics</h3>
        <div id="detail-body" style="max-height:60vh;overflow-y:auto"></div>
        <div class="modal-actions">
          <button type="button" class="btn secondary" onclick="closeModal('modal-detail')">Close</button>
        </div>
      </div>
    </dialog>
    <dialog id="modal-earnings" style="max-width:640px;width:90vw">
      <div class="modal-body">
        <h3 id="earnings-title">Earnings Analysis</h3>
        <div id="earnings-body" style="max-height:65vh;overflow-y:auto"></div>
        <div class="modal-actions">
          <button type="button" class="btn secondary" onclick="closeModal('modal-earnings')">Close</button>
        </div>
      </div>
    </dialog>
    """

    js = f"""
    const RESEARCH_ROWS = {rows_json};
    const WATCHLISTS = {json.dumps(watchlists)};
    let sortKey = 'ticker', sortDir = 1;
    let actionFilter = '';
    function starredIn(name, ticker) {{ return (WATCHLISTS[name] || []).includes(ticker); }}
    function actionColor(a) {{ return a === 'READY' ? '#0F6E56' : a === 'WATCH' ? '#8a6d1a' : a === 'AVOID' ? '#A32D2D' : '#898781'; }}
    function setActionFilter(a) {{ actionFilter = a; renderResearch(); }}
    function renderActionTabs() {{
      const tabs = [['', 'All'], ['READY', 'Ready'], ['WATCH', 'Watch'], ['AVOID', 'Avoid']];
      document.getElementById('action-tabs').innerHTML = tabs.map(([val, label]) => {{
        const count = val ? RESEARCH_ROWS.filter(r => r.conv_action === val).length : RESEARCH_ROWS.length;
        const active = actionFilter === val;
        const color = val ? actionColor(val) : '#52514e';
        return `<button onclick="setActionFilter('${{val}}')"
          style="font-size:11px;font-weight:600;padding:4px 12px;border-radius:14px;cursor:pointer;
                 border:1px solid ${{color}};background:${{active ? color : 'transparent'}};
                 color:${{active ? '#fff' : color}}">${{label}} (${{count}})</button>`;
      }}).join('');
    }}
    function instOwnChgHtml(chg) {{
      if (chg == null) return '';
      const color = chg > 0 ? '#0F6E56' : chg < 0 ? '#A32D2D' : '#898781';
      const arrow = chg > 0 ? '▲' : chg < 0 ? '▼' : '·';
      return ` <span style="color:${{color}};font-size:10px">${{arrow}}${{Math.abs(chg).toFixed(1)}}</span>`;
    }}
    function sortRows(rows) {{
      return [...rows].sort((a, b) => {{
        const av = a[sortKey] ?? '', bv = b[sortKey] ?? '';
        return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
      }});
    }}
    function renderResearch() {{
      renderActionTabs();
      const q = document.getElementById('rsearch').value.trim().toUpperCase();
      const view = document.getElementById('rview').value;
      const watchSelected = Array.from(document.getElementById('rwatch').selectedOptions).map(o => o.value);
      const watchTickers = watchSelected.length
        ? new Set(watchSelected.flatMap(w => WATCHLISTS[w] || [])) : null;
      let rows = RESEARCH_ROWS.filter(r =>
        (!q || r.ticker.includes(q) || (r.sector || '').toUpperCase().includes(q)) &&
        (!watchTickers || watchTickers.has(r.ticker)) &&
        (!actionFilter || r.conv_action === actionFilter));
      document.getElementById('rcount').textContent = rows.length;
      const root = document.getElementById('research-root');
      if (view === 'grouped') {{
        const bySec = {{}};
        rows.forEach(r => {{ const s = r.sector || 'Unknown'; (bySec[s] = bySec[s] || []).push(r); }});
        root.innerHTML = Object.keys(bySec).sort().map(sec => `
          <div style="margin-bottom:14px">
            <div style="font-size:12px;font-weight:700;color:#898781;margin-bottom:6px">${{sec}} (${{bySec[sec].length}})</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px">
              ${{bySec[sec].map(r => `<a href="/research/${{r.ticker}}.html" class="chip" style="border-left:3px solid ${{actionColor(r.conv_action)}}">${{r.ticker}} · ${{r.conv_overall ?? '—'}}</a>`).join('')}}
            </div></div>`).join('');
        return;
      }}
      rows = sortRows(rows);
      const arrow = key => sortKey === key ? (sortDir === 1 ? ' ▲' : ' ▼') : '';
      const th = (key, label) =>
        `<th style="cursor:pointer;white-space:nowrap" onclick="setSort('${{key}}')">${{label}}${{arrow(key)}}</th>`;
      root.innerHTML = `<table style="width:auto;min-width:100%;white-space:nowrap"><thead><tr>
        <th></th>
        ${{th('ticker', 'Ticker')}}
        ${{th('price', 'Price')}}
        ${{th('week52_low', '52W Low')}}
        ${{th('week52_high', '52W High')}}
        ${{th('category', 'Category')}}
        ${{th('conv_action', 'Action')}}
        ${{th('earnings_date', 'Earnings Date')}}
        ${{th('days_to_earnings', 'DOE')}}
        ${{th('forward_pe', 'Fwd P/E')}}
        ${{th('peg_ratio', 'PEG')}}
        ${{th('inst_own_pct', 'Inst Own%')}}
        ${{th('rs_rank', 'RS')}}
        ${{th('canslim_pass', 'CANSLIM')}}
        ${{th('entry_zone', 'Entry Zone')}}
        ${{th('s1', 'S1')}}
        ${{th('r1', 'R1')}}
        ${{th('key_level_score', 'Key Level')}}
        ${{th('touches', 'Touches')}}
        ${{th('volume_confirmation', 'Vol Conf')}}
        ${{th('dist_to_support_pct', 'Dist S1')}}
        ${{th('dist_to_resistance_pct', 'Dist R1')}}
        ${{th('rr_to_resistance', 'R:R')}}
        ${{th('breakout_probability', 'Breakout%')}}
        ${{th('bounce_probability', 'Bounce%')}}
        ${{th('updated_at', 'Updated')}}
        <th></th></tr></thead><tbody>
        ${{rows.map(r => `<tr>
          <td><button onclick="toggleWatchlist(document.getElementById('rwatch').value, '${{r.ticker}}', this)"
              style="background:none;border:none;font-size:14px;color:#c9a227">${{starredIn(document.getElementById('rwatch').value, r.ticker) ? '★' : '☆'}}</button></td>
          <td><b>${{r.ticker}}</b></td>
          <td style="font-size:11px">${{r.price != null ? '$' + r.price.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.week52_low != null ? '$' + r.week52_low.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.week52_high != null ? '$' + r.week52_high.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.category || '—'}}</td>
          <td><span style="color:${{actionColor(r.conv_action)}};font-weight:600;font-size:11px">${{r.conv_action || '—'}}</span></td>
          <td style="font-size:11px;color:#898781">${{r.earnings_date && r.earnings_date !== 'N/A' ? r.earnings_date : '—'}}</td>
          <td style="font-size:11px">${{r.days_to_earnings ?? '—'}}</td>
          <td style="font-size:11px">${{r.forward_pe ?? '—'}}</td>
          <td style="font-size:11px">${{r.peg_ratio ?? '—'}}</td>
          <td style="font-size:11px">${{r.inst_own_pct != null ? r.inst_own_pct + '%' : '—'}}${{instOwnChgHtml(r.inst_own_chg)}}</td>
          <td style="font-size:11px">${{r.rs_rank ?? '—'}}</td>
          <td style="font-size:11px">${{r.canslim_pass === true ? '✓' : r.canslim_pass === false ? '✗' : '—'}}</td>
          <td style="font-size:11px">${{r.entry_zone != null ? '$' + r.entry_zone.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.s1 != null ? '$' + r.s1.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.r1 != null ? '$' + r.r1.toFixed(2) : '—'}}</td>
          <td style="font-size:11px">${{r.key_level_score ?? '—'}}</td>
          <td style="font-size:11px">${{r.touches ?? '—'}}</td>
          <td style="font-size:11px">${{r.volume_confirmation === true ? '✓' : r.volume_confirmation === false ? '✗' : '—'}}</td>
          <td style="font-size:11px">${{r.dist_to_support_pct != null ? r.dist_to_support_pct + '%' : '—'}}</td>
          <td style="font-size:11px">${{r.dist_to_resistance_pct != null ? r.dist_to_resistance_pct + '%' : '—'}}</td>
          <td style="font-size:11px">${{r.rr_to_resistance ?? '—'}}</td>
          <td style="font-size:11px">${{r.breakout_probability != null ? r.breakout_probability + '%' : '—'}}</td>
          <td style="font-size:11px">${{r.bounce_probability != null ? r.bounce_probability + '%' : '—'}}</td>
          <td style="font-size:11px;color:#898781">${{(r.updated_at || '').slice(5,16)}}</td>
          <td style="display:flex;gap:4px">
            <a href="/research/${{r.ticker}}.html" class="btn secondary" style="text-decoration:none;padding:3px 10px;font-size:11px">Open</a>
            <button type="button" onclick="openDetail('${{r.ticker}}')" class="btn secondary" style="padding:3px 10px;font-size:11px">Detailed Metrics</button>
            <button type="button" onclick="runEarningsAnalysis('${{r.ticker}}')" class="btn secondary" style="padding:3px 10px;font-size:11px">Earnings Analysis</button>
          </td>
        </tr>`).join('')}}
      </tbody></table>`;
    }}
    function setSort(key) {{
      sortDir = (sortKey === key) ? -sortDir : 1;
      sortKey = key;
      renderResearch();
    }}
    // "Detailed Metrics": every column the scan/research pipeline computed
    // for this ticker (row.raw, same fields stock_scan_*.csv has) merged
    // with the curated fields already shown in the table — one place to see
    // everything instead of hunting across a 25-column row.
    function fmtDetailVal(v) {{
      if (v === null || v === undefined || v === '') return '—';
      if (typeof v === 'boolean') return v ? '✓' : '✗';
      return String(v);
    }}
    function openDetail(ticker) {{
      const row = RESEARCH_ROWS.find(r => r.ticker === ticker);
      if (!row) return;
      document.getElementById('detail-title').textContent = ticker + ' — Detailed Metrics';
      const {{ raw, ...curated }} = row;
      const all = {{ ...curated, ...(raw || {{}}) }};
      const keys = Object.keys(all);
      document.getElementById('detail-body').innerHTML = keys.length
        ? `<table style="width:100%"><tbody>${{keys.map(k => `
            <tr><td style="color:#898781;white-space:nowrap;padding-right:14px;vertical-align:top">${{k}}</td>
                <td style="font-weight:600;word-break:break-word">${{fmtDetailVal(all[k])}}</td></tr>`).join('')}}</tbody></table>`
        : '<span style="font-size:12px;color:#898781">No detailed metrics captured yet — re-run a scan or research refresh for this ticker.</span>';
      openModal('modal-detail');
    }}
    document.addEventListener('DOMContentLoaded', renderResearch);

    // "Earnings Analysis": deterministic weighted-score engine (see
    // core/earnings_sentiment.py) run on demand via the job-tray pattern —
    // POST starts it, the job writes /earnings/<TICKER>.json, and once
    // /api/jobs reports it done this fetches that file and renders it.
    let _pendingEarningsTicker = null;
    async function runEarningsAnalysis(ticker) {{
      toast('Analyzing ' + ticker + ' — earnings history, options chain, '
           + 'market context (~15-20s)…', 'ok');
      try {{
        const res = await fetch('/run', {{
          method: 'POST',
          body: new URLSearchParams({{ action: 'earnings_analysis', ticker }}),
        }});
        const data = await res.json();
        if (!data.ok) {{ toast(data.message || 'Failed to start', 'err'); return; }}
      }} catch (e) {{ toast('Request failed: ' + e, 'err'); return; }}
      _pendingEarningsTicker = ticker;
      pollJobs();
    }}
    function biasColor(bias) {{
      if (bias === 'Strong Buy' || bias === 'Buy') return '#0F6E56';
      if (bias === 'Strong Sell' || bias === 'Sell') return '#A32D2D';
      return '#8a6d1a';
    }}
    function riskColor(risk) {{
      return risk === 'Low' ? '#0F6E56' : risk === 'High' ? '#A32D2D'
           : risk === 'Medium' ? '#8a6d1a' : '#898781';
    }}
    function reasonList(arr) {{
      return (arr && arr.length)
        ? `<ul style="margin:4px 0 0;padding-left:16px">${{arr.map(r =>
            `<li style="font-size:11px;margin-bottom:2px">${{r}}</li>`).join('')}}</ul>`
        : '<div style="font-size:11px;color:#898781">none flagged</div>';
    }}
    function renderEarningsModal(ticker, data) {{
      document.getElementById('earnings-title').textContent = ticker + ' — Earnings Analysis';
      const bColor = biasColor(data.trading_bias);
      const rColor = riskColor(data.earnings_risk);
      const move = data.expected_move_pct;
      const moveSrc = data.expected_move_source === 'options_straddle' ? 'options-implied'
                    : data.expected_move_source === 'historical_avg' ? 'historical avg (no options data)' : '';
      const factorRows = Object.entries(data.factor_scores || {{}}).map(([k, v]) => {{
        const halfPct = Math.min(50, Math.abs(v) / 25 * 50);
        const color = v > 0 ? '#0F6E56' : v < 0 ? '#A32D2D' : '#d9d7ce';
        const barLeft = v >= 0 ? 50 : 50 - halfPct;
        return `<div style="display:flex;align-items:center;gap:8px;margin:3px 0">
          <span style="min-width:120px;font-size:11px;text-transform:capitalize">${{k.replace(/_/g,' ')}}</span>
          <div style="flex:1;background:#f1efea;border-radius:3px;height:8px;position:relative">
            <div style="position:absolute;top:0;left:${{barLeft}}%;width:${{halfPct}}%;height:8px;background:${{color}};border-radius:2px"></div>
            <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#d9d7ce"></div>
          </div>
          <span style="min-width:28px;text-align:right;font-size:11px;font-weight:600">${{v > 0 ? '+' : ''}}${{v}}</span>
        </div>`;
      }}).join('');
      document.getElementById('earnings-body').innerHTML = `
        <div style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:14px">
          <div><div style="font-size:11px;color:#898781">Trading Bias</div>
            <div style="font-size:16px;font-weight:700;color:${{bColor}}">${{data.trading_bias}}</div></div>
          <div><div style="font-size:11px;color:#898781">Confidence</div>
            <div style="font-size:16px;font-weight:700">${{data.confidence}}/10</div></div>
          <div><div style="font-size:11px;color:#898781">Expected Move</div>
            <div style="font-size:16px;font-weight:700">${{move != null ? '±' + move.toFixed(1) + '%' : '—'}}</div>
            <div style="font-size:10px;color:#898781">${{moveSrc}}</div></div>
          <div><div style="font-size:11px;color:#898781">Earnings Risk</div>
            <div style="font-size:16px;font-weight:700;color:${{rColor}}">${{data.earnings_risk}}</div></div>
          <div><div style="font-size:11px;color:#898781">Next Earnings</div>
            <div style="font-size:14px;font-weight:600">${{data.next_earnings_date || '—'}}${{data.days_to_earnings != null ? ' (' + data.days_to_earnings + 'd)' : ''}}</div></div>
        </div>
        <div style="margin-bottom:14px">
          <div style="font-size:11px;color:#898781;margin-bottom:4px">Bullish ${{data.bullish_probability}}% / Bearish ${{data.bearish_probability}}% · total score ${{data.total_score}} · regime ${{data.market_regime}}</div>
          <div style="display:flex;height:14px;border-radius:7px;overflow:hidden">
            <div style="width:${{data.bullish_probability}}%;background:#0F6E56"></div>
            <div style="width:${{data.bearish_probability}}%;background:#A32D2D"></div>
          </div>
        </div>
        <div style="margin-bottom:14px">
          <div style="font-size:11px;font-weight:600;color:#898781;margin-bottom:4px">FACTOR SCORES (of ±100 total)</div>
          ${{factorRows}}
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px">
          <div style="flex:1;min-width:200px">
            <div style="font-size:11px;font-weight:600;color:#0F6E56">BULLISH REASONS</div>
            ${{reasonList(data.key_bullish_reasons)}}
          </div>
          <div style="flex:1;min-width:200px">
            <div style="font-size:11px;font-weight:600;color:#A32D2D">BEARISH REASONS</div>
            ${{reasonList(data.key_bearish_reasons)}}
          </div>
        </div>
        ${{(data.risk_factors && data.risk_factors.length) ? `
        <div style="margin-bottom:10px">
          <div style="font-size:11px;font-weight:600;color:#633806">RISK FACTORS</div>
          ${{reasonList(data.risk_factors)}}
        </div>` : ''}}
        <details style="margin-top:6px">
          <summary style="font-size:10px;color:#898781;cursor:pointer">What this doesn't cover</summary>
          <ul style="margin:4px 0 0;padding-left:16px">${{(data.data_gaps || []).map(g =>
            `<li style="font-size:10px;color:#898781;margin-bottom:2px">${{g}}</li>`).join('')}}</ul>
        </details>
        <div style="font-size:10px;color:#898781;margin-top:8px">Generated ${{data.generated_at}} · deterministic scoring, not investment advice.</div>
      `;
      openModal('modal-earnings');
    }}

    // A research/news job finishing means RESEARCH_ROWS is stale (updated
    // scores, new tickers, refreshed timestamps) — reload once to pick it up
    function onJobFinished(j) {{
      if (j.kind === 'research' || j.kind === 'news') setTimeout(() => location.reload(), 1200);
      if (j.kind === 'earnings' && _pendingEarningsTicker) {{
        const ticker = _pendingEarningsTicker;
        _pendingEarningsTicker = null;
        if (j.status === 'done') {{
          fetch('/earnings/' + ticker + '.json').then(r => r.json())
            .then(data => renderEarningsModal(ticker, data))
            .catch(e => toast('Could not load analysis: ' + e, 'err'));
        }}
      }}
    }}
    """

    return card("Research Library", controls, "🔎", pad="16px 18px"), js


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO
# ─────────────────────────────────────────────────────────────────────────────

def _latest_scan_rows() -> list[dict]:
    files = _latest("stock_scan_*.csv", 1)
    files = [f for f in files if not any(f.stem.endswith(s) for s in
                                         ("_daytrade", "_swing", "_longterm"))]
    if not files:
        return []
    import pandas as pd
    df = pd.read_csv(files[0])
    return [{k: (None if pd.isna(v) else v) for k, v in r.items()}
            for _, r in df.iterrows()]


def portfolio_page() -> tuple[str, str]:
    from stockanalysis.reporting.portfolio import (
        load_positions, build_portfolio_view, portfolio_totals,
        allocation_summary)

    positions = load_positions()
    if not positions:
        body = card("", empty(
            "No portfolio file found. Copy data/portfolio_template.csv to "
            "data/portfolio.csv and list your positions (Ticker, Shares, "
            "Avg_Cost, Entry_Date, Strategy, Stop, Target, Notes) — or add "
            "your first one below."), pad="40px")
        body += card("", '<button type="button" class="btn" '
                     'onclick="openPositionModal(null)">+ Add Position</button>', pad="0 18px 18px")
        return body + _position_modal(), _position_js

    rows = _latest_scan_rows()
    view = build_portfolio_view(positions, rows)
    totals = portfolio_totals(view)
    alloc = allocation_summary(view)

    gain = totals.get("total_gain")
    gain_status = "good" if (gain or 0) >= 0 else "bad"
    summary = f"""
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px">
      <div><div style="font-size:11px;color:#898781">Portfolio Value</div>
        <div style="font-size:20px;font-weight:650">{fmt_money(totals.get('portfolio_value'), 0)}</div></div>
      <div><div style="font-size:11px;color:#898781">Total Gain</div>
        <div style="font-size:20px;font-weight:650">{badge(fmt_money(gain, 0) if gain is not None else '—', gain_status)}
        <span style="font-size:11px;color:#898781"> {fmt_pct(totals.get('total_gain_pct'))}</span></div></div>
      <div><div style="font-size:11px;color:#898781">Cash</div>
        <div style="font-size:20px;font-weight:650">{fmt_money(totals.get('cash'), 0)}</div></div>
      <div><div style="font-size:11px;color:#898781">At Risk</div>
        <div style="font-size:20px;font-weight:650">{fmt_money(totals.get('total_risk'), 0)}</div></div>
      <div><div style="font-size:11px;color:#898781">Positions / Watching</div>
        <div style="font-size:20px;font-weight:650">{totals.get('positions')} / {totals.get('watching')}</div></div>
    </div>"""

    def _alloc_bars(pcts):
        if not pcts:
            return empty("—")
        peak = max(p for _, p in pcts) or 1
        return "".join(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
            f'<span style="min-width:100px;font-size:11px">{esc(k)}</span>'
            f'<div style="flex:1;background:#f1efea;border-radius:3px;height:9px">'
            f'<div style="width:{max(2, round(p / peak * 100))}%;background:#185FA5;height:9px;border-radius:3px"></div></div>'
            f'<span style="min-width:40px;text-align:right;font-size:11px;font-weight:600">{p:.1f}%</span></div>'
            for k, p in pcts)

    warn_html = "".join(f'<div style="font-size:11px;color:#791F1F;margin-top:6px">⚠ {esc(w)}</div>'
                        for w in alloc.get("warnings") or [])
    alloc_html = (f'<div style="display:flex;gap:24px;flex-wrap:wrap">'
                 f'<div style="flex:1;min-width:200px"><div style="font-size:11px;font-weight:600;color:#898781;margin-bottom:4px">MARKET CAP</div>{_alloc_bars(alloc.get("caps") or [])}</div>'
                 f'<div style="flex:1;min-width:200px"><div style="font-size:11px;font-weight:600;color:#898781;margin-bottom:4px">SECTOR</div>{_alloc_bars(alloc.get("sectors") or [])}</div>'
                 f'</div>{warn_html}')

    holdings_rows = []
    for p in view:
        g_pct = p.get("Gain_Pct")
        g_color = "#0F6E56" if (g_pct or 0) >= 0 else "#A32D2D"
        action = p.get("Next_Action", "")
        act_urgent = action.split(" ")[0] in ("EXIT", "TRIM", "REDUCE", "REVIEW")
        alerts = "".join(f'<div style="font-size:10px;color:{"#791F1F" if "⛔" in a else "#633806"}">{esc(a)}</div>'
                         for a in p.get("Alerts") or [])
        edit_payload = esc(json.dumps({
            "Ticker":     p["Ticker"],
            "Shares":     p.get("Shares") or "",
            "Avg_Cost":   p.get("Avg_Cost") if p.get("Avg_Cost") is not None else "",
            "Entry_Date": p["Entry_Date"].isoformat() if p.get("Entry_Date") else "",
            "Strategy":   p.get("Strategy") or "watch",
            "Stop":       p.get("Stop") if p.get("Stop") is not None else "",
            "Target":     p.get("Target") if p.get("Target") is not None else "",
            "Notes":      p.get("Notes") or "",
        }))
        row_actions = (
            f'<div style="display:flex;gap:4px">'
            f'<button type="button" class="btn secondary" style="font-size:10px;padding:2px 8px" '
            f'''data-position='{edit_payload}' onclick="openPositionModal(JSON.parse(this.dataset.position))">Edit</button>'''
            f'<button type="button" class="btn secondary" style="font-size:10px;padding:2px 8px;color:#791F1F" '
            f'onclick="deletePosition(\'{esc(p["Ticker"])}\')">Delete</button>'
            f'</div>')
        holdings_rows.append(f"""
        <tr style="{'opacity:.6' if p['Is_Watch'] else ''}">
          <td><a href="/research/{p['Ticker']}.html"><b>{p['Ticker']}</b></a></td>
          <td>{esc(p['Strategy'])}</td>
          <td>{esc(p.get('Cap') or '—')}</td>
          <td style="text-align:right">{p['Shares']:g}</td>
          <td style="text-align:right">{fmt_money(p.get('Price'))}</td>
          <td style="text-align:right;color:{g_color}">{fmt_pct(g_pct) if g_pct is not None else '—'}</td>
          <td style="text-align:right">{f"{p['Alloc_Pct']:.1f}%" if p.get('Alloc_Pct') is not None else '—'}</td>
          <td style="text-align:right">{p['Days_Held'] if p.get('Days_Held') is not None else '—'}</td>
          <td style="text-align:right">{fmt_money(p.get('Stop'))}</td>
          <td style="text-align:right">{fmt_money(p.get('Target'))}</td>
          <td style="color:{'#791F1F' if act_urgent else '#0b0b0b'};font-weight:600;font-size:11px">{esc(action)}</td>
          <td>{alerts or '<span style="font-size:10px;color:#0F6E56">✓ clear</span>'}</td>
          <td>{row_actions}</td>
        </tr>""")

    holdings = f"""<table><thead><tr>
      <th>Ticker</th><th>Strategy</th><th>Cap</th><th style="text-align:right">Shares</th>
      <th style="text-align:right">Price</th><th style="text-align:right">Gain %</th>
      <th style="text-align:right">Alloc %</th><th style="text-align:right">Days Held</th>
      <th style="text-align:right">Stop</th><th style="text-align:right">Target</th>
      <th>Next Action</th><th>Alerts</th><th></th></tr></thead>
      <tbody>{''.join(holdings_rows)}</tbody></table>"""

    body = (
        card("Portfolio Summary", summary, "💼")
        + card("Allocation", alloc_html, "📊")
        + card("Holdings & Watchlist", holdings, "📋",
              right='<button type="button" class="btn" style="font-size:11px;padding:4px 10px" '
                    'onclick="openPositionModal(null)">+ Add Position</button>')
        + _position_modal()
    )
    extra_js = ("function onJobFinished(j) { setTimeout(() => location.reload(), 1200); }"
               + _position_js)
    return body, extra_js


def _position_modal() -> str:
    return """
    <dialog id="modal-position">
      <form class="modal-body" onsubmit="submitPosition(event, this); return false;">
        <h3 id="position-modal-title">Add position</h3>
        <input type="hidden" name="Original_Ticker" value="">
        <div style="display:flex;flex-direction:column;gap:10px">
          <input name="Ticker" placeholder="Ticker (e.g. NVDA)" required style="text-transform:uppercase">
          <div style="display:flex;gap:8px">
            <input name="Shares" type="number" step="any" placeholder="Shares (blank = watchlist)" style="flex:1">
            <input name="Avg_Cost" type="number" step="any" placeholder="Avg cost" style="flex:1">
          </div>
          <div style="display:flex;gap:8px">
            <input name="Entry_Date" type="date" style="flex:1">
            <select name="Strategy" style="flex:1">
              <option value="watch">watch</option>
              <option value="day">day</option>
              <option value="swing">swing</option>
              <option value="longterm">longterm</option>
            </select>
          </div>
          <div style="display:flex;gap:8px">
            <input name="Stop" type="number" step="any" placeholder="Stop" style="flex:1">
            <input name="Target" type="number" step="any" placeholder="Target" style="flex:1">
          </div>
          <input name="Notes" placeholder="Notes">
        </div>
        <div class="modal-actions">
          <button type="button" class="btn secondary" onclick="closeModal('modal-position')">Cancel</button>
          <button class="btn">Save</button>
        </div>
      </form>
    </dialog>"""


_position_js = r"""
function openPositionModal(pos) {
  const form = document.getElementById('modal-position').querySelector('form');
  form.reset();
  form.Original_Ticker.value = pos ? pos.Ticker : '';
  document.getElementById('position-modal-title').textContent = pos ? 'Edit ' + pos.Ticker : 'Add position';
  if (pos) {
    form.Ticker.value = pos.Ticker || '';
    form.Shares.value = pos.Shares || '';
    form.Avg_Cost.value = pos.Avg_Cost ?? '';
    form.Entry_Date.value = pos.Entry_Date || '';
    form.Strategy.value = pos.Strategy || 'watch';
    form.Stop.value = pos.Stop ?? '';
    form.Target.value = pos.Target ?? '';
    form.Notes.value = pos.Notes || '';
  }
  openModal('modal-position');
}
async function submitPosition(event, form) {
  event.preventDefault();
  const fd = new FormData(form);
  try {
    const res = await fetch('/api/portfolio/save', { method: 'POST', body: new URLSearchParams(fd) });
    const data = await res.json();
    if (data.ok) {
      toast(data.message || 'Saved', 'ok');
      closeModal('modal-position');
      setTimeout(() => location.reload(), 600);
    } else { toast(data.message || 'Save failed', 'err'); }
  } catch (e) { toast('Request failed: ' + e, 'err'); }
}
async function deletePosition(ticker) {
  if (!confirm('Remove ' + ticker + ' from the portfolio?')) return;
  try {
    const res = await fetch('/api/portfolio/delete', { method: 'POST', body: new URLSearchParams({ ticker }) });
    const data = await res.json();
    if (data.ok) {
      toast(data.message || 'Removed', 'ok');
      setTimeout(() => location.reload(), 600);
    } else { toast(data.message || 'Delete failed', 'err'); }
  } catch (e) { toast('Request failed: ' + e, 'err'); }
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

def automation_page() -> tuple[str, str]:
    from stockanalysis.reporting.portfolio import PORTFOLIO_VALUE, SMALLCAP_MAX_PCT

    alive = jobstore.scheduler_alive()
    if alive:
        sched_jobs = jobstore.scheduler_jobs()

        def _run_now_form(job_name: str) -> str:
            return (
                f'<form style="margin:0" onsubmit="submitJob(event, this, null); return false;">'
                f'<input type="hidden" name="action" value="run_cron">'
                f'<input type="hidden" name="job_name" value="{esc(job_name)}">'
                f'<button class="btn" style="font-size:10px;padding:2px 8px">Run now</button></form>'
            )

        sched_rows = "".join(
            f'<tr><td>{esc(j["job"])}</td><td>{esc(j["next_run"] or "—")}</td>'
            f'<td>{_run_now_form(j["job"])}</td></tr>'
            for j in sched_jobs
        ) or f'<tr><td colspan="3">{empty("No jobs registered yet.")}</td></tr>'
        scheduler_html = (
            badge("● RUNNING", "good", "small")
            + '<div style="font-size:11px;color:#898781;margin-top:8px">'
              'Cron-style loop firing the scans/emails/cleanup below on schedule, '
              'in the background of this web app process. "Run now" fires that job\'s '
              'function immediately without touching its normal schedule — use it to '
              'verify a job actually works instead of waiting for its trigger time.</div>'
              f'<table style="margin-top:10px"><thead><tr><th>Job</th>'
              f'<th>Next run (ET)</th><th></th></tr></thead><tbody>{sched_rows}</tbody></table>'
              '<form style="margin-top:12px" onsubmit="submitJob(event, this, null); return false;">'
              '<input type="hidden" name="action" value="test_scheduler">'
              '<button class="btn">Run scheduler self-test (fires a job in ~1 min)</button></form>'
        )
    else:
        scheduler_html = (
            badge("○ NOT RUNNING", "bad", "small")
            + '<div style="font-size:12px;color:#898781;margin-top:8px">'
              'Start the app without <code>--no-scheduler</code> to enable automatic scans.</div>'
        )

    hist = jobstore.history()
    hist_rows = "".join(
        f'<tr><td>{badge(j["status"].upper(), {"done":"good","failed":"bad","running":"watch"}.get(j["status"],"muted"), "small")}</td>'
        f'<td>{esc(j["label"])}</td><td>{esc(j["started"] or "")}</td>'
        f'<td>{esc(j["finished"] or "")}</td><td style="font-size:11px;color:#52514e">{esc(j["detail"])}</td></tr>'
        for j in hist) or '<tr><td colspan="5">' + empty("No jobs run yet this session.") + '</td></tr>'
    history_table = f"""<table><thead><tr>
      <th>Status</th><th>Job</th><th>Started</th><th>Finished</th><th>Detail</th></tr></thead>
      <tbody>{hist_rows}</tbody></table>"""

    settings_html = f"""
    <table><tbody>
      <tr><td style="color:#898781">Portfolio Value</td><td>{fmt_money(PORTFOLIO_VALUE, 0)}</td></tr>
      <tr><td style="color:#898781">Small-cap warning threshold</td><td>{SMALLCAP_MAX_PCT:g}%</td></tr>
      <tr><td style="color:#898781">Account size (risk sizing)</td><td>{fmt_money(float(os.environ.get('ACCOUNT_SIZE', 100000)), 0)}</td></tr>
      <tr><td style="color:#898781">Risk per trade</td><td>{os.environ.get('RISK_PER_TRADE_PCT', '1.0')}%</td></tr>
      <tr><td style="color:#898781">Cleanup retention</td><td>{os.environ.get('CLEANUP_DAYS', '7')} days</td></tr>
    </tbody></table>
    <div style="font-size:11px;color:#898781;margin-top:8px">
      Edit these via environment variables or a .env file in the project root, then restart.</div>"""

    day_session = _read_json(OUTPUT_DIR / "day_session.json")
    if day_session:
        ds_html = (f'<div style="font-size:12px">Initialized {esc(day_session.get("updated_at",""))} — '
                   f'{len(day_session.get("hot") or [])} movers + '
                   f'{len(day_session.get("base") or [])} base = '
                   f'{len(day_session.get("merged") or [])} tickers</div>')
    else:
        ds_html = empty("Not initialized yet — runs automatically at market open under the scheduler.")

    cleanup_form = """
    <form onsubmit="submitJob(event, this, null); return false;" style="display:flex;gap:10px;align-items:center">
      <input type="hidden" name="action" value="cleanup">
      <input name="days" type="number" value="7" min="0" step="1" style="width:80px">
      <button class="btn warn">Clean up outputs older than N days</button>
    </form>"""

    last_test = next((j for j in hist if j["kind"] == "test"), None)
    if last_test:
        ok = last_test["status"] == "done" and last_test["detail"].startswith("PASSED")
        test_status = (
            badge(("✓ " if ok else "✗ ") + last_test["detail"][:80],
                  "good" if ok else "bad", "small")
            + f'<div style="font-size:11px;color:#898781;margin-top:6px">'
              f'Last run {esc(last_test["finished"] or last_test["started"] or "")} · '
              f'<a href="/last_test_run.txt" target="_blank">full output</a></div>'
        )
    else:
        test_status = empty("Not run yet this session.")
    tests_form = f"""
    <div style="margin-bottom:10px">{test_status}</div>
    <form onsubmit="submitJob(event, this, null); return false;">
      <input type="hidden" name="action" value="test">
      <button class="btn">Run unit tests (tests/)</button>
    </form>"""

    body = (
        card("Scheduler", scheduler_html, "⏱")
        + card("Unit Tests", tests_form, "🧪")
        + card("Scan History", history_table, "🗒")
        + card("Settings (read-only)", settings_html, "⚙️")
        + card("Day Session Universe", ds_html, "🔔")
        + card("Cleanup", cleanup_form, "🧹")
    )
    # Any job finishing while this page is open means the history table /
    # day-session panel are stale — reload once rather than leave them frozen
    extra_js = "function onJobFinished(j) { setTimeout(() => location.reload(), 1200); }"
    return body, extra_js
