"""
views.py
========
Shared HTML layout and components. Pure string building — no HTTP here.

Colour system, reused everywhere so a status always reads the same way:
    green  = strong / verified / good        #0F6E56 on #E1F5EE
    yellow = watch / caution / unverified    #633806 on #FAEEDA
    red    = reject / danger / hard stop     #791F1F on #FCEBEB
    blue   = informational                   #0C447C on #E6F1FB
    grey   = unknown / not assessed          #444441 on #F1EFE8

The one visual rule that carries meaning rather than decoration: **every
value rendered through `claim_value` shows its confidence badge**. On a page
this dense, if evidence and assertion look alike the reader stops
distinguishing them within about thirty seconds, and then the whole
claim-tracking apparatus underneath is decorative. The badge is small and
always present, so "seller says" versus "verified" is legible at a glance
without reading.
"""

from __future__ import annotations

import html as _html
import json

from findfarms.core.claims import Claim, LABEL as CLAIM_LABEL, VERIFIED, SITE_VISIT
from findfarms.core.units import format_price, format_area

NAV = (
    ("dashboard", "/", "🏡", "Dashboard"),
    ("properties", "/properties", "📋", "All Properties"),
    ("discover", "/discover", "🔎", "Discover"),
    ("add", "/add", "➕", "Add Listing"),
    ("drops", "/price-drops", "📉", "Price Drops"),
    ("workflow", "/workflow", "✅", "Workflow"),
    ("about", "/about", "📖", "How this works"),
)

_STATUS = {
    "good":  ("#E1F5EE", "#085041"),
    "watch": ("#FAEEDA", "#633806"),
    "bad":   ("#FCEBEB", "#791F1F"),
    "info":  ("#E6F1FB", "#0C447C"),
    "muted": ("#F1EFE8", "#444441"),
}

CATEGORY_STATUS = {"A": "good", "B": "good", "C": "watch", "D": "muted", "E": "bad"}
LEGAL_STATUS = {"LOW": "good", "MEDIUM": "watch", "HIGH": "bad", "UNKNOWN": "muted"}
PRICE_STATUS = {"CHEAP": "good", "FAIR": "info", "EXPENSIVE": "watch",
                "UNKNOWN": "muted"}
ALERT_STATUS = {"🚨 ALERT": "bad", "🟢 STRONG": "good", "🟡 WATCH": "watch",
                "🔴 REJECT": "muted"}


def esc(s) -> str:
    return _html.escape(str(s)) if s is not None else ""


def badge(text: str, status: str = "muted", size: str = "normal") -> str:
    bg, fg = _STATUS.get(status, _STATUS["muted"])
    pad = "1px 6px" if size == "small" else "3px 9px"
    fs = "10px" if size == "small" else "11px"
    return (f'<span style="background:{bg};color:{fg};font-size:{fs};'
            f'font-weight:600;padding:{pad};border-radius:5px;'
            f'white-space:nowrap;display:inline-block">{esc(text)}</span>')


def score_pill(score, label: str = "", max_score: int = 100) -> str:
    """A score with a colour that means the same thing on every page."""
    if score is None:
        return badge("—", "muted")
    s = int(score)
    status = ("good" if s >= 70 else "watch" if s >= 50 else
              "muted" if s >= 35 else "bad")
    bg, fg = _STATUS[status]
    txt = f"{s}" + (f" {label}" if label else "")
    return (f'<span style="background:{bg};color:{fg};font-weight:700;'
            f'font-size:12px;padding:3px 9px;border-radius:5px;'
            f'white-space:nowrap">{esc(txt)}</span>')


def confidence_badge(claim: Claim, size: str = "small") -> str:
    """The confidence marker. Green only for things actually confirmed —
    verified and site-visit. Everything else reads as provisional, which is
    what it is."""
    icon, text = CLAIM_LABEL.get(claim.confidence, CLAIM_LABEL["UNKNOWN"])
    status = ("good" if claim.confidence in (VERIFIED, SITE_VISIT)
              else "info" if claim.confidence == "OBSERVED_FROM_MEDIA"
              else "muted" if claim.confidence == "UNKNOWN" else "watch")
    return badge(f"{icon} {text}", status, size)


def claim_value(claim: Claim, formatter=None, unknown: str = "Not stated") -> str:
    """A claim's value with its confidence badge, always together.

    The pairing is not optional anywhere in this UI. A value shown without
    its provenance is exactly the laundering the claims module exists to
    prevent, and it is far too easy to do by accident in a template.
    """
    if not claim.known:
        return f'<span style="color:#8a8880">{esc(unknown)}</span>'
    val = formatter(claim.value) if formatter else esc(claim.value)
    tip = esc(claim.source or "")
    note = f' title="{esc(claim.note)}"' if claim.note else ""
    return (f'<span{note}><span style="font-weight:600">{val}</span> '
            f'<span title="{tip}">{confidence_badge(claim)}</span></span>')


def card(title: str, body: str, icon: str = "", right: str = "",
         pad: str = "16px 18px", accent: str = "") -> str:
    head = ""
    if title:
        head = ('<div style="display:flex;align-items:center;gap:8px;'
                'margin-bottom:12px;flex-wrap:wrap">'
                + (f'<span style="font-size:17px">{icon}</span>' if icon else "")
                + f'<h3 style="font-size:14px;font-weight:650;color:#0b0b0b;'
                  f'margin:0;letter-spacing:-0.01em">{esc(title)}</h3>'
                + (f'<span style="margin-left:auto">{right}</span>' if right else "")
                + "</div>")
    border = f"border-left:3px solid {accent};" if accent else ""
    return (f'<div style="background:white;border:0.5px solid #e1e0d9;{border}'
            f'border-radius:9px;padding:{pad};margin-bottom:14px">{head}{body}</div>')


def bullets(items, colour: str = "#3a3a37", icon: str = "") -> str:
    if not items:
        return '<p style="color:#8a8880;font-size:12px;margin:0">Nothing recorded.</p>'
    lis = "".join(
        f'<li style="margin-bottom:6px;line-height:1.55">'
        + (f'<span style="margin-right:6px">{icon}</span>' if icon else "")
        + f'{esc(i)}</li>' for i in items)
    return (f'<ul style="margin:0;padding-left:{"18px" if not icon else "2px"};'
            f'font-size:12.5px;color:{colour};'
            f'{"list-style:none" if icon else ""}">{lis}</ul>')


def kv_table(rows, label_width: str = "180px") -> str:
    """Label/value rows. Values are pre-rendered HTML, usually claim_value()."""
    out = []
    for label, value in rows:
        out.append(
            f'<tr><td style="padding:5px 12px 5px 0;color:#6a6a66;font-size:12px;'
            f'vertical-align:top;width:{label_width}">{esc(label)}</td>'
            f'<td style="padding:5px 0;font-size:12.5px;color:#1a1a18;'
            f'vertical-align:top">{value}</td></tr>')
    return f'<table style="width:100%;border-collapse:collapse">{"".join(out)}</table>'


def data_table(headers, rows, align_right=()) -> str:
    """A scrollable table. Rows are lists of pre-rendered HTML cells."""
    th = "".join(
        f'<th style="text-align:{"right" if i in align_right else "left"};'
        f'padding:8px 10px;font-size:10.5px;font-weight:600;color:#6a6a66;'
        f'text-transform:uppercase;letter-spacing:0.04em;border-bottom:1px solid '
        f'#e1e0d9;white-space:nowrap">{esc(h)}</th>' for i, h in enumerate(headers))
    trs = []
    for r in rows:
        tds = "".join(
            f'<td style="text-align:{"right" if i in align_right else "left"};'
            f'padding:9px 10px;font-size:12.5px;color:#1a1a18;'
            f'border-bottom:0.5px solid #f0efe9;vertical-align:middle">{c}</td>'
            for i, c in enumerate(r))
        trs.append(f"<tr>{tds}</tr>")
    if not trs:
        trs = [f'<tr><td colspan="{len(headers)}" style="padding:20px;'
               f'text-align:center;color:#8a8880;font-size:12.5px">'
               f'Nothing here yet.</td></tr>']
    return (f'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch">'
            f'<table style="width:100%;border-collapse:collapse;min-width:640px">'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def warning_box(text: str, kind: str = "watch", title: str = "") -> str:
    bg, fg = _STATUS.get(kind, _STATUS["watch"])
    head = (f'<div style="font-weight:650;margin-bottom:5px;font-size:12.5px">'
            f'{esc(title)}</div>' if title else "")
    return (f'<div style="background:{bg};color:{fg};border-radius:7px;'
            f'padding:11px 13px;font-size:12.5px;line-height:1.55;'
            f'margin-bottom:12px">{head}{esc(text)}</div>')


def property_link(pid: str, text: str) -> str:
    return (f'<a href="/property?id={esc(pid)}" style="color:#185FA5;'
            f'text-decoration:none;font-weight:600">{esc(text)}</a>')


LEGAL_DISCLAIMER = (
    "Preliminary screening only — not legal advice and not a title clearance. "
    "This system reads advertisements, not documents. Engage a property lawyer "
    "in Mysuru who does agricultural title work, and a licensed surveyor, "
    "before any advance, agreement or payment."
)


def render_page(active: str, title: str, body: str, extra_js: str = "") -> str:
    nav = "".join(
        f'<a href="{href}" style="display:flex;align-items:center;gap:9px;'
        f'padding:8px 12px;border-radius:7px;text-decoration:none;font-size:13px;'
        f'{"background:#1a1a18;color:white;font-weight:600" if key == active else "color:#3a3a37"}'
        f'">{icon} <span>{esc(label)}</span></a>'
        for key, href, icon, label in NAV)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Mysuru Farm Finder</title>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,
       system-ui,sans-serif;background:#faf9f5;color:#1a1a18;
       -webkit-font-smoothing:antialiased}}
  a{{color:#185FA5}}
  .layout{{display:flex;min-height:100vh}}
  .side{{width:214px;flex-shrink:0;background:#f4f2ec;border-right:0.5px solid #e1e0d9;
        padding:18px 12px;position:sticky;top:0;height:100vh;overflow-y:auto}}
  .main{{flex:1;padding:24px 30px 60px;max-width:1400px;min-width:0}}
  h1{{font-size:22px;font-weight:650;margin:0 0 4px;letter-spacing:-0.02em}}
  h2{{font-size:15px;font-weight:650;margin:26px 0 12px;letter-spacing:-0.01em}}
  .sub{{color:#6a6a66;font-size:13px;margin:0 0 22px}}
  .grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
  input,textarea,select,button{{font-family:inherit;font-size:13px}}
  input[type=text],input[type=url],textarea,select{{width:100%;padding:9px 11px;
    border:1px solid #ddd9cd;border-radius:7px;background:white}}
  textarea{{min-height:150px;resize:vertical;line-height:1.5}}
  button{{background:#1a1a18;color:white;border:none;padding:9px 17px;
    border-radius:7px;cursor:pointer;font-weight:600}}
  button:hover{{background:#333330}}
  button.sec{{background:white;color:#1a1a18;border:1px solid #ddd9cd}}
  .disc{{font-size:11px;color:#8a8880;line-height:1.5;margin-top:26px;
    padding-top:14px;border-top:0.5px solid #e1e0d9}}
  @media(max-width:820px){{
    .layout{{flex-direction:column}}
    .side{{width:100%;height:auto;position:static;display:flex;flex-wrap:wrap;gap:4px}}
    .side .brand{{width:100%}}
    .main{{padding:18px 14px 50px}}
  }}
</style></head>
<body><div class="layout">
<nav class="side">
  <div class="brand" style="padding:4px 12px 16px">
    <div style="font-size:15px;font-weight:700;letter-spacing:-0.02em">🌾 Farm Finder</div>
    <div style="font-size:11px;color:#8a8880;margin-top:2px">Mysuru · 30 km · 1–5 acres</div>
  </div>
  {nav}
</nav>
<main class="main">
{body}
<div class="disc">⚖️ {esc(LEGAL_DISCLAIMER)}</div>
</main></div>
<script>{extra_js}</script>
</body></html>"""


def json_script(name: str, data) -> str:
    return f'<script>window.{name} = {json.dumps(data, default=str)};</script>'
