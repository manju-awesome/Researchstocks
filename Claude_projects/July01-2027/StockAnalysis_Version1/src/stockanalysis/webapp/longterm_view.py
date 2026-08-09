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
    "THESIS BROKEN": ("#FCEBEB", "#791F1F"),
    "OWN / WAIT FOR PRICE": ("#FAEEDA", "#633806"),
    "OWN / WAIT FOR TREND": ("#FAEEDA", "#633806"),
    "OWN / WAIT FOR ENTRY": ("#FAEEDA", "#633806"),
}

_INVEST_STYLE = {"CORE": "good", "OWN": "good", "WATCHLIST": "watch",
                 "REJECT": "bad"}
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
                 "RESEARCH": "Research", "AVOID": "Avoid",
                 "THESIS BROKEN": "Thesis broken",
                 "OWN / WAIT FOR PRICE": "Own / wait for price",
                 "OWN / WAIT FOR TREND": "Own / wait for trend",
                 "OWN / WAIT FOR ENTRY": "Own / wait for entry"}

# Stage is what the Pullback column shows now. The zone answers "is price on
# a tracked level" and collapses a 22%-below-the-50-MA correction to "—";
# the stage names it.
_STAGE_SHORT = {"AT_HIGHS": "At highs", "STAGE1_EMA": "S1 · 8/21 EMA",
                "STAGE2_50MA": "S2 · 50 MA", "STAGE3_DEEP": "S3 · deep",
                "STAGE4_UNCONFIRMED": "Below 200 MA · unconfirmed",
                "STAGE4_BREAKDOWN": "S4 · breakdown",
                "EXTENDED": "Extended"}
# Ordered so sorting descending puts the shallow, tradeable pullbacks first.
_STAGE_RANK = {"STAGE2_50MA": 6, "STAGE1_EMA": 5, "STAGE3_DEEP": 4,
               "AT_HIGHS": 3, "EXTENDED": 2, "STAGE4_UNCONFIRMED": 1,
               "STAGE4_BREAKDOWN": 0}

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


def _levels_panel(r):
    """The moving-average reference prices, moved out of the table.

    Every level with its price and signed distance, plus which of them are
    clustered around the current price. Green when price is above the level
    (support underfoot), red when below it (resistance overhead).
    """
    p = r["pullback"]
    by, cluster = p.get("by_level") or {}, p.get("ma_cluster") or {}
    near = {l["name"] for l in cluster.get("levels", [])}
    rows = []
    for key, label in (("8EMA", "8 EMA"), ("21EMA", "21 EMA"),
                       ("50MA", "50 MA"), ("200MA", "200 MA"),
                       ("Prior_Breakout_Level", "prior breakout")):
        lv = by.get(key) or {}
        dist, price = lv.get("distance_pct"), lv.get("price")
        if price is None and dist is None:
            continue
        colour = "#898781" if dist is None else (
            "#0F6E56" if lv.get("held") else "#A32D2D")
        rows.append(
            f'<tr><td style="padding:3px 12px 3px 0;white-space:nowrap">'
            f'{esc(label)}'
            + (' <span style="color:#8a6d1a" title="inside the cluster">◆</span>'
               if label in near else '')
            + f'</td>'
            f'<td style="padding:3px 12px 3px 0;text-align:right">'
            f'{f"${price:,.2f}" if price is not None else "—"}</td>'
            f'<td style="padding:3px 0;text-align:right;color:{colour};'
            f'font-weight:600">{f"{dist:+.1f}%" if dist is not None else "—"}'
            f'</td></tr>')
    head = ""
    if cluster.get("count", 0) >= 2:
        head = (f'<div style="font-size:11px;margin-bottom:6px">'
                f'{esc(cluster["label"])} — {cluster["count"]} levels within '
                f'{cluster.get("within_pct", 2):.0f}% of the price'
                + (f', spanning {cluster["span_pct"]:.1f}%'
                   if cluster.get("span_pct") is not None else "")
                + '. A coil says a move resolves here, not which way.</div>')
    return head + (f'<table style="border-collapse:collapse;font-size:11px">'
                   f'{"".join(rows)}</table>')


def _scenarios_panel(r):
    """The buy triggers as a decision tree rather than one price.

    A quality name can become buyable three different ways — the trend
    repairs, support confirms, or the price comes to the valuation — and
    they are alternatives, not steps. Presenting only the last of them
    ("wait for $434.93") describes the least likely of the three as the
    only one.
    """
    groups = {"A": ("Technical recovery", []), "B": ("Support confirmation", []),
              "C": ("Valuation reset", []), "D": ("Deep value", []),
              "X": ("Invalidation", []), "": ("Other", [])}
    for t in r.get("triggers") or []:
        key = t[0] if t[:2] in ("A ", "B ", "C ", "D ") else (
            "X" if t.lower().startswith("invalidation") else "")
        body = t[4:] if key in ("A", "B", "C", "D") else t
        groups.setdefault(key, (key, []))[1].append(body)
    out = []
    for key in ("A", "B", "C", "D", "X", ""):
        label, items = groups.get(key, ("", []))
        if not items:
            continue
        colour = "#A32D2D" if key == "X" else "#0F6E56"
        mark = "✕" if key == "X" else (key or "→")
        out.append(
            f'<div style="margin-bottom:8px">'
            f'<div style="font-size:10px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:{colour};font-weight:700;'
            f'margin-bottom:2px">{esc(mark)} {esc(label)}</div>'
            + "".join(f'<div style="font-size:11px;color:#444441;'
                      f'margin-left:12px">{esc(i)}</div>' for i in items)
            + '</div>')
    return "".join(out) or empty("no triggers computed")


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
        + (f'{e["tranche_pct"]}% of target' if e["tranche_pct"] else "—")
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

        _entries_panel(r),
    ]
    grid = (
        '<div style="display:grid;grid-template-columns:1fr;gap:14px;'
        'margin-top:12px">'
        f'<div>{card("Business quality — LQuality", _quality_panel(q), "💎")}</div>'
        f'<div>{card("Valuation", _valuation_panel(v), "⚖️")}</div>'
        f'<div>{card("Long-term trend", _trend_panel(t), "📈")}</div>'
        f'<div>{card("Moving-average levels", _levels_panel(r), "📐")}</div>'
        f'<div>{card("What would change it", _scenarios_panel(r), "🔀")}</div>'
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
_RULE_JS = r"""
(function () {
  // The operator list and the value widget both depend on the field's kind,
  // so the form has to rebuild them when the field changes. Everything else
  // on this page is a link; this is the one control that cannot be.
  var meta = window.LT_FIELDS || {};
  var field = document.getElementById('lt-rule-field');
  var opSel = document.getElementById('lt-rule-op');
  var wrap = document.getElementById('lt-rule-valuewrap');
  var hint = document.getElementById('lt-rule-hint');
  if (!field || !opSel || !wrap) return;

  var OP_LABEL = { gte: 'at least', gt: 'more than', lte: 'at most',
                   lt: 'less than', eq: 'is', ne: 'is not',
                   between: 'between', within: 'within', in: 'is one of' };
  var INPUT = 'padding:7px 9px;font-size:12px;border:0.5px solid #e1e0d9;' +
              'border-radius:7px;width:110px';

  function rebuild() {
    var spec = meta[field.value];
    if (!spec) return;
    opSel.innerHTML = (spec.ops || []).map(function (o) {
      return '<option value="' + o + '">' + (OP_LABEL[o] || o) + '</option>';
    }).join('');
    hint.textContent = spec.hint || '';
    drawValue();
  }

  function drawValue() {
    var spec = meta[field.value];
    if (!spec) return;
    var op = opSel.value;
    if (spec.kind === 'bool') {
      wrap.innerHTML = '<select name="_value" style="' + INPUT + '">' +
        '<option value="true">Yes</option><option value="false">No</option></select>';
    } else if (spec.kind === 'enum') {
      wrap.innerHTML = '<select name="_value" style="' + INPUT + ';width:auto">' +
        (spec.values || []).map(function (v) {
          return '<option value="' + v + '">' + v + '</option>';
        }).join('') + '</select>';
    } else if (op === 'between') {
      wrap.innerHTML =
        '<input name="_value" type="number" step="any" placeholder="from" style="' + INPUT + ';width:78px">' +
        ' <input name="_value2" type="number" step="any" placeholder="to" style="' + INPUT + ';width:78px">';
    } else {
      wrap.innerHTML = '<input name="_value" type="number" step="any" ' +
        'placeholder="' + (spec.unit || 'value') + '" style="' + INPUT + '">';
    }
  }

  field.addEventListener('change', rebuild);
  opSel.addEventListener('change', drawValue);
  rebuild();

  // Assemble the three inputs into one `rule` param on submit, so the URL
  // carries "lquality:gte:85" rather than three loose fields the server
  // would have to recombine.
  field.form.addEventListener('submit', function (e) {
    var spec = meta[field.value];
    if (!spec) return;
    var v = wrap.querySelector('[name=_value]');
    var v2 = wrap.querySelector('[name=_value2]');
    var value = v ? v.value : '';
    if (value === '' || value === null) { e.preventDefault(); return; }
    if (opSel.value === 'between') {
      if (!v2 || v2.value === '') { e.preventDefault(); return; }
      value = value + ',' + v2.value;
    }
    var hiddenRule = document.createElement('input');
    hiddenRule.type = 'hidden';
    hiddenRule.name = 'rule';
    hiddenRule.value = field.value + ':' + opSel.value + ':' + value;
    field.form.appendChild(hiddenRule);
    // The three builder inputs are for the human, not the URL.
    field.removeAttribute('name');
    opSel.removeAttribute('name');
    if (v) v.removeAttribute('name');
    if (v2) v2.removeAttribute('name');
  });
})();
"""

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

  // Sort keys, highest priority first: [{key, dir}, ...]. Multi-column
  // because the useful questions here are compound — "best businesses, and
  // among those the ones I can act on" is LQuality then Action, and neither
  // column answers it alone.
  var sortKeys = [];

  function compare(a, b, key, dir) {
    var th = head.querySelector('th[data-col="' + key + '"]');
    var numeric = th && th.dataset.type === 'num';
    var ta = cellOf(a.main, key), tb2 = cellOf(b.main, key);
    var ra = ta ? ta.dataset.sort : '', rb = tb2 ? tb2.dataset.sort : '';
    var blankA = (ra === undefined || ra === '');
    var blankB = (rb === undefined || rb === '');
    var va = numeric ? parseFloat(ra) : String(ra || '').toUpperCase();
    var vb = numeric ? parseFloat(rb) : String(rb || '').toUpperCase();
    if (numeric) {
      if (isNaN(va)) blankA = true;
      if (isNaN(vb)) blankB = true;
    }
    // Blanks last in BOTH directions: "no value" is not an extreme value.
    if (blankA !== blankB) return blankA ? 1 : -1;
    if (blankA) return 0;
    if (va < vb) return dir === 'asc' ? -1 : 1;
    if (va > vb) return dir === 'asc' ? 1 : -1;
    return 0;
  }

  function applySort() {
    if (!sortKeys.length) return;
    var groups = pairs();
    groups.forEach(function (g, i) { g._i = i; });   // stable tiebreak
    groups.sort(function (a, b) {
      for (var i = 0; i < sortKeys.length; i++) {
        var r = compare(a, b, sortKeys[i].key, sortKeys[i].dir);
        if (r !== 0) return r;
      }
      return a._i - b._i;
    });
    var frag = document.createDocumentFragment();
    groups.forEach(function (g) {
      frag.appendChild(g.main);
      g.rest.forEach(function (r) { frag.appendChild(r); });
    });
    body.appendChild(frag);
    markSort();
  }

  function markSort() {
    var multi = sortKeys.length > 1;
    Array.prototype.forEach.call(head.cells, function (th) {
      var arrow = th.querySelector('.lt-arrow');
      if (!arrow) return;
      var at = -1;
      for (var i = 0; i < sortKeys.length; i++) {
        if (sortKeys[i].key === th.dataset.col) { at = i; break; }
      }
      if (at === -1) {
        arrow.textContent = '';
        th.style.color = '#898781';
        th.dataset.dir = '';
      } else {
        // The priority number only appears once it means something.
        arrow.textContent = (sortKeys[at].dir === 'asc' ? ' ▲' : ' ▼')
          + (multi ? String(at + 1) : '');
        th.style.color = '#0b0b0b';
        th.dataset.dir = sortKeys[at].dir;
      }
    });
    var note = document.getElementById('lt-sort-note');
    if (note) {
      note.style.display = multi ? '' : 'none';
      if (multi) {
        note.textContent = 'Sorted by ' + sortKeys.map(function (k, i) {
          var th = head.querySelector('th[data-col="' + k.key + '"]');
          var label = th ? th.textContent.replace(/[▲▼0-9]/g, '').trim() : k.key;
          return (i + 1) + '. ' + label + ' ' + (k.dir === 'asc' ? 'asc' : 'desc');
        }).join(', ') + ' — shift-click a header to add another, click to reset.';
      }
    }
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
    th.addEventListener('click', function (e) {
      var key = th.dataset.col;
      // Numbers open on descending (best first); text opens ascending.
      var opening = th.dataset.type === 'num' ? 'desc' : 'asc';
      var at = -1;
      for (var i = 0; i < sortKeys.length; i++) {
        if (sortKeys[i].key === key) { at = i; break; }
      }
      if (e.shiftKey) {
        // Add as a further tiebreak, or flip it if already in the list.
        if (at === -1) sortKeys.push({ key: key, dir: opening });
        else sortKeys[at].dir = sortKeys[at].dir === 'asc' ? 'desc' : 'asc';
      } else if (at === 0 && sortKeys.length === 1) {
        sortKeys = [{ key: key, dir: sortKeys[0].dir === 'asc' ? 'desc' : 'asc' }];
      } else {
        sortKeys = [{ key: key, dir: opening }];
      }
      applySort();
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


def _support_confluence_cell(conf, cluster=None):
    """Support as two readings that are allowed to disagree.

    The cluster says how tightly the levels are wound around price; the
    count says how many are actually holding it up. Meta has five levels
    inside a 1.9% band and only two of them beneath the price — a strong
    coil at a weak support reading, and both are true. Showing only the
    second describes a decision point as an absence.
    """
    n = conf.get("agreeing", len(conf.get("hits", [])))
    possible = conf.get("possible", 6)
    score = conf.get("score", 0)
    cluster = cluster or {}
    count = cluster.get("count") or 0
    if count >= 2:
        colour = "#0F6E56" if count >= 3 else "#8a6d1a"
        names = ", ".join(l["name"] for l in cluster.get("levels", []))
        head = (f'<span style="color:{colour};font-weight:700" '
                f'title="{esc(names)}">{esc(cluster.get("label", ""))}</span>')
        sub = (f'{count} within {cluster.get("within_pct", 2):.0f}%'
               + (f', span {cluster["span_pct"]:.1f}%'
                  if cluster.get("span_pct") is not None else "")
               + f' · {n} of {possible} holding')
    else:
        colour = "#0b0b0b" if n >= 3 else "#8a6d1a" if n >= 2 else "#A32D2D"
        head = (f'<span style="color:{colour};font-weight:700">'
                f'{n} of {possible}</span>')
        sub = f'{esc(conf.get("label", ""))} · {score}/100'
    return (f'{head}<div style="font-size:10px;color:#898781;'
            f'white-space:nowrap">{sub}</div>',
            # Sorted on levels actually holding, cluster size as tiebreak.
            n * 1000 + count * 10 + min(score, 9))


def _status_cell(view, style_map):
    """A status badge with its score underneath — the company verdict and
    the timing verdict shown as two separate answers."""
    status = view.get("status")
    if not status:
        return '<span style="color:#898781">—</span>', None
    rank = {"CORE": 4, "OWN": 3, "WATCHLIST": 2, "REJECT": 1}.get(status, 0)
    score = view.get("score")
    return (f'{badge(status.title(), style_map.get(status, "muted"), "small")}'
            f'<div style="font-size:10px;color:#898781" '
            f'title="{esc(view.get("why") or "")}">'
            f'{score if score is not None else "—"}/100</div>',
            rank * 1000 + (score or 0))


def _fair_value_line(v):
    """The modelled value, labelled as a reference rather than a target.

    The peer method prices a company against its sector; it does not say
    what the business is worth, and a fair value shown bare invites being
    read as a buy price. Meta's $434.93 is "where the sector multiple puts
    it", which is a reason to wait and not a limit order.
    """
    fair = v.get("fair_value")
    conf = f'{v.get("confidence_icon", "")} {(v.get("confidence") or "").title()}'
    if fair is None:
        implied = v.get("implied_growth_pct")
        extra = (f'needs {implied:.0f}% growth' if implied is not None else "")
        return (f'<div style="font-size:10px;color:#898781" '
                f'title="{esc(v.get("confidence_note") or "")}">'
                f'{esc(conf.strip())}{" · " + extra if extra else ""}</div>')
    upside = v.get("upside_pct")
    return (f'<div style="font-size:10px;color:#898781" '
            f'title="Reference value, not a price target — '
            f'{esc(v.get("confidence_note") or "")}">'
            f'ref ${fair:,.2f}'
            + (f' ({upside:+.0f}%)' if upside is not None else "")
            + f' · {esc(conf.strip())}</div>')


def _resistance_cell(pullback):
    """The first price overhead, and whether the market has actually turned
    down from it.

    Same tested/derived split as the support side, and the 52-week high rung
    matters: a stock in a clean uptrend has every moving average below it, so
    without that fallback this column would be blank for precisely the names
    worth owning. 311 of 545 rows have a tested R1, 100 fall back to a moving
    average and 134 to the 52-week high.
    """
    rz = (pullback or {}).get("resistance") or {}
    price, dist = rz.get("price"), rz.get("distance_pct")
    if price is None:
        return '<span style="color:#898781">—</span>', None
    touches = rz.get("touches")
    if rz.get("actual_resistance"):
        style = "color:#A32D2D;font-weight:700"
        sub = f"{touches:.0f} touches" if touches else "tested"
    else:
        style = "color:#898781;font-style:italic"
        sub = f'{rz.get("label") or "level"} · derived'
    dist_txt = (f' <span style="color:#898781">{dist:+.1f}%</span>'
                if dist is not None else "")
    return (f'<span style="{style};white-space:nowrap" '
            f'title="{esc(rz.get("note") or "")}">${price:,.2f}</span>{dist_txt}'
            f'<div style="font-size:10px;color:#898781;white-space:nowrap">'
            f'{esc(sub)}</div>', dist)


# (key, header, alignment, sort type). Order here is the DEFAULT order; the
# user can drag columns and the choice persists in localStorage.
#
# The four moving-average distance columns moved into the reasoning panel.
# They are reference prices rather than judgments — useful once a name is
# worth looking at, and four columns of noise before that. What replaced
# them is the pair the page exists to separate: the company verdict and the
# timing verdict, which routinely disagree.
_COLUMNS = (
    ("ticker", "Ticker", "left", "text"),
    ("price", "Price", "right", "num"),
    ("lquality", "LQuality", "left", "num"),
    ("valuation", "Valuation", "left", "num"),
    ("trend", "Trend", "center", "num"),
    ("pullback", "Pullback", "left", "num"),
    ("support", "Support", "left", "num"),
    ("buyzone", "S1 \u00b7 Support", "right", "num"),
    ("resistance", "R1 \u00b7 Resistance", "right", "num"),
    ("rs", "RS", "center", "num"),
    ("market", "Market", "center", "text"),
    ("investment", "Investment", "left", "num"),
    ("entry_score", "Entry", "left", "num"),
    ("action", "Action", "left", "num"),
)
_HEADERS = tuple(c[1] for c in _COLUMNS)

# Sort keys for columns whose display is a symbol or a label. Ranked so
# "descending" means "better" everywhere — otherwise the first click on
# Trend puts the broken ones on top.
_TREND_RANK = {"CONFIRMED": 4, "PARTIAL": 3, "RECOVERING": 2,
               "IMPAIRED": 1, "BROKEN": 0}
_BAND_RANK = {"UNDERVALUED": 2, "FAIR": 1, "OVERVALUED": 0}
_ACTION_ORDER = ("BUY NOW", "BUY ON CONFIRMATION", "BUY ON 8/21 EMA",
                 "BUY ON 50 MA", "BUY ON BREAKOUT RETEST", "BUY ON 200 MA",
                 "BUY ON SUPPORT", "DEEP PULLBACK \u2014 WAIT FOR SUPPORT",
                 "OWN / WAIT FOR PRICE", "OWN / WAIT FOR TREND",
                 "OWN / WAIT FOR ENTRY",
                 "WATCH", "WAIT", "RESEARCH", "AVOID", "THESIS BROKEN")
_ACTION_RANK = {a: len(_ACTION_ORDER) - i for i, a in enumerate(_ACTION_ORDER)}


def _cells(r):
    """(column key -> (html, sort_value)) for one result row."""
    q, v, p, conf, rs = (r["quality"], r["valuation"], r["pullback"],
                         r["confluence"], r["rs"])
    # The engine's own tri-state icon: 🟢 confirmed / 🟡 partial / 🔴 broken.
    # A grey "unknown" dot read as "no data" when the real meaning is
    # "structure holds, slopes unmeasured".
    trend_mark = r["trend"].get("icon") or "⚪"
    trend_state = r["trend"].get("state")
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
             f'{_fair_value_line(v)}'
             if v["band"] else '<span style="color:#898781">—</span>'),
            _BAND_RANK.get(v["band"])),
        "trend": (f'<span title="{esc(r["trend"].get("summary") or "")}">'
                  f'{trend_mark}</span>',
                  _TREND_RANK.get(trend_state)),
        "pullback": (
            f'{p.get("stage_icon", "")} '
            f'{esc(_STAGE_SHORT.get(p.get("stage"), _ZONE_SHORT.get(p["zone"], p["zone"])))}',
            _STAGE_RANK.get(p.get("stage"))),
        "price": (f'<strong>${r["price"]:,.2f}</strong>' if r.get("price")
                  else '<span style="color:#898781">—</span>', r.get("price")),
        "buyzone": _buyzone_cell(p),
        "resistance": _resistance_cell(p),
        "support": _support_confluence_cell(conf, r.get("ma_cluster") or {}),
        "investment": _status_cell(r.get("investment") or {}, _INVEST_STYLE),
        "entry_score": (
            f'<strong>{(r.get("entry") or {}).get("score", "—")}</strong>'
            f'<div style="font-size:10px;color:#898781">of 100</div>',
            (r.get("entry") or {}).get("score")),
        "rs": (rs_mark, rs["score"]),
        "market": (market, r["regime"]),
        "lt": (f'<strong>{r["lt_score"] if r["lt_score"] is not None else "—"}</strong>',
               r["lt_score"]),
        "action": (
            _action_pill(r["action"], r["icon"])
            + (f'<div style="font-size:10px;color:#898781">'
               f'{r["tranche_pct"]}% of target</div>'
               if r.get("tranche_pct") else ""),
            _ACTION_RANK.get(r["action"])),
    }
    return out


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


# ─────────────────────────────────────────────────────────────────────────────
# RULE BUILDER — screener rules over the engine's own columns
# ─────────────────────────────────────────────────────────────────────────────

def _list_options(active: str) -> str:
    """The saved watchlists, most-used first.

    Ordered by hand rather than alphabetically because "daytrade" and
    "watchlist" are the two anyone reaches for, and burying them between
    "AI: Optics" and "Dividend" makes the picker a scrolling exercise.
    """
    from . import api
    lists = api.longterm_lists()
    preferred = [n for n in ("watchlist", "daytrade", "Longterm", "AI",
                             "Dividend") if n in lists]
    rest = sorted(n for n in lists if n not in preferred)
    out = ['<option value="">All tickers</option>']
    for name in preferred + rest:
        sel = " selected" if name == active else ""
        out.append(f'<option value="{esc(name)}"{sel}>{esc(name)} '
                   f'({len(lists[name])})</option>')
    return "".join(out)


def _preset_bar(link, active_rules, needs_rescan, counts):
    """The screens a manager actually runs, grouped by the question asked.

    Ordered "what to own" -> "when to buy" -> "what would stop me" because
    that is the order the work happens in, and it is the framework's own
    hierarchy. A preset list organised by field type would scatter it.
    """
    from stockanalysis.core.longterm import screen as LS
    current = set(active_rules)
    sections = []
    for group in LS.PRESET_GROUPS:
        items = [p for p in LS.PRESETS if p["group"] == group]
        if not items:
            continue
        pills = []
        for preset in items:
            on = current == set(preset["rules"])
            # A preset whose inputs the library does not carry yet returns
            # nothing, and would be indistinguishable from a broken one
            # without saying so.
            stale = preset.get("needs_statements") and needs_rescan
            bg, fg = ("#0b0b0b", "white") if on else (
                ("#F7F4EC", "#a09b8c") if stale else ("#F1EFE8", "#444441"))
            note = ("needs a scan for statement data — "
                    "the reverse DCF has no inputs yet" if stale
                    else preset["desc"])
            # Counted live against the universe now on screen, never stored
            # on the preset. A recorded count is a claim about a moving
            # target: splitting one pullback stage in two silently took
            # Fallen Quality from 10 matches to 0 while it still advertised
            # 10, and clicking it returned an empty table.
            n = counts.get(preset["key"])
            count = "" if n is None else f"{n}"
            pills.append(
                f'<a href="{esc(link(rule=[] if on else list(preset["rules"]), action=""))}" '
                f'title="{esc(note)}" style="background:{bg};color:{fg};'
                f'font-size:11px;font-weight:600;padding:5px 10px;'
                f'border-radius:6px;text-decoration:none;white-space:nowrap;'
                f'display:inline-flex;gap:5px;align-items:center">'
                f'{preset["icon"]} {esc(preset["name"])}'
                + (f'<span style="font-weight:400;opacity:.65">'
                   f'{esc("needs scan" if stale else count)}</span>'
                   if (count or stale) else "")
                + '</a>')
        sections.append(
            f'<div style="display:flex;gap:6px;flex-wrap:wrap;'
            f'align-items:center;margin-bottom:6px">'
            f'<span style="font-size:10px;text-transform:uppercase;'
            f'letter-spacing:.06em;color:#898781;min-width:112px">'
            f'{esc(group)}</span>{"".join(pills)}</div>')
    return (f'<div style="background:white;border:0.5px solid #e1e0d9;'
            f'border-radius:12px;padding:12px 14px;margin-bottom:14px">'
            f'{"".join(sections)}</div>')


def _rule_pills(conds, link):
    """Active rules, each removable. Rules live in the URL, so a filtered
    view is a link and the back button undoes one rule at a time."""
    from stockanalysis.core.longterm import screen as LS
    if not conds:
        return ""
    out = []
    for i, c in enumerate(conds):
        rest = [_rule_text(x) for j, x in enumerate(conds) if j != i]
        out.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'background:#E6F1FB;color:#0C447C;font-size:11px;font-weight:600;'
            f'padding:4px 8px;border-radius:6px">{esc(LS.describe(c))}'
            f'<a href="{esc(link(rule=rest))}" style="color:#0C447C;'
            f'text-decoration:none;font-weight:700" title="Remove">×</a></span>')
    return "".join(out)


def _num_text(v):
    """85.0 -> "85". Values arrive as floats from the parser and go back into
    the URL on every re-render, so without this a rule picks up a trailing
    ".0" the moment it round-trips through a pill."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _rule_text(cond) -> str:
    if isinstance(cond.value, bool):
        value = "true" if cond.value else "false"
    elif cond.op == "between":
        value = f"{_num_text(cond.value)},{_num_text(cond.value2)}"
    else:
        value = _num_text(cond.value)
    return f"{cond.field}:{cond.op}:{value}"


def _rule_builder(conds, rule_op, link, stats, n_matched, n_total,
                  search_q=""):
    """Field -> operator -> value, as a plain GET form.

    The operator list and the value widget both depend on the field's kind,
    which is the only reason there is any JavaScript here: everything else on
    this page is a link.
    """
    import json as _json
    from stockanalysis.core.longterm import screen as LS

    from stockanalysis.core.screener import OPS_FOR_KIND

    meta = {f.key: {"kind": f.kind, "ops": list(OPS_FOR_KIND.get(f.kind, ())),
                    "values": list(f.values), "unit": f.unit,
                    "hint": f.hint, "label": f.label}
            for f in LS.LONGTERM_FIELDS}

    options = []
    for group in LS.FIELD_GROUPS:
        items = [f for f in LS.LONGTERM_FIELDS if f.group == group]
        if not items:
            continue
        options.append(f'<optgroup label="{esc(group)}">' + "".join(
            f'<option value="{esc(f.key)}">{esc(f.label)}</option>'
            for f in items) + '</optgroup>')

    hidden = "".join(
        f'<input type="hidden" name="rule" value="{esc(_rule_text(c))}">'
        for c in conds)

    # Per-rule diagnosis. "0 matches" is a dead end; "0 matches, and 431 rows
    # had no data for this rule" is an answer.
    # Per-rule diagnosis. "0 matches" is a dead end; naming which rule is
    # binding, and what dropping it would return, is an answer. `alone` and
    # `without` differ usefully: a rule can look permissive on its own and
    # still be the one killing the screen, through how it overlaps the rest.
    diag = ""
    if conds and stats:
        # Exactly one rule gets the marker. Flagging every rule whose
        # removal helps marks all of them on a tight screen, which is the
        # same as marking none.
        loosest = None
        if len(conds) > 1:
            ranked = [st for st in stats if st.get("without") is not None]
            if ranked:
                top = max(ranked, key=lambda st: st["without"])
                if top["without"] > max(n_matched * 2, n_matched + 5):
                    loosest = top.get("index")

        lines = []
        for st in stats:
            label = st.get("label") or st.get("field")
            without = st.get("without")
            binding = loosest is not None and st.get("index") == loosest
            lines.append(
                f'<li style="margin:2px 0">'
                f'{"<strong>" if binding else ""}{esc(str(label))}'
                f'{"</strong>" if binding else ""} — '
                f'{st.get("alone", 0)} on its own'
                + (f', {st["missing"]} with no data' if st.get("missing")
                   else "")
                + (f' · drop it and {without} match' if len(conds) > 1
                   and without is not None else "")
                + (' ← the binding one' if binding else "") + '</li>')
        diag = (f'<div style="font-size:11px;color:#898781;margin-top:8px">'
                f'<strong>{n_matched}</strong> of {n_total} match'
                f'<ul style="margin:4px 0 0;padding-left:16px;list-style:none">'
                f'{"".join(lines)}</ul></div>')

    toggle = ""
    if len(conds) > 1:
        other = "OR" if rule_op == "AND" else "AND"
        toggle = (f'<a href="{esc(link(rule_op=other))}" '
                  f'style="font-size:11px;color:#185FA5;margin-left:6px">'
                  f'match {esc(other.lower())} instead</a>')

    return f"""
<div style="background:white;border:0.5px solid #e1e0d9;border-radius:12px;
            padding:12px 14px;margin-bottom:14px">
  <form method="get" action="/longterm"
        style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    {hidden}
    <input type="hidden" name="q" value="{esc(search_q or '')}">
    <input type="hidden" name="rule_op" value="{esc(rule_op)}">
    <span style="font-size:11px;color:#898781;text-transform:uppercase;
                 letter-spacing:.06em">Add rule</span>
    <select name="_field" id="lt-rule-field"
            style="padding:7px 9px;font-size:12px;border:0.5px solid #e1e0d9;
                   border-radius:7px">{"".join(options)}</select>
    <select name="_op" id="lt-rule-op"
            style="padding:7px 9px;font-size:12px;border:0.5px solid #e1e0d9;
                   border-radius:7px"></select>
    <span id="lt-rule-valuewrap"></span>
    <button type="submit" class="btn" style="padding:7px 14px">Add</button>
    <span id="lt-rule-hint" style="font-size:11px;color:#898781"></span>
  </form>
  <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;
              margin-top:{'10px' if conds else '0'}">
    {_rule_pills(conds, link)}{toggle}
    {f'<a href="{esc(link(rule=[]))}" style="font-size:11px;color:#185FA5;margin-left:auto">Clear rules</a>' if conds else ''}
  </div>
  {diag}
</div>
<script>window.LT_FIELDS = {_json.dumps(meta)};</script>"""


def longterm_page(query: dict | None = None) -> tuple[str, str]:
    from . import api

    query = query or {}
    action_filter = (query.get("action") or [""])[0].strip()
    regime_override = (query.get("regime") or [""])[0].strip() or None
    raw_query = (query.get("q") or [""])[0]
    list_name = (query.get("list") or [""])[0].strip()
    rule_texts = [r for r in (query.get("rule") or []) if r.strip()]
    rule_op = ((query.get("rule_op") or ["AND"])[0].strip().upper()
               or "AND")
    wanted = parse_tickers(raw_query)
    # Default FIRST, clamp second. Clamping an absent value ran
    # max(10, min(500, 0)) -> 10, so `or DEFAULT_LIMIT` could never fire and
    # the page quietly showed ten rows instead of sixty.
    raw_limit = (query.get("limit") or [""])[0].strip()
    try:
        limit = int(raw_limit) if raw_limit else DEFAULT_LIMIT
    except ValueError:
        limit = DEFAULT_LIMIT
    limit = max(10, min(500, limit))

    data = api.longterm(regime_override)
    rows, cov = data["rows"], data["coverage"]

    def link(**params):
        """A URL carrying the page's whole state, so no control silently
        discards another's — clicking a chip while a search is active used
        to drop the search, and now must not drop the rules either."""
        state = {"q": raw_query.strip(), "list": list_name,
                 "action": action_filter,
                 "regime": regime_override or "",
                 "rule": list(rule_texts),
                 "rule_op": "" if rule_op == "AND" else rule_op}
        for key, value in params.items():
            state[key] = value if isinstance(value, list) else (
                "" if value is None else str(value))
        kept = {k: v for k, v in state.items() if v}
        # doseq: `rule` repeats once per condition.
        return "/longterm" + (f"?{urlencode(kept, doseq=True)}" if kept else "")

    # ── ticker search ───────────────────────────────────────────────────────
    # Narrows the universe before anything else looks at it, so the chips
    # below count within the search rather than across the whole library.
    # Counting globally would offer "Avoid 347" next to three searched
    # tickers and return an empty table when clicked.
    by_ticker = {r["ticker"]: r for r in rows}

    # A saved list narrows the universe before anything else looks at it.
    # Tickers on the list that no scan has covered are NAMED rather than
    # quietly dropped — the same rule the ticker search follows, and the
    # reason a 25-name list showing 19 rows is legible instead of alarming.
    lists = api.longterm_lists()
    list_missing = []
    if list_name and list_name in lists:
        members = lists[list_name]
        rows = [by_ticker[t] for t in members if t in by_ticker]
        list_missing = [t for t in members if t not in by_ticker]
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

    # Rules run after the ticker search and before the action chips, so the
    # chip counts describe what the rules actually left.
    from stockanalysis.core.longterm import screen as LS
    # Counted over the search-narrowed universe, which is what clicking a
    # preset will actually screen — presets replace the rules but keep `q`.
    preset_counts = LS.preset_counts(base)
    before_rules = len(base)
    base, rule_conds, rule_stats = LS.apply_rules(base, rule_texts, rule_op)

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
  <select name="list" style="padding:9px 10px;font-size:12px;
          border:0.5px solid #e1e0d9;border-radius:8px;max-width:220px">
    {_list_options(list_name)}
  </select>
  <button type="submit" class="btn" style="padding:9px 16px">Search</button>
  {f'<a href="{esc(link(q="", action="", limit=""))}" '
   f'style="font-size:12px;color:#185FA5">Clear</a>' if wanted else ''}
</form>"""

    notfound = ""
    if list_missing:
        shown = ", ".join(list_missing[:12])
        notfound += (
            f'<div style="background:#F1EFE8;border-radius:8px;padding:9px 12px;'
            f'margin-bottom:12px;font-size:12px;color:#444441">'
            f'<strong>{esc(list_name)}</strong> — {len(list_missing)} of its '
            f'tickers have no research page yet: {esc(shown)}'
            + ("…" if len(list_missing) > 12 else "")
            + f'. Scan them from the '
              f'<a href="/scanner" style="color:#185FA5">Scanner</a> page.</div>')
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
    # An explicit search or a chosen list is never truncated — asking for
    # eight tickers, or for "daytrade", and being shown the first six
    # silently would be worse than a long page.
    shown = shown if (wanted or list_name) else shown[:limit]

    if shown:
        # One result means the reasoning IS the answer, so don't make the
        # user click again to reach it.
        expand = len(shown) == 1
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
{_preset_bar(link, rule_texts, cov["needs_rescan"], preset_counts)}
{_rule_builder(rule_conds, rule_op, link, rule_stats, len(base),
               before_rules, raw_query)}

<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;
            margin-bottom:14px">
  {"".join(chips)}
</div>

<div id="lt-sort-note" style="display:none;font-size:11px;color:#898781;
     margin:-4px 0 8px"></div>

{card("", table, pad="6px 10px 10px")}

<div style="font-size:10px;color:#898781;margin-top:-6px">
  Click a header to sort; <strong>shift-click a second header</strong> to
  sort by both — e.g. LQuality then Action. Drag a header to reorder;
  column order persists in this browser
  (<a href="#" id="lt-reset-cols" style="color:#185FA5">reset columns</a>).
  S1 · Support is the price to work an order at and R1 · Resistance the
  first thing overhead; both are green/red and bold when the market has
  actually traded there, and grey italic when the figure is only the nearest
  moving average or the 52-week high — a derived level, not one anyone has
  defended. The four MA columns show how far price sits above or below each,
  green when the level is holding underfoot and red when it was lost.
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
    return body, _TABLE_JS + _RULE_JS
