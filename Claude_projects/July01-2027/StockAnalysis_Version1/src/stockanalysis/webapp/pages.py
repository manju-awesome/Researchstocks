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

    universe_opts = "".join(
        f'<option value="{u}">{u}</option>'
        for u in ("daytrade", "watchlist", "longterm", "dividend", "sp500"))
    form = f"""
    <form onsubmit="submitJob(event, this, null); return false;" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <input type="hidden" name="action" value="scan">
      <select name="universe">{universe_opts}</select>
      <label style="font-size:12px;display:flex;gap:6px;align-items:center">
        <input type="checkbox" name="portfolio" checked> include Portfolio management</label>
      <button class="btn">Run Scan</button>
      <span style="font-size:11px;color:#898781">writes CSVs, research pages, and a fresh dashboard</span>
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
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
      <input id="rsearch" placeholder="Filter by ticker or sector…" style="min-width:220px"
             oninput="renderResearch()">
      <select id="rview" onchange="renderResearch()">
        <option value="table">Table view</option>
        <option value="grouped">Grouped by sector</option>
      </select>
      <select id="rwatch">{watch_opts}</select>
      <span style="font-size:11px;color:#898781;margin-left:auto">
        <span id="rcount">{len(rows)}</span> tickers</span>
    </div>
    <div id="research-root"></div>
    """

    js = f"""
    const RESEARCH_ROWS = {rows_json};
    const WATCHLISTS = {json.dumps(watchlists)};
    let sortKey = 'ticker', sortDir = 1;
    function starredIn(name, ticker) {{ return (WATCHLISTS[name] || []).includes(ticker); }}
    function actionColor(a) {{ return a === 'READY' ? '#0F6E56' : a === 'WATCH' ? '#8a6d1a' : a === 'AVOID' ? '#A32D2D' : '#898781'; }}
    function sortRows(rows) {{
      return [...rows].sort((a, b) => {{
        const av = a[sortKey] ?? '', bv = b[sortKey] ?? '';
        return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
      }});
    }}
    function renderResearch() {{
      const q = document.getElementById('rsearch').value.trim().toUpperCase();
      const view = document.getElementById('rview').value;
      const watch = document.getElementById('rwatch').value;
      let rows = RESEARCH_ROWS.filter(r =>
        !q || r.ticker.includes(q) || (r.sector || '').toUpperCase().includes(q));
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
      root.innerHTML = `<table><thead><tr>
        <th></th>
        <th style="cursor:pointer" onclick="setSort('ticker')">Ticker</th>
        <th style="cursor:pointer" onclick="setSort('sector')">Sector</th>
        <th style="cursor:pointer" onclick="setSort('category')">Category</th>
        <th style="cursor:pointer" onclick="setSort('conv_overall')">Score</th>
        <th>Action</th>
        <th style="cursor:pointer" onclick="setSort('updated_at')">Updated</th>
        <th></th></tr></thead><tbody>
        ${{rows.map(r => `<tr>
          <td><button onclick="toggleWatchlist(document.getElementById('rwatch').value, '${{r.ticker}}', this)"
              style="background:none;border:none;font-size:14px;color:#c9a227">${{starredIn(document.getElementById('rwatch').value, r.ticker) ? '★' : '☆'}}</button></td>
          <td><b>${{r.ticker}}</b></td>
          <td>${{r.sector || '—'}}</td>
          <td>${{r.category || '—'}}</td>
          <td>${{r.conv_overall ?? '—'}}</td>
          <td><span style="color:${{actionColor(r.conv_action)}};font-weight:600;font-size:11px">${{r.conv_action || '—'}}</span></td>
          <td style="font-size:11px;color:#898781">${{(r.updated_at || '').slice(5,16)}}</td>
          <td><a href="/research/${{r.ticker}}.html" class="btn secondary" style="text-decoration:none;padding:3px 10px;font-size:11px">Open</a></td>
        </tr>`).join('')}}
      </tbody></table>`;
    }}
    function setSort(key) {{
      sortDir = (sortKey === key) ? -sortDir : 1;
      sortKey = key;
      renderResearch();
    }}
    document.addEventListener('DOMContentLoaded', renderResearch);
    // A research/news job finishing means RESEARCH_ROWS is stale (updated
    // scores, new tickers, refreshed timestamps) — reload once to pick it up
    function onJobFinished(j) {{
      if (j.kind === 'research' || j.kind === 'news') setTimeout(() => location.reload(), 1200);
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
            "Avg_Cost, Entry_Date, Strategy, Stop, Target, Notes)."), pad="40px")
        return body, ""

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
        </tr>""")

    holdings = f"""<table><thead><tr>
      <th>Ticker</th><th>Strategy</th><th>Cap</th><th style="text-align:right">Shares</th>
      <th style="text-align:right">Price</th><th style="text-align:right">Gain %</th>
      <th style="text-align:right">Alloc %</th><th style="text-align:right">Days Held</th>
      <th style="text-align:right">Stop</th><th style="text-align:right">Target</th>
      <th>Next Action</th><th>Alerts</th></tr></thead>
      <tbody>{''.join(holdings_rows)}</tbody></table>"""

    body = (
        card("Portfolio Summary", summary, "💼")
        + card("Allocation", alloc_html, "📊")
        + card("Holdings & Watchlist", holdings, "📋")
    )
    extra_js = "function onJobFinished(j) { setTimeout(() => location.reload(), 1200); }"
    return body, extra_js


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

def automation_page() -> tuple[str, str]:
    from stockanalysis.reporting.portfolio import PORTFOLIO_VALUE, SMALLCAP_MAX_PCT

    alive = jobstore.scheduler_alive()
    if alive:
        sched_jobs = jobstore.scheduler_jobs()
        sched_rows = "".join(
            f'<tr><td>{esc(j["job"])}</td><td>{esc(j["next_run"] or "—")}</td></tr>'
            for j in sched_jobs
        ) or f'<tr><td colspan="2">{empty("No jobs registered yet.")}</td></tr>'
        scheduler_html = (
            badge("● RUNNING", "good", "small")
            + '<div style="font-size:11px;color:#898781;margin-top:8px">'
              'Cron-style loop firing the scans/emails/cleanup below on schedule, '
              'in the background of this web app process.</div>'
              f'<table style="margin-top:10px"><thead><tr><th>Job</th>'
              f'<th>Next run (ET)</th></tr></thead><tbody>{sched_rows}</tbody></table>'
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
