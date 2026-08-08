"""
longterm_view.py
================
The Long-Term Buy Engine page. Presentation only: every score, band, verdict
and blocker comes from core.longterm through api.longterm(), and this file
renders what it is handed.

That separation is what lets each row's expanded panel claim to show "why"
and be right — the ✓/✗ lines, the gate a name stopped at, and the prices to
wait for are the engine's own output, not a second implementation of the
rules in HTML.

Server-rendered rather than a JS controller like screener_view: this page has
no rule builder and no per-keystroke re-query, so the whole thing is one
render at a few tens of milliseconds over 545 rows. Filtering is a query
string and a page load, which keeps the URL shareable.

The layout follows §15 of the framework — one row per company, the eight
judgments side by side, the action last — because the point of the table is
to make the disagreements visible. A name that is Elite and Overvalued and a
name that is Watchlist and Undervalued both score in the seventies, and a
single blended number would hide which is which.
"""

from __future__ import annotations

import string
from urllib.parse import urlencode

from stockanalysis.core.longterm.technicals import SUPPORT_SLOTS

from stockanalysis.core.longterm.engine import ACTION_ICONS

from .views import badge, card, empty, esc, tv_url

_ACTION_STYLE = {
    "BUY NOW": ("#E1F5EE", "#085041"),
    "BUY ON CONFIRMATION": ("#E1F5EE", "#0F6E56"),
    "BUY ON 8/21 EMA": ("#E6F1FB", "#0C447C"),
    "BUY ON 50 MA": ("#E6F1FB", "#0C447C"),
    "BUY ON BREAKOUT RETEST": ("#E6F1FB", "#0C447C"),
    "BUY ON 200 MA": ("#E6F1FB", "#0C447C"),
    "BUY ON SUPPORT": ("#E6F1FB", "#0C447C"),
    "DEEP PULLBACK — WAIT FOR SUPPORT": ("#FAEEDA", "#633806"),
    "WATCH": ("#F1EFE8", "#444441"),
    "WAIT": ("#FAEEDA", "#633806"),
    "RESEARCH": ("#F1EFE8", "#444441"),
    "AVOID": ("#FCEBEB", "#791F1F"),
}

_TIER_STYLE = {"Elite": "good", "High Quality": "good",
               "Watchlist": "watch", "Reject": "bad"}
_BAND_STYLE = {"UNDERVALUED": "good", "FAIR": "watch", "OVERVALUED": "bad"}

# Zone and action names are written out rather than derived with .title() or
# .replace(): both mangle the acronyms this domain is full of, turning "EMA"
# into "E MA" and "BUY ON 8/21 EMA" into "Buy On 8/21 Ema".
_ZONE_SHORT = {"EMA": "8/21 EMA", "50MA": "50 MA", "200MA": "200 MA",
               "BREAKOUT": "Breakout", "NONE": "—"}
_ACTION_SHORT = {"BUY NOW": "Buy now",
                 "BUY ON CONFIRMATION": "Buy on confirmation",
                 "BUY ON 8/21 EMA": "Buy on 8/21 EMA",
                 "BUY ON 50 MA": "Buy on 50 MA",
                 "BUY ON BREAKOUT RETEST": "Buy on breakout retest",
                 "BUY ON 200 MA": "Buy on 200 MA",
                 "BUY ON SUPPORT": "Buy on support",
                 "DEEP PULLBACK — WAIT FOR SUPPORT": "Deep pullback",
                 "WATCH": "Watch", "WAIT": "Wait",
                 "RESEARCH": "Research", "AVOID": "Avoid"}

# Stage is what the Pullback column shows now. The zone answers "is price on
# a tracked level" and collapses a 22%-below-the-50-MA correction to "—";
# the stage names it.
_STAGE_SHORT = {"AT_HIGHS": "At highs", "STAGE1_EMA": "S1 · 8/21 EMA",
                "STAGE2_50MA": "S2 · 50 MA", "STAGE3_DEEP": "S3 · deep",
                "STAGE4_BREAKDOWN": "S4 · breakdown",
                "EXTENDED": "Extended"}
# Ordered so sorting descending puts the shallow, tradeable pullbacks first.
_STAGE_RANK = {"STAGE2_50MA": 5, "STAGE1_EMA": 4, "STAGE3_DEEP": 3,
               "AT_HIGHS": 2, "EXTENDED": 1, "STAGE4_BREAKDOWN": 0}

# Which gate a name stopped at, in plain language for the filter chips.
_GATE_LABEL = {
    "quality": "Failed on business quality",
    "valuation": "Failed on price",
    # Deliberately not "Failed on trend": the same gate now catches a broken
    # trend AND one whose structure holds but was never fully measured, and
    # calling the second a failure states something the data does not say.
    "trend": "Long-term trend not confirmed",
    "regime": "Held back by the market regime",
    "earnings": "Held back by earnings",
    "entry": "No entry at this price",
    "support": "Not enough support confluence",
    "trigger": "Waiting on confirmation",
    "readiness": "Support not tested yet",
    "confirmed": "All four gates passed",
}


def _pct(v, nd=1, dash="—"):
    if v is None:
        return dash
    return f"{v:+.{nd}f}%"


def _score_cell(value, label=None, style="muted"):
    if value is None:
        return '<span style="color:#898781">—</span>'
    inner = f'<strong>{value}</strong>'
    if label:
        inner += f' {badge(label, style, "small")}'
    return inner


def _action_pill(action, icon):
    bg, fg = _ACTION_STYLE.get(action, ("#F1EFE8", "#444441"))
    return (f'<span style="background:{bg};color:{fg};font-size:10px;'
            f'font-weight:700;padding:3px 9px;border-radius:5px;'
            f'white-space:nowrap">{icon} {esc(action)}</span>')


# ─────────────────────────────────────────────────────────────────────────────
# The expanded panel — the audit behind one verdict
# ─────────────────────────────────────────────────────────────────────────────

def _list_block(title, items, mark, color):
    if not items:
        return ""
    lis = "".join(
        f'<li style="margin:3px 0;color:#444441">'
        f'<span style="color:{color};font-weight:700">{mark}</span> '
        f'{esc(item)}</li>' for item in items)
    return (f'<div style="margin-bottom:10px">'
            f'<div style="font-size:10px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:#898781;margin-bottom:4px">'
            f'{esc(title)}</div>'
            f'<ul style="margin:0;padding-left:16px;font-size:12px;'
            f'list-style:none">{lis}</ul></div>')


def _quality_panel(q):
    if not q.get("components"):
        return empty("no fundamental data for this ticker")
    rows = []
    for c in sorted(q["components"], key=lambda x: -x["weight"]):
        weak = c["name"] in (q.get("weak_proxies") or [])
        pct = max(0, min(100, c["score"]))
        rows.append(
            f'<tr>'
            f'<td style="padding:3px 8px 3px 0;white-space:nowrap">'
            f'{esc(c["name"])}'
            + (' <span title="thin evidence for its weight — read as a '
               'tiebreaker" style="color:#8a6d1a">⚠</span>' if weak else '')
            + f'</td>'
            f'<td style="padding:3px 8px 3px 0;color:#898781">{c["weight"]}%</td>'
            f'<td style="padding:3px 8px 3px 0;width:90px">'
            f'<div style="background:#f1efea;border-radius:3px;height:6px">'
            f'<div style="width:{pct}%;height:100%;border-radius:3px;'
            f'background:{"#0F6E56" if pct >= 60 else "#8a6d1a" if pct >= 35 else "#A32D2D"}">'
            f'</div></div></td>'
            f'<td style="padding:3px 8px 3px 0"><strong>{c["score"]:.0f}</strong></td>'
            f'<td style="padding:3px 0;color:#898781">{esc(c["detail"])}</td>'
            f'</tr>')
    missing = ""
    if q.get("missing"):
        missing = (f'<div style="font-size:11px;color:#898781;margin-top:6px">'
                   f'Not measured: {esc(", ".join(q["missing"]))} — the score '
                   f'is renormalised over the {int(q["coverage"] * 100)}% of '
                   f'weight that had data, not padded with zeros.</div>')
    return (f'<table style="width:100%;border-collapse:collapse;font-size:11px">'
            f'{"".join(rows)}</table>{missing}')


def _valuation_panel(v):
    if not v.get("band"):
        return empty("could not be valued — "
                     + "; ".join(v.get("notes") or ["no method applied"]))
    head = f'<div style="font-size:12px;margin-bottom:8px">{esc(v["headline"] or "")}</div>'
    method = {"REVERSE_DCF": "Reverse DCF — what the price already assumes",
              "PEER": "Peer multiple — priced against its sector"}.get(
                  v["method"], v["method"] or "")
    bits = "".join(f'<li style="margin:3px 0">{esc(a)}</li>'
                   for a in (v.get("assumptions") or []))
    notes = "".join(
        f'<div style="font-size:11px;color:#8a6d1a;margin-top:5px">⚠ {esc(n)}</div>'
        for n in (v.get("notes") or []))
    return (head +
            f'<div style="font-size:10px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:#898781;margin-bottom:4px">'
            f'{esc(method)}</div>'
            f'<ul style="margin:0;padding-left:16px;font-size:11px;'
            f'color:#444441">{bits}</ul>{notes}')


def _trend_panel(t):
    cells = []
    for c in t.get("checks", []):
        mark, color = ("✓", "#0F6E56") if c["ok"] else \
                      ("✗", "#A32D2D") if c["ok"] is False else ("?", "#898781")
        req = ' <span style="color:#898781">(required)</span>' if c["required"] else ""
        cells.append(f'<li style="margin:3px 0;font-size:11px">'
                     f'<span style="color:{color};font-weight:700">{mark}</span> '
                     f'{esc(c["name"])}{req} — '
                     f'<span style="color:#898781">{esc(c["detail"])}</span></li>')
    return f'<ul style="margin:0;padding-left:16px;list-style:none">{"".join(cells)}</ul>'


def _range_panel(rng):
    """The 52-week range as a position, not just two numbers."""
    high, low, price = rng.get("high"), rng.get("low"), rng.get("price")
    if high is None and low is None:
        return empty("no 52-week range for this ticker")
    pos = rng.get("position_pct")
    bar = ""
    if pos is not None:
        bar = (
            f'<div style="position:relative;height:8px;border-radius:4px;'
            f'margin:8px 0 5px;background:linear-gradient(90deg,#E1F5EE,#FAEEDA,#FCEBEB)">'
            f'<div style="position:absolute;left:{pos:.1f}%;top:-3px;'
            f'width:2px;height:14px;background:#0b0b0b;'
            f'transform:translateX(-1px)"></div></div>')

    def cell(label, value, note):
        return (f'<div><div style="font-size:10px;text-transform:uppercase;'
                f'letter-spacing:.06em;color:#898781">{esc(label)}</div>'
                f'<div style="font-size:13px;font-weight:600">{value}</div>'
                f'<div style="font-size:10px;color:#898781">{esc(note)}</div></div>')

    from_high = rng.get("from_high_pct")
    from_low = rng.get("from_low_pct")
    return (
        f'<div style="display:flex;gap:22px;flex-wrap:wrap">'
        + cell("52W Low", f'${low:,.2f}' if low is not None else "—",
               f"{from_low:+.1f}% above it" if from_low is not None else "")
        + cell("Now", f'${price:,.2f}' if price is not None else "—",
               f"{pos:.0f}% up the range" if pos is not None else "")
        + cell("52W High", f'${high:,.2f}' if high is not None else "—",
               f"{from_high:+.1f}% from it" if from_high is not None else "")
        + '</div>' + bar
        + '<div style="font-size:10px;color:#898781">Distance from the high is '
          'the drawdown you are buying; distance from the low is the recovery '
          'you are paying for.</div>')


def _support_panel(conf, vol, pullback):
    def items(entries, mark, color):
        return "".join(
            f'<li style="margin:2px 0;font-size:11px">'
            f'<span style="color:{color};font-weight:700">{mark}</span> '
            f'{esc(e["name"])} <span style="color:#898781">+{e["points"]} · '
            f'{esc(e["detail"])}</span></li>' for e in entries)

    conf_html = (f'<div style="font-size:11px;margin-bottom:4px">'
                 f'<strong>{conf["score"]}/100</strong> {esc(conf["label"])} — '
                 f'{len(conf["hits"])} of 6 levels agree</div>'
                 f'<ul style="margin:0 0 8px;padding-left:14px;list-style:none">'
                 + items(conf["hits"], "✓", "#0F6E56")
                 + items(conf["misses"], "✗", "#A32D2D") + '</ul>')

    if vol.get("score") is None:
        vol_html = empty("pullback volume not measured — run a scan")
    else:
        vol_html = (f'<div style="font-size:11px;margin-bottom:4px">'
                    f'<strong>{vol["score"]}/100</strong> {esc(vol["label"])} '
                    f'<span style="color:#898781">({vol["measured"]} of 5 '
                    f'checks measured)</span></div>'
                    f'<ul style="margin:0;padding-left:14px;list-style:none">'
                    + items(vol["hits"], "✓", "#0F6E56")
                    + items(vol["misses"], "✗", "#A32D2D")
                    + items(vol.get("unknown") or [], "?", "#898781") + '</ul>')

    return (f'<div style="font-size:11px;color:#444441;margin-bottom:8px">'
            f'{esc(pullback["note"])}</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">'
            f'<div>{conf_html}</div><div>{vol_html}</div></div>')


def _entries_panel(r):
    entries = r.get("entries") or []
    if not entries:
        return ""
    rows = "".join(
        f'<tr><td style="padding:3px 10px 3px 0">{esc(e["name"])}</td>'
        f'<td style="padding:3px 10px 3px 0"><strong>${e["price"]:,.2f}</strong></td>'
        f'<td style="padding:3px 10px 3px 0;color:#898781">'
        f'{_pct(e["move_pct"])} from here</td>'
        f'<td style="padding:3px 0;color:#898781">'
        + (f'{e["tranche_pct"]}% tranche' if e["tranche_pct"] else "—")
        + '</td></tr>' for e in entries[:4])
    return (f'<div style="margin-top:10px">'
            f'<div style="font-size:10px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:#898781;margin-bottom:4px">'
            f'Levels below the current price</div>'
            f'<table style="border-collapse:collapse;font-size:11px">{rows}</table>'
            f'</div>')


def _detail(r):
    q, v, t = r["quality"], r["valuation"], r["trend"]
    gate = _GATE_LABEL.get(r["gate"], r["gate"])
    parts = [
        f'<div style="font-size:11px;color:#898781;margin-bottom:10px">'
        f'Stopped at: <strong style="color:#444441">{esc(gate)}</strong>'
        f' · LT score {r["lt_score"] if r["lt_score"] is not None else "—"}'
        f' from {int((r["lt_coverage"] or 0) * 100)}% of its inputs</div>',
        _list_block("Why", r.get("why"), "✓", "#0F6E56"),
        _list_block("What is blocking it", r.get("blockers"), "✗", "#A32D2D"),
        _list_block("What would change it", r.get("triggers"), "→", "#0C447C"),
        _entries_panel(r),
    ]
    grid = (
        '<div style="display:grid;grid-template-columns:1fr;gap:14px;'
        'margin-top:12px">'
        f'<div>{card("Business quality — LQuality", _quality_panel(q), "💎")}</div>'
        f'<div>{card("Valuation", _valuation_panel(v), "⚖️")}</div>'
        f'<div>{card("Long-term trend", _trend_panel(t), "📈")}</div>'
        f'<div>{card("52-week range", _range_panel(r["pullback"].get("range_52w") or {}), "📏")}</div>'
        f'<div>{card("Support and pullback volume", _support_panel(r["confluence"], r["volume"], r["pullback"]), "🧱")}</div>'
        '</div>')
    return "".join(parts) + grid


# ─────────────────────────────────────────────────────────────────────────────
# The table — §15
# ─────────────────────────────────────────────────────────────────────────────

_TH = ('padding:7px 8px;font-size:10px;text-transform:uppercase;'
       'letter-spacing:.06em;color:#898781;border-bottom:1px solid #e1e0d9;'
       'white-space:nowrap;cursor:pointer;user-select:none')

# Sorting and column dragging, in the page rather than the server, because
# both are view state — re-rendering 545 rows over the network to reverse a
# column would be a page load for something the browser already has.
#
# Two things make this less trivial than a normal sortable table:
#
#   1. Every result is TWO <tr>s — the summary and the collapsible reasoning
#      beneath it. Sorting has to move them as a unit, or the audit ends up
#      under someone else's ticker. That is why rows carry data-main /
#      data-detail and the sort operates on pairs.
#   2. Missing values must not sort as zero. A ticker with no 200 MA is not
#      the worst 200 MA support in the library; blanks are pinned to the
#      bottom on both directions.
#
# Order and sort survive reloads in localStorage, since a layout you have to
# rebuild after every filter click is not a layout you would use.
_TABLE_JS = r"""
(function () {
  var table = document.getElementById('lt-table');
  if (!table) return;
  var KEY = 'lt.cols.v1', SORTKEY = 'lt.sort.v1';
  var head = table.tHead.rows[0], body = table.tBodies[0];

  function colKeys() {
    return Array.prototype.map.call(head.cells, function (th) {
      return th.dataset.col;
    });
  }

  // Summary row + its detail row, kept together through every reorder.
  function pairs() {
    var out = [], cur = null;
    Array.prototype.forEach.call(body.rows, function (tr) {
      if (tr.dataset.main) { cur = { main: tr, rest: [] }; out.push(cur); }
      else if (cur) { cur.rest.push(tr); }
    });
    return out;
  }

  function cellOf(tr, key) {
    return tr.querySelector('td[data-col="' + key + '"]');
  }

  function sortBy(key, dir) {
    // Sorting dissolves the action grouping. A ranking that restarts inside
    // each group is not a ranking, and leaving the banner rows in place
    // would strand them against whichever pair happened to precede them.
    var banners = body.querySelectorAll('tr[data-group]');
    if (banners.length) {
      Array.prototype.forEach.call(banners, function (b) { b.remove(); });
      var note = document.getElementById('lt-group-note');
      if (note) note.style.display = '';
    }
    var groups = pairs();
    var type = (head.querySelector('th[data-col="' + key + '"]') || {}).dataset;
    var numeric = type && type.type === 'num';
    groups.forEach(function (g, i) {
      var td = cellOf(g.main, key);
      var raw = td ? td.dataset.sort : '';
      g._blank = (raw === undefined || raw === '');
      g._v = numeric ? parseFloat(raw) : String(raw || '').toUpperCase();
      if (numeric && isNaN(g._v)) { g._blank = true; }
      g._i = i;                       // stable tiebreak
    });
    groups.sort(function (a, b) {
      // Blanks last in BOTH directions: "no value" is not an extreme value.
      if (a._blank !== b._blank) return a._blank ? 1 : -1;
      if (a._blank) return a._i - b._i;
      if (a._v < b._v) return dir === 'asc' ? -1 : 1;
      if (a._v > b._v) return dir === 'asc' ? 1 : -1;
      return a._i - b._i;
    });
    var frag = document.createDocumentFragment();
    groups.forEach(function (g) {
      frag.appendChild(g.main);
      g.rest.forEach(function (r) { frag.appendChild(r); });
    });
    body.appendChild(frag);
    markSort(key, dir);
  }

  function markSort(key, dir) {
    Array.prototype.forEach.call(head.cells, function (th) {
      var arrow = th.querySelector('.lt-arrow');
      if (!arrow) return;
      var on = th.dataset.col === key;
      arrow.textContent = on ? (dir === 'asc' ? ' ▲' : ' ▼') : '';
      th.style.color = on ? '#0b0b0b' : '#898781';
    });
  }

  function moveColumn(from, to) {
    if (from === to) return;
    var rows = [head].concat(Array.prototype.filter.call(body.rows, function (r) {
      return r.dataset.main;                 // detail rows are one colspan cell
    }));
    rows.forEach(function (row) {
      var cell = row.cells[from];
      var ref = row.cells[to];
      if (!cell || !ref) return;
      row.insertBefore(cell, from < to ? ref.nextSibling : ref);
    });
    try { localStorage.setItem(KEY, JSON.stringify(colKeys())); } catch (e) {}
  }

  // Restore a saved order by moving each column into place, left to right.
  try {
    var saved = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (Array.isArray(saved)) {
      saved.forEach(function (key, target) {
        var now = colKeys().indexOf(key);
        if (now > -1 && now !== target) moveColumn(now, target);
      });
    }
  } catch (e) {}

  var dragFrom = null;
  Array.prototype.forEach.call(head.cells, function (th) {
    th.draggable = true;
    th.addEventListener('dragstart', function (e) {
      dragFrom = Array.prototype.indexOf.call(head.cells, th);
      th.style.opacity = '.4';
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', th.dataset.col); } catch (err) {}
    });
    th.addEventListener('dragend', function () {
      th.style.opacity = '';
      Array.prototype.forEach.call(head.cells, function (o) {
        o.style.borderLeft = ''; o.style.borderRight = '';
      });
    });
    th.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      var over = Array.prototype.indexOf.call(head.cells, th);
      th.style.borderLeft = over < dragFrom ? '2px solid #185FA5' : '';
      th.style.borderRight = over > dragFrom ? '2px solid #185FA5' : '';
    });
    th.addEventListener('dragleave', function () {
      th.style.borderLeft = ''; th.style.borderRight = '';
    });
    th.addEventListener('drop', function (e) {
      e.preventDefault();
      var to = Array.prototype.indexOf.call(head.cells, th);
      if (dragFrom !== null) moveColumn(dragFrom, to);
      dragFrom = null;
    });
    th.addEventListener('click', function () {
      var key = th.dataset.col;
      // Numbers open on descending (best first); text opens on ascending.
      var opening = th.dataset.type === 'num' ? 'desc' : 'asc';
      var dir = th.dataset.dir === opening
        ? (opening === 'desc' ? 'asc' : 'desc') : opening;
      Array.prototype.forEach.call(head.cells, function (o) { o.dataset.dir = ''; });
      th.dataset.dir = dir;
      sortBy(key, dir);
    });
  });

  // Column ORDER persists; the active sort deliberately does not.
  //
  // Restoring a saved sort on load looks helpful and is not: sorting
  // dissolves the action grouping, so a sort remembered from a previous
  // visit silently destroys the default view on every subsequent page load,
  // and the grouping never comes back. Order is a layout preference worth
  // keeping. A sort is a question you asked once.
  try { localStorage.removeItem(SORTKEY); } catch (e) {}

  var reset = document.getElementById('lt-reset-cols');
  if (reset) {
    reset.addEventListener('click', function (e) {
      e.preventDefault();
      try { localStorage.removeItem(KEY); } catch (err) {}
      location.reload();
    });
  }
})();
"""
_TD = 'padding:8px;border-bottom:0.5px solid #f1efea;font-size:12px;vertical-align:top'


def _support_confluence_cell(conf):
    """Levels agreeing, with the weighted score demoted to context.

    The count leads because the count is what the engine actually gates on
    (MIN_CONFLUENCE_HITS), and because the score cannot carry the label —
    its ranges overlap between adjacent counts, so 60/100 might be three
    levels or four. Showing the score first described one thing while the
    decision used another.

    Sorts on count first, score as the tiebreak, so ordering by this column
    matches what the label says while still separating a 50 MA + 200 MA
    agreement from an 8/21 EMA + key-level one.
    """
    n, possible = conf.get("agreeing", len(conf["hits"])), conf.get("possible", 6)
    score = conf["score"]
    colour = ("#0F6E56" if n >= 4 else "#0b0b0b" if n >= 3
              else "#8a6d1a" if n >= 2 else "#A32D2D")
    names = ", ".join(h["name"] for h in conf["hits"]) or "nothing holding here"
    return (f'<span style="color:{colour};font-weight:700" '
            f'title="{esc(names)}">{n} of {possible}</span>'
            f'<div style="font-size:10px;color:#898781;white-space:nowrap">'
            f'{esc(conf["label"])} · {score}/100</div>',
            n * 1000 + score)


def _buyzone_cell(pullback):
    """The price to work an order at — and whether anyone has ever defended it.

    A tested volume shelf and a moving average that merely happens to be the
    next line down are rendered differently on purpose. Roughly a third of
    the library has no tested level, and showing a computed average in the
    same voice would turn "support is probably around here" into "support is
    here". Derived levels are muted, italic, and say which average they came
    from.
    """
    bz = (pullback or {}).get("buy_zone") or {}
    price, dist = bz.get("price"), bz.get("distance_pct")
    if price is None:
        return '<span style="color:#898781">—</span>', None
    touches = bz.get("touches")
    if bz.get("actual_support"):
        # Green and bold: the market has defended this price before.
        style = "color:#0F6E56;font-weight:700"
        sub = f"{touches:.0f} touches" if touches else "tested"
    elif bz.get("source") == "volume_shelf":
        style = "color:#8a6d1a;font-weight:600"
        sub = (f"{touches:.0f} touches · unconfirmed" if touches
               else "unconfirmed")
    else:
        # Grey and italic: arithmetic on recent closes, not a level anyone
        # has defended. The label names which average it came from.
        style = "color:#898781;font-style:italic"
        sub = f'{bz.get("label") or "MA"} · derived'
    dist_txt = f' <span style="color:#898781">{dist:+.1f}%</span>' \
        if dist is not None else ""
    return (f'<span style="{style};white-space:nowrap" '
            f'title="{esc(bz.get("note") or "")}">${price:,.2f}</span>{dist_txt}'
            f'<div style="font-size:10px;color:#898781;white-space:nowrap">'
            f'{esc(sub)}</div>', dist)


def _support_cell(r, key):
    """One rung of the S1..S4 ladder: how far price sits above or below that
    moving average, and whether the level is holding at all.

    The sign is the content. Above means support underfoot, below means the
    level was lost and is now overhead — the distinction the whole engine
    turns on — so the colour follows `held`, not the magnitude.
    """
    lv = (r["pullback"].get("by_level") or {}).get(key) or {}
    dist, price = lv.get("distance_pct"), lv.get("price")
    if dist is None:
        return '<span style="color:#898781">—</span>', None
    colour = "#0F6E56" if lv.get("held") else "#A32D2D"
    weight = "700" if lv.get("supporting") else "400"
    at = ' title="price is sitting on this level"' if lv.get("supporting") else ""
    html = (f'<span style="color:{colour};font-weight:{weight}"{at}>'
            f'{dist:+.1f}%</span>')
    if price is not None:
        html += (f'<div style="font-size:10px;color:#898781">'
                 f'${price:,.2f}</div>')
    return html, dist


# (key, header, alignment, sort type). Order here is the DEFAULT order; the
# user can drag columns and the choice persists in localStorage.
_COLUMNS = (
    ("ticker", "Ticker", "left", "text"),
    ("price", "Price", "right", "num"),
    ("lquality", "LQuality", "left", "num"),
    ("valuation", "Valuation", "left", "num"),
    ("trend", "Trend", "center", "num"),
    ("pullback", "Pullback", "left", "num"),
    ("buyzone", "Buy Zone", "right", "num"),
    ("support", "Support", "left", "num"),   # levels agreeing, score as tiebreak
    ("s1", "8 EMA", "right", "num"),
    ("s2", "21 EMA", "right", "num"),
    ("s3", "50 MA", "right", "num"),
    ("s4", "200 MA", "right", "num"),
    ("rs", "RS", "center", "num"),
    ("market", "Market", "center", "text"),
    ("lt", "LT Score", "left", "num"),
    ("action", "Action", "left", "num"),
)
_HEADERS = tuple(c[1] for c in _COLUMNS)

# Sort keys for the columns whose display is a symbol or a label. Ranked so
# "descending" means "better" everywhere — otherwise sorting Trend puts the
# broken ones on top, which nobody wants on the first click.
_TREND_RANK = {True: 2, None: 1, False: 0}
_BAND_RANK = {"UNDERVALUED": 2, "FAIR": 1, "OVERVALUED": 0}
_ACTION_ORDER = ("BUY NOW", "BUY ON CONFIRMATION", "BUY ON 8/21 EMA",
                 "BUY ON 50 MA", "BUY ON BREAKOUT RETEST", "BUY ON 200 MA",
                 "BUY ON SUPPORT", "DEEP PULLBACK — WAIT FOR SUPPORT",
                 "WATCH", "WAIT", "RESEARCH", "AVOID")
_ACTION_RANK = {a: len(_ACTION_ORDER) - i for i, a in enumerate(_ACTION_ORDER)}


def _cells(r):
    """(column key -> (html, sort_value)) for one result row."""
    q, v, p, conf, rs = (r["quality"], r["valuation"], r["pullback"],
                         r["confluence"], r["rs"])
    # The engine's own tri-state icon: 🟢 confirmed / 🟡 partial / 🔴 broken.
    # A grey "unknown" dot read as "no data" when the real meaning is
    # "structure holds, slopes unmeasured".
    trend_mark = r["trend"].get("icon") or "⚪"
    rs_mark = ("🟢" if rs["strong"] else "🔴" if rs["strong"] is False else "⚪")
    market = {"FAVORABLE": "🟢", "SELECTIVE": "🟡", "DEFENSIVE": "🔴"}.get(
        r["regime"], "⚪")

    out = {
        "ticker": (
            f'<a href="{tv_url(r["ticker"])}" target="_blank" '
            f'style="font-weight:700;color:#0b0b0b;text-decoration:none">'
            f'{esc(r["ticker"])}</a>'
            f'<div style="font-size:10px;color:#898781;max-width:150px;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
            f'{esc(r["name"])}</div>', r["ticker"]),
        "lquality": (
            _score_cell(q["score"], q["tier"],
                        _TIER_STYLE.get(q["tier"], "muted")), q["score"]),
        "valuation": (
            (f'{v["band_icon"]} '
             f'{badge(v.get("band_label") or v["band"].title(), _BAND_STYLE.get(v["band"], "muted"), "small")}'
             f'<div style="font-size:10px;color:#898781" '
             f'title="{esc(v.get("confidence_note") or "")}">'
             f'{v.get("confidence_icon", "")} {esc((v.get("confidence") or "").title())}'
             f'</div>'
             if v["band"] else '<span style="color:#898781">—</span>'),
            _BAND_RANK.get(v["band"])),
        "trend": (trend_mark, _TREND_RANK.get(r["trend"]["pass"])),
        "pullback": (
            f'{p.get("stage_icon", "")} '
            f'{esc(_STAGE_SHORT.get(p.get("stage"), _ZONE_SHORT.get(p["zone"], p["zone"])))}',
            _STAGE_RANK.get(p.get("stage"))),
        "price": (f'<strong>${r["price"]:,.2f}</strong>' if r.get("price")
                  else '<span style="color:#898781">—</span>', r.get("price")),
        "buyzone": _buyzone_cell(p),
        "support": _support_confluence_cell(conf),
        "rs": (rs_mark, rs["score"]),
        "market": (market, r["regime"]),
        "lt": (f'<strong>{r["lt_score"] if r["lt_score"] is not None else "—"}</strong>',
               r["lt_score"]),
        "action": (
            _action_pill(r["action"], r["icon"])
            + (f'<div style="font-size:10px;color:#898781">'
               f'{r["tranche_pct"]}% tranche</div>'
               if r.get("tranche_pct") else ""),
            _ACTION_RANK.get(r["action"])),
    }
    for slot, key, _name in SUPPORT_SLOTS:
        out[slot.lower()] = _support_cell(r, key)
    return out


def _group_header(action, count):
    """A banner row separating one action from the next.

    Grouping is the default because the page's job is to answer "what should
    I do", and 545 rows sorted by a score answers "what ranks highest" —
    a different question. Sorting any column dissolves the groups (see the
    table JS), since a ranking that jumps between them is not a ranking.
    """
    bg, fg = _ACTION_STYLE.get(action, ("#F1EFE8", "#444441"))
    return (f'<tr data-group="1"><td colspan="{len(_COLUMNS)}" '
            f'style="padding:12px 8px 5px">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="background:{bg};color:{fg};font-size:10px;'
            f'font-weight:700;padding:3px 9px;border-radius:5px;'
            f'white-space:nowrap">{ACTION_ICONS.get(action, "")} '
            f'{esc(action)}</span>'
            f'<span style="font-size:11px;color:#898781">{count} '
            f'{"name" if count == 1 else "names"}</span>'
            f'<span style="flex:1;height:1px;background:#e1e0d9"></span>'
            f'</div></td></tr>')


def _grouped_rows(rows, expand):
    """Rows bucketed by action, in the engine's own priority order."""
    buckets = {}
    for r in rows:
        buckets.setdefault(r["action"], []).append(r)
    ordered = [a for a in _ACTION_ORDER if a in buckets]
    # Anything the engine gained that this view has not been taught about
    # still renders, at the end, rather than vanishing.
    ordered += [a for a in buckets if a not in _ACTION_ORDER]
    out = []
    for action in ordered:
        group = buckets[action]
        out.append(_group_header(action, len(group)))
        out.extend(_row(r, open_detail=expand) for r in group)
    return "".join(out)


def _row(r, open_detail: bool = False, order=None):
    order = order or [c[0] for c in _COLUMNS]
    align = {c[0]: c[2] for c in _COLUMNS}
    cells = _cells(r)
    tds = []
    for key in order:
        html, sort_value = cells.get(key, ("", None))
        sort_attr = "" if sort_value is None else esc(str(sort_value))
        tds.append(f'<td data-col="{key}" data-sort="{sort_attr}" '
                   f'style="{_TD};text-align:{align.get(key, "left")}">'
                   f'{html}</td>')

    return (f'<tr data-main="1">{"".join(tds)}</tr>'
            f'<tr data-detail="1"><td colspan="{len(_COLUMNS)}" '
            f'style="padding:0 8px 10px;border-bottom:0.5px solid #f1efea">'
            f'<details{" open" if open_detail else ""}>'
            f'<summary style="cursor:pointer;font-size:11px;'
            f'color:#185FA5;padding:2px 0">Show the reasoning</summary>'
            f'<div style="padding:8px 0 4px">{_detail(r)}</div>'
            f'</details></td></tr>')

# Ticker characters that survive the round trip to yfinance and TradingView:
# letters and digits, plus the separators share classes and indices use
# (BRK-B, BF.B, ^GSPC). Everything else is treated as a delimiter.
_TICKER_CHARS = set(string.ascii_uppercase + string.digits + ".-^")


def parse_tickers(raw: str, limit: int = 60) -> list[str]:
    """"nvda, msft  aapl;brk-b" -> ["NVDA", "MSFT", "AAPL", "BRK-B"].

    Split on anything that is not a ticker character rather than on a
    specific separator, because people paste lists in every shape a
    spreadsheet, a broker export or a chat message produces — commas,
    newlines, tabs, semicolons, or plain spaces. Order is the order typed
    and duplicates collapse, so a searched list reads back the way it was
    written.

    `limit` exists only to stop a pasted thousand-line column turning one
    page render into a thousand table rows.
    """
    out, seen, token = [], set(), []

    def flush():
        if not token:
            return
        word = "".join(token)
        if word and word not in seen:
            seen.add(word)
            out.append(word)
        token.clear()

    for ch in (raw or "").upper():
        if ch in _TICKER_CHARS:
            token.append(ch)
        else:
            flush()
    flush()
    return out[:limit]

# Actions the framework treats as actionable, in the order the page shows them.
_BUY_ACTIONS = ("BUY NOW", "BUY ON CONFIRMATION", "BUY ON 8/21 EMA",
                "BUY ON 50 MA", "BUY ON BREAKOUT RETEST", "BUY ON 200 MA",
                "BUY ON SUPPORT")

DEFAULT_LIMIT = 60


def longterm_page(query: dict | None = None) -> tuple[str, str]:
    from . import api

    query = query or {}
    action_filter = (query.get("action") or [""])[0].strip()
    regime_override = (query.get("regime") or [""])[0].strip() or None
    raw_query = (query.get("q") or [""])[0]
    grouped = (query.get("group") or ["action"])[0].strip().lower() != "off"
    wanted = parse_tickers(raw_query)
    try:
        limit = max(10, min(500, int((query.get("limit") or ["0"])[0] or 0)))
    except ValueError:
        limit = DEFAULT_LIMIT
    limit = limit or DEFAULT_LIMIT

    data = api.longterm(regime_override)
    rows, cov = data["rows"], data["coverage"]

    def link(**params):
        """A URL carrying the page's whole state, so no control silently
        discards another's — clicking a chip while a search is active used
        to drop the search."""
        state = {"q": raw_query.strip(), "action": action_filter,
                 "regime": regime_override or "",
                 "group": "" if grouped else "off"}
        state.update({k: ("" if v is None else str(v)) for k, v in params.items()})
        kept = {k: v for k, v in state.items() if v}
        return "/longterm" + (f"?{urlencode(kept)}" if kept else "")

    # ── ticker search ───────────────────────────────────────────────────────
    # Narrows the universe before anything else looks at it, so the chips
    # below count within the search rather than across the whole library.
    # Counting globally would offer "Avoid 347" next to three searched
    # tickers and return an empty table when clicked.
    by_ticker = {r["ticker"]: r for r in rows}
    missing = []
    if wanted:
        found = []
        for t in wanted:
            (found.append(by_ticker[t]) if t in by_ticker else missing.append(t))
        # Input order, not engine ranking: someone who typed a list is
        # comparing those names against each other and expects to read them
        # back in the order they wrote them.
        base = found
    else:
        base = rows

    counts = {}
    for r in base:
        counts[r["action"]] = counts.get(r["action"], 0) + 1

    # ── the banner that stops this page looking broken ──────────────────────
    # A library scanned before core.longterm existed has none of the columns
    # the trend gate and the confirmation check read, so every name legitimately
    # lands on WATCH. Without saying so, the page reads as an engine that
    # cannot find anything rather than one that has not been fed.
    warn = ""
    if cov["needs_rescan"]:
        warn = (
            f'<div style="background:#FAEEDA;border:0.5px solid #e8d5aa;'
            f'border-radius:10px;padding:12px 14px;margin-bottom:14px;'
            f'font-size:12px;color:#633806">'
            f'<strong>This library predates the engine.</strong> '
            f'Moving-average slopes are present on {cov["ma_slope"]} of '
            f'{cov["total"]} tickers, reversal candles on {cov["reversal"]}, '
            f'and multi-year statements on {cov["statements"]}. Until a scan '
            f'repopulates them the trend gate reads UNKNOWN and no name can '
            f'reach BUY NOW — the engine is refusing to confirm an entry it '
            f'cannot see, not failing to find one. Run a scan from the '
            f'<a href="/scanner" style="color:#633806">Scanner</a> page.</div>')

    # ── search bar ──────────────────────────────────────────────────────────
    # A plain GET form: the result stays in the URL, so a comparison of five
    # names is a link that can be bookmarked or pasted, and the back button
    # behaves.
    search = f"""
<form method="get" action="/longterm"
      style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;
             margin-bottom:12px">
  <input name="q" value="{esc(raw_query.strip())}" autocomplete="off"
         placeholder="Look up tickers — NVDA, or MSFT, AAPL, GOOGL"
         style="flex:1;min-width:260px;max-width:460px;padding:9px 12px;
                font-size:13px;border:0.5px solid #e1e0d9;border-radius:8px">
  {f'<input type="hidden" name="regime" value="{esc(regime_override)}">'
   if regime_override else ''}
  <button type="submit" class="btn" style="padding:9px 16px">Search</button>
  {f'<a href="{esc(link(q="", action="", limit=""))}" '
   f'style="font-size:12px;color:#185FA5">Clear</a>' if wanted else ''}
</form>"""

    notfound = ""
    if missing:
        notfound = (
            f'<div style="background:#F1EFE8;border-radius:8px;padding:9px 12px;'
            f'margin-bottom:12px;font-size:12px;color:#444441">'
            f'Not in the research library: '
            f'<strong>{esc(", ".join(missing))}</strong> — the engine only '
            f'scores tickers a scan has already covered. Add them from the '
            f'<a href="/scanner" style="color:#185FA5">Scanner</a> page and '
            f'they will appear here.</div>')

    # ── filter chips ────────────────────────────────────────────────────────
    def chip(label, value, count):
        on = action_filter == value
        bg, fg = ("#0b0b0b", "white") if on else ("#F1EFE8", "#444441")
        return (f'<a href="{esc(link(action="" if on else value, limit=""))}" '
                f'style="background:{bg};color:{fg};'
                f'font-size:11px;font-weight:600;padding:5px 11px;'
                f'border-radius:6px;text-decoration:none;white-space:nowrap">'
                f'{esc(label)} {count}</a>')

    buy_total = sum(counts.get(a, 0) for a in _BUY_ACTIONS)
    chips = [chip("All", "", len(base))]
    if buy_total or not wanted:
        chips.append(chip("Buy-ready", "BUY", buy_total))
    for action in _BUY_ACTIONS + ("WATCH", "WAIT", "AVOID"):
        if counts.get(action):
            chips.append(chip(_ACTION_SHORT.get(action, action), action,
                              counts[action]))

    shown = base
    if action_filter == "BUY":
        shown = [r for r in base if r["action"] in _BUY_ACTIONS]
    elif action_filter:
        shown = [r for r in base if r["action"] == action_filter]
    total_matching = len(shown)
    # An explicit search is never truncated — asking for eight tickers and
    # being shown the first six silently would be worse than a long page.
    shown = shown if wanted else shown[:limit]

    if shown:
        # One result means the reasoning IS the answer, so don't make the
        # user click again to reach it.
        expand = len(shown) == 1
        if grouped:
            body_rows = _grouped_rows(shown, expand)
        else:
            body_rows = "".join(_row(r, open_detail=expand) for r in shown)
    else:
        msg = ("Nothing matches this filter."
               if not wanted else
               f"None of those {len(base)} tickers are "
               f"{_ACTION_SHORT.get(action_filter, action_filter)}.")
        body_rows = (f'<tr><td colspan="10" style="padding:24px;'
                     f'text-align:center">{empty(msg)}</td></tr>')

    more = ""
    if total_matching > len(shown):
        more = (f'<div style="text-align:center;padding:12px">'
                f'<a href="{esc(link(limit=total_matching))}" '
                f'style="font-size:12px;color:#185FA5">'
                f'Show all {total_matching}</a></div>')

    regime_pill = {"FAVORABLE": "good", "SELECTIVE": "watch",
                   "DEFENSIVE": "bad"}.get(data["regime"], "muted")

    # min-width matters: without it `width:100%` makes the browser compress
    # ten columns to fit the card instead of overflowing, and the Action
    # column — the one the whole page exists to show — is what gets crushed.
    headers = "".join(
        f'<th data-col="{key}" data-type="{stype}" data-dir="" '
        f'title="Click to sort · drag to reorder" '
        f'style="{_TH};text-align:{align}">{esc(label)}'
        f'<span class="lt-arrow"></span></th>'
        for key, label, align, stype in _COLUMNS)

    table = (
        '<div style="overflow-x:auto">'
        '<table id="lt-table" style="width:100%;min-width:1180px;'
        'border-collapse:collapse">'
        f'<thead><tr>{headers}</tr></thead>'
        f'<tbody>{body_rows}</tbody></table></div>{more}')

    body = f"""
<div style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap;
            margin-bottom:12px">
  <div>
    <h2 style="margin:0 0 3px;font-size:19px">Long-Term Buy Engine</h2>
    <div style="font-size:11px;color:#898781;max-width:640px">
      Business quality → valuation → long-term trend → support → entry
      trigger, in that order. A company that fails an earlier gate cannot be
      rescued by a later one, so the chart never compensates for the
      business.
    </div>
  </div>
  <div style="margin-left:auto;text-align:right">
    {badge(data["regime"], regime_pill)}
    <div style="font-size:10px;color:#898781;margin-top:4px">
      {esc(data["regime_note"])}<br>{esc(data["risk_free_note"])}
    </div>
  </div>
</div>

{warn}
{search}
{notfound}

<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;
            margin-bottom:14px">
  {"".join(chips)}
  <a href="{esc(link(group="" if not grouped else "off"))}"
     style="margin-left:auto;font-size:11px;color:#185FA5">
    {"Ungroup" if grouped else "Group by action"}</a>
</div>

<div id="lt-group-note" style="display:none;font-size:11px;color:#898781;
     margin:-4px 0 8px">
  Sorted — action grouping dissolved.
  <a href="javascript:location.reload()" style="color:#185FA5">restore groups</a>
</div>

{card("", table, pad="6px 10px 10px")}

<div style="font-size:10px;color:#898781;margin-top:-6px">
  Click a header to sort, drag one to reorder; both persist in this browser
  (<a href="#" id="lt-reset-cols" style="color:#185FA5">reset columns</a>).
  S1–S4 are a fixed ladder — 8 EMA, 21 EMA, 50 MA, 200 MA — showing how far
  price sits above or below each, so a column reads down the page. Green
  means the level is holding underfoot, red that it was lost and is now
  overhead; bold means price is sitting on it.
  <br>
  LQuality is this engine's own 100-point score and is deliberately not the
  same number as the Screener's Quality — they are calibrated for different
  questions. Valuation prices most companies by reverse DCF (what growth the
  current price already requires) and falls back to a sector multiple for
  financials, REITs and anything without positive free cash flow; the method
  is shown per row. Moat and capital-allocation factors are quantitative
  proxies, marked ⚠ where the evidence is thinner than the weight.
</div>
"""
    return body, _TABLE_JS
