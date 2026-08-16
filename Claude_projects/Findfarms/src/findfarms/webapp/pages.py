"""
pages.py
========
Page bodies. Each returns (html, extra_js).

The dashboard's section order encodes the user's own stated priority —
livability and water security first, agricultural return second,
appreciation third — rather than sorting everything by deal score and
calling it done. "Best Water" sits directly under the headline list because
water is the factor that cannot be fixed after purchase, and "Due Diligence"
is a section rather than a footnote because that is where nearly every
property actually is.
"""

from __future__ import annotations

from findfarms.core import pipeline
from findfarms.core.claims import ClaimSet
from findfarms.core.units import format_price, format_area
from findfarms.discovery import ingest as ingest_mod, sources as sources_mod
from findfarms.store import db
from findfarms.webapp.views import (ALERT_STATUS, CATEGORY_STATUS, LEGAL_STATUS,
                                    PRICE_STATUS, badge, bullets, card,
                                    claim_value, confidence_badge, data_table,
                                    esc, kv_table, property_link, score_pill,
                                    warning_box)


def _rows():
    """All properties as (pid, prop, claims, scores), scored."""
    out = []
    for pid, prop in db.load_properties().items():
        cs = ClaimSet.from_dict(prop.get("claims", {}))
        out.append((pid, prop, cs, prop.get("scores") or {}))
    return out


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ppa(cs):
    return _num(cs.value("price_per_acre")) or _num(cs.value("price_per_acre_stated"))


def _label(cs, pid):
    village = cs.value("village") or "Unknown village"
    acres = cs.value("acres")
    a = format_area(acres) if acres else "size ?"
    return f"{village} · {a}"


def _ranked(exclude_rejected: bool = True):
    rows = _rows()
    if exclude_rejected:
        rows = [r for r in rows if r[3].get("status") != "DO NOT PROCEED"]
    return sorted(rows, key=lambda r: -(r[3].get("deal") or 0))


def _mini_table(rows, value_fn, value_header, limit=10, note=""):
    body = data_table(
        ["#", "Property", "Acres", "₹/acre", "km", value_header, "Deal", "Status"],
        [[str(i + 1),
          property_link(pid, cs.value("village") or "—"),
          format_area(cs.value("acres")),
          format_price(_ppa(cs)) if _ppa(cs) else "—",
          f"{s.get('driving_km'):.0f}" if s.get("driving_km") else "—",
          value_fn(pid, prop, cs, s),
          score_pill(s.get("deal")),
          badge(s.get("status", "—"),
                "bad" if s.get("status") == "DO NOT PROCEED" else
                "watch" if s.get("status") == "DUE DILIGENCE REQUIRED" else "good",
                "small")]
         for i, (pid, prop, cs, s) in enumerate(rows[:limit])],
        align_right=(2, 3, 4, 5, 6))
    if note:
        body += (f'<p style="font-size:11.5px;color:#8a8880;margin:10px 0 0;'
                 f'line-height:1.5">{esc(note)}</p>')
    return body


# ---------------------------------------------------------- dashboard ----

def dashboard_page(params=None):
    rows = _rows()
    if not rows:
        return _empty_state(), ""

    ranked = _ranked()
    total = len(rows)
    rejected = [r for r in rows if r[3].get("status") == "DO NOT PROCEED"]
    dd = [r for r in rows if r[3].get("status") == "DUE DILIGENCE REQUIRED"]
    alerts = [r for r in rows if r[3].get("alert") == "🚨 ALERT"]
    strong = [r for r in rows if r[3].get("alert") == "🟢 STRONG"]
    drops = pipeline.price_drops()

    # -- headline counters --------------------------------------------------
    stats = "".join(
        f'<div style="background:white;border:0.5px solid #e1e0d9;border-radius:9px;'
        f'padding:13px 15px;flex:1;min-width:118px">'
        f'<div style="font-size:23px;font-weight:700;letter-spacing:-0.02em;'
        f'color:{col}">{v}</div>'
        f'<div style="font-size:11px;color:#6a6a66;margin-top:1px">{esc(l)}</div></div>'
        for v, l, col in (
            (total, "Tracked", "#1a1a18"),
            (len(alerts), "🚨 Alert", "#791F1F" if alerts else "#8a8880"),
            (len(strong), "🟢 Strong", "#0F6E56" if strong else "#8a8880"),
            (len(drops), "📉 Price drops", "#0F6E56" if drops else "#8a8880"),
            (len(dd), "⚠️ Due diligence", "#633806"),
            (len(rejected), "❌ Rejected", "#8a8880"),
        ))

    body = [
        '<h1>Mysuru Retirement Farm Finder</h1>',
        '<p class="sub">Best combination of legal safety, water security, '
        'agricultural productivity, retirement livability and fair price — '
        'within ~30 km of Mysuru. Not the cheapest land.</p>',
        f'<div style="display:flex;gap:11px;flex-wrap:wrap;margin-bottom:22px">{stats}</div>',
    ]

    # A standing note about where the ranking actually stands, rather than
    # letting a page of numbers imply more certainty than exists.
    unverified = sum(1 for _, _, _, s in rows if s.get("legal_risk") == "UNKNOWN")
    if unverified:
        body.append(warning_box(
            f"{unverified} of {total} properties have UNKNOWN legal risk — nobody "
            f"has read a document for them, so their deal scores are capped and "
            f"none can rank as an A. That is the expected state for anything "
            f"sourced from advertisements. Scores move as you verify.",
            "info", "Where this ranking currently stands"))

    # -- 🔥 top opportunities ------------------------------------------------
    body.append("<h2>🔥 Best current opportunities</h2>")
    body.append(card("", _mini_table(
        ranked, lambda p, pr, cs, s: score_pill(s.get("water"), "💧"), "Water",
        limit=10,
        note="Ranked by deal score: legal evidence 25%, water 25%, agriculture "
             "15%, location 10%, price 10%, retirement 10%, optionality 5%. "
             "Properties with a legal hard stop are excluded entirely — see "
             "Rejected below."),
        pad="6px 8px 12px"))

    # -- 💧 water -------------------------------------------------------------
    by_water = sorted([r for r in rows if r[3].get("status") != "DO NOT PROCEED"],
                      key=lambda r: -(r[3].get("water") or 0))
    body.append("<h2>💧 Best water security</h2>")
    body.append(card("", _mini_table(
        by_water, lambda p, pr, cs, s: score_pill(s.get("water"), "💧"), "Water",
        note="Water is the one thing money cannot add to a parcel. Scores here "
             "are capped at 55 while every water claim rests on the seller's "
             "word — a site visit or pump test lifts the cap."),
        pad="6px 8px 12px"))

    # -- 🌳 agriculture -------------------------------------------------------
    by_agri = sorted([r for r in rows if r[3].get("status") != "DO NOT PROCEED"],
                     key=lambda r: -(r[3].get("agriculture") or 0))
    body.append("<h2>🌳 Best agricultural land</h2>")
    body.append(card("", _mini_table(
        by_agri, lambda p, pr, cs, s: score_pill(s.get("agriculture"), "🌳"),
        "Agri", note="Established perennials score above annual crops: they "
                     "yield with modest labour and survive a neglected season."),
        pad="6px 8px 12px"))

    # -- 🏡 retirement --------------------------------------------------------
    by_ret = sorted([r for r in rows if r[3].get("status") != "DO NOT PROCEED"],
                    key=lambda r: -(r[3].get("retirement") or 0))
    body.append("<h2>🏡 Best for retirement living</h2>")
    body.append(card("", _mini_table(
        by_ret, lambda p, pr, cs, s: score_pill(s.get("retirement"), "🏡"),
        "Retire", note="Weighted on the days that go wrong: hospital access, "
                       "monsoon road passability, neighbours within reach, "
                       "mobile signal. Land appreciation is deliberately not a "
                       "factor in this score."),
        pad="6px 8px 12px"))

    # -- 💰 value -------------------------------------------------------------
    by_value = sorted([r for r in rows
                       if r[3].get("price_position") in ("CHEAP", "FAIR")
                       and r[3].get("status") != "DO NOT PROCEED"],
                      key=lambda r: -(r[3].get("deal") or 0))
    body.append("<h2>💰 Best value against comparables</h2>")
    body.append(card("", _mini_table(
        by_value, lambda p, pr, cs, s: badge(
            s.get("price_position", "—"),
            PRICE_STATUS.get(s.get("price_position"), "muted"), "small"), "Price",
        note="Compared against adjusted asking prices of similar parcels in the "
             "database — never against a claimed 'market value'. Cheap in this "
             "market is more often a title, water or access problem than a "
             "bargain."),
        pad="6px 8px 12px"))

    # -- 🤝 owner direct ------------------------------------------------------
    owner_direct = [r for r in rows if r[2].get("owner_direct").truthy()
                    and r[3].get("status") != "DO NOT PROCEED"]
    body.append("<h2>🤝 Owner-direct listings</h2>")
    body.append(card("", _mini_table(
        sorted(owner_direct, key=lambda r: -(r[3].get("deal") or 0)),
        lambda p, pr, cs, s: claim_value(cs.get("owner_direct")), "Owner direct",
        note="Negotiation with the decision-maker, and no commission built into "
             "the asking price. Still only the listing's own claim until you "
             "meet the person named on the RTC."),
        pad="6px 8px 12px"))

    # -- 🔎 motivated ---------------------------------------------------------
    motivated = [r for r in rows
                 if r[3].get("motivation") in ("HIGHLY_MOTIVATED", "POSSIBLY_MOTIVATED")
                 and r[3].get("status") != "DO NOT PROCEED"]
    body.append("<h2>🔎 Possible negotiating room</h2>")
    body.append(card("", _mini_table(
        sorted(motivated, key=lambda r: -(r[3].get("deal") or 0)),
        lambda p, pr, cs, s: badge(
            s.get("motivation", "—").replace("_", " ").title(),
            "good" if s.get("motivation") == "HIGHLY_MOTIVATED" else "watch",
            "small"), "Signal",
        note="Measures negotiating room from published wording and observed "
             "market behaviour — price cuts, time tracked, relisting. It is "
             "deliberately not an inference about the seller's circumstances."),
        pad="6px 8px 12px"))

    # -- 📉 price drops -------------------------------------------------------
    body.append("<h2>📉 Price drops</h2>")
    if drops:
        body.append(card("", data_table(
            ["Property", "Acres", "First seen", "Now", "Drop", "Steps", "Days", ""],
            [[property_link(d["property_id"], d["village"]),
              format_area(d["acres"]),
              format_price(d["first_price"]),
              f'<b>{format_price(d["current_price"])}</b>',
              badge(f'−{d["drop_pct"]:.0f}%', "good", "small"),
              str(d["steps"]), str(d["days_tracked"] or "—"),
              badge("Negotiation opportunity", "good", "small")]
             for d in drops],
            align_right=(1, 2, 3, 4, 5, 6)) +
            '<p style="font-size:11.5px;color:#8a8880;margin:10px 0 0;line-height:1.5">'
            'A seller who has already cut once has shown the list price was not '
            'the real price. This is worth more attention than a hundred new '
            'listings.</p>', pad="6px 8px 12px"))
    else:
        body.append(card("", '<p style="color:#8a8880;font-size:12.5px;margin:0">'
                             'No price drops recorded yet. This section fills in as '
                             'the same properties are re-discovered over months — '
                             'it is the reason the database keeps history rather '
                             'than re-scoring from scratch.</p>'))

    # -- ⚠️ due diligence ------------------------------------------------------
    body.append("<h2>⚠️ Awaiting document verification</h2>")
    body.append(card("", _mini_table(
        sorted(dd, key=lambda r: -(r[3].get("deal") or 0)),
        lambda p, pr, cs, s: badge(s.get("legal_risk", "—"),
                                   LEGAL_STATUS.get(s.get("legal_risk"), "muted"),
                                   "small"), "Legal", limit=15,
        note="UNKNOWN is not a neutral verdict — it means nobody has checked. "
             "Every property here is capped at 74/100 until documents exist."),
        pad="6px 8px 12px"))

    # -- ❌ rejected -----------------------------------------------------------
    if rejected:
        body.append("<h2>❌ Rejected — do not proceed</h2>")
        body.append(card("", data_table(
            ["Property", "Acres", "₹/acre", "Reason"],
            [[property_link(pid, cs.value("village") or "—"),
              format_area(cs.value("acres")),
              format_price(_ppa(cs)) if _ppa(cs) else "—",
              esc(_reject_reason(pid))]
             for pid, prop, cs, s in rejected], align_right=(1, 2)) +
            '<p style="font-size:11.5px;color:#8a8880;margin:10px 0 0;line-height:1.5">'
            'Kept in the database rather than deleted: they still count as price '
            'comparables, and a parcel rejected today may be re-listed by a '
            'different seller with the defect resolved.</p>', pad="6px 8px 12px"))

    return "".join(body), ""


def _reject_reason(pid: str) -> str:
    prop = db.get_property(pid)
    if not prop:
        return "—"
    cs = ClaimSet.from_dict(prop.get("claims", {}))
    a = pipeline.analyse_property(cs, db.load_properties(), pid, prop,
                                  db.price_timeline(pid))
    highs = [f["label"] for f in a["legal"]["findings"] if f["severity"] == "HIGH"]
    return "; ".join(highs) if highs else (a["deal"]["gates"] or ["—"])[0][:90]


def _empty_state():
    return (
        '<h1>Mysuru Retirement Farm Finder</h1>'
        '<p class="sub">No properties tracked yet.</p>'
        + card("Start here",
               '<p style="font-size:13px;line-height:1.65;margin:0 0 14px">'
               'This system is a research database, not a scraper. Its value is '
               'in what happens after a listing arrives — deduplication across '
               'sources, independent distance estimation, evidence-weighted '
               'scoring, and price history tracked over months. Getting listings '
               '<em>in</em> is mostly manual, and that is the honest design '
               'rather than a limitation.</p>'
               '<p style="font-size:13px;line-height:1.65;margin:0 0 16px">'
               '<a href="/discover">Open the Discover page</a> for the full '
               'keyword × village search matrix as clickable links, then paste '
               'anything worth keeping into <a href="/add">Add Listing</a>.</p>'
               '<a href="/add"><button>Add your first listing</button></a>',
               "🌱"))


# --------------------------------------------------------- properties ----

def properties_page(params=None):
    params = params or {}
    sort = (params.get("sort") or ["deal"])[0]
    show_rejected = (params.get("rejected") or ["0"])[0] == "1"

    rows = _rows()
    if not show_rejected:
        rows = [r for r in rows if r[3].get("status") != "DO NOT PROCEED"]

    keys = {"deal": lambda r: -(r[3].get("deal") or 0),
            "water": lambda r: -(r[3].get("water") or 0),
            "agri": lambda r: -(r[3].get("agriculture") or 0),
            "retire": lambda r: -(r[3].get("retirement") or 0),
            "price": lambda r: (_ppa(r[2]) or 9e18),
            "distance": lambda r: (r[3].get("driving_km") or 9e9),
            "acres": lambda r: (_num(r[2].value("acres")) or 9e9)}
    rows = sorted(rows, key=keys.get(sort, keys["deal"]))

    opts = "".join(
        f'<option value="{k}"{" selected" if k == sort else ""}>{esc(l)}</option>'
        for k, l in (("deal", "Deal score"), ("water", "Water"),
                     ("agri", "Agriculture"), ("retire", "Retirement"),
                     ("price", "₹/acre (low first)"),
                     ("distance", "Distance"), ("acres", "Size")))

    controls = (
        f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;'
        f'margin-bottom:14px">'
        f'<label style="font-size:12px;color:#6a6a66">Sort by</label>'
        f'<select onchange="location.href=\'/properties?sort=\'+this.value+'
        f'\'&rejected={1 if show_rejected else 0}\'" style="width:auto">{opts}</select>'
        f'<a href="/properties?sort={esc(sort)}&rejected={0 if show_rejected else 1}" '
        f'style="font-size:12px;text-decoration:none">'
        f'{"Hide" if show_rejected else "Show"} rejected</a></div>')

    table = data_table(
        ["Rank", "Village", "Acres", "Price", "₹/Acre", "Distance", "Water",
         "Agri", "Retire", "Legal", "Deal", "Seller", "Status", "Sources"],
        [[str(i + 1),
          property_link(pid, cs.value("village") or "—"),
          format_area(cs.value("acres")),
          format_price(_num(cs.value("asking_price"))) if cs.value("asking_price") else "—",
          format_price(_ppa(cs)) if _ppa(cs) else "—",
          (f"{s.get('driving_km'):.0f} km" if s.get("driving_km") else "—"),
          score_pill(s.get("water")),
          score_pill(s.get("agriculture")),
          score_pill(s.get("retirement")),
          badge(s.get("legal_risk", "—"),
                LEGAL_STATUS.get(s.get("legal_risk"), "muted"), "small"),
          score_pill(s.get("deal")) + " " +
          badge(s.get("category", "—"),
                CATEGORY_STATUS.get(s.get("category"), "muted"), "small"),
          ("Owner" if cs.get("owner_direct").truthy() else
           "Broker" if cs.get("seller_type").known else "—"),
          badge(s.get("status", "—"),
                "bad" if s.get("status") == "DO NOT PROCEED" else
                "watch" if s.get("status") == "DUE DILIGENCE REQUIRED" else "good",
                "small"),
          str(len(prop.get("sources", [])))]
         for i, (pid, prop, cs, s) in enumerate(rows)],
        align_right=(2, 3, 4, 5, 6, 7, 8, 10, 13))

    return (f'<h1>All properties</h1>'
            f'<p class="sub">{len(rows)} tracked. Every number here is computed '
            f'from claims that carry their own confidence — open a property to '
            f'see what is evidence and what is advertising.</p>'
            f'{controls}{card("", table, pad="6px 8px 10px")}'), ""


# ------------------------------------------------------ property page ----

def property_page(params=None):
    pid = ((params or {}).get("id") or [""])[0]
    prop = db.get_property(pid)
    if not prop:
        return '<h1>Not found</h1><p class="sub">No property with that id.</p>', ""

    cs = ClaimSet.from_dict(prop.get("claims", {}))
    a = pipeline.analyse_property(cs, db.load_properties(), pid, prop,
                                  db.price_timeline(pid))
    deal, water, agri, ret = a["deal"], a["water"], a["agriculture"], a["retirement"]
    legal, price, motiv, loc = a["legal"], a["price"], a["motivation"], a["location"]

    village = cs.value("village") or "Unknown village"
    head = [
        f'<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">'
        f'<h1 style="margin:0">{esc(village)}</h1>'
        f'{badge(a["alert"]["level"], ALERT_STATUS.get(a["alert"]["level"], "muted"))}'
        f'{badge(deal["status"], "bad" if deal["status"] == "DO NOT PROCEED" else "watch" if deal["status"] == "DUE DILIGENCE REQUIRED" else "good")}'
        f'</div>',
        f'<p class="sub">{esc(format_area(cs.value("acres")))} · '
        f'{esc(format_price(_ppa(cs)))}/acre · '
        f'~{loc["driving_km"]:.0f} km from Mysuru · '
        f'tracked {db.days_on_market(prop) or 0} days · '
        f'{len(prop.get("sources", []))} source(s)</p>' if loc["driving_km"] else
        f'<p class="sub">{esc(format_area(cs.value("acres")))}</p>',
    ]

    # -- score summary -------------------------------------------------------
    scores_html = "".join(
        f'<div style="text-align:center;flex:1;min-width:88px">'
        f'<div style="font-size:10.5px;color:#6a6a66;margin-bottom:4px;'
        f'text-transform:uppercase;letter-spacing:0.04em">{esc(l)}</div>'
        f'{score_pill(v)}</div>'
        for l, v in (("Deal", deal["score"]), ("Water", water["score"]),
                     ("Agriculture", agri["score"]), ("Retirement", ret["score"])))
    scores_html += (
        f'<div style="text-align:center;flex:1;min-width:88px">'
        f'<div style="font-size:10.5px;color:#6a6a66;margin-bottom:4px;'
        f'text-transform:uppercase;letter-spacing:0.04em">Legal risk</div>'
        f'{badge(legal["level"], LEGAL_STATUS.get(legal["level"], "muted"))}</div>'
        f'<div style="text-align:center;flex:1;min-width:88px">'
        f'<div style="font-size:10.5px;color:#6a6a66;margin-bottom:4px;'
        f'text-transform:uppercase;letter-spacing:0.04em">Price</div>'
        f'{badge(price["position"], PRICE_STATUS.get(price["position"], "muted"))}</div>'
        f'<div style="text-align:center;flex:1;min-width:88px">'
        f'<div style="font-size:10.5px;color:#6a6a66;margin-bottom:4px;'
        f'text-transform:uppercase;letter-spacing:0.04em">Category</div>'
        f'{badge(deal["category"] + " · " + deal["category_name"], CATEGORY_STATUS.get(deal["category"], "muted"))}</div>')
    head.append(card("", f'<div style="display:flex;gap:10px;flex-wrap:wrap;'
                         f'align-items:center">{scores_html}</div>'))

    body = head

    for g in deal["gates"]:
        body.append(warning_box(g, "bad" if "STOPPED" in g else "watch",
                                "Gate applied"))

    # -- why interesting / risks --------------------------------------------
    body.append(f'<div class="grid">'
                f'{card("Why this is interesting", bullets(a["why_interesting"], icon="•"), "✨")}'
                f'{card("Major risks", bullets(a["major_risks"], "#791F1F", icon="⚠"), "🚨")}'
                f'</div>')

    # -- claimed facts -------------------------------------------------------
    facts = kv_table([
        ("Village / taluk", claim_value(cs.get("village")) + " · " +
         claim_value(cs.get("taluk"))),
        ("Survey number", claim_value(cs.get("survey_number"))),
        ("Extent", claim_value(cs.get("acres"), lambda v: esc(format_area(v)))),
        ("Asking price", claim_value(cs.get("asking_price"),
                                     lambda v: esc(format_price(v)))),
        ("Price per acre", claim_value(cs.get("price_per_acre"),
                                       lambda v: esc(format_price(v)))),
        ("Negotiable", claim_value(cs.get("negotiable"))),
        ("Water source", claim_value(cs.get("water_sources"))),
        ("Borewell depth", claim_value(cs.get("borewell_depth_ft"),
                                       lambda v: f"{esc(v)} ft")),
        ("Summer yield", claim_value(cs.get("summer_yield"),
                                     unknown="Not established — ask")),
        ("Soil", claim_value(cs.get("soil"))),
        ("Crops / trees", claim_value(cs.get("crops"))),
        ("Road", claim_value(cs.get("road_surface")) + " · " +
         claim_value(cs.get("road_frontage"))),
        ("Distance to main road",
         claim_value(cs.get("main_road_distance_m"),
                     lambda v: ("fronts a main road" if float(v) == 0
                                else f"{float(v):,.0f} m"),
                     unknown="Not stated — the number sellers omit when it is bad")),
        ("Electricity", claim_value(cs.get("electricity"))),
        ("Seller", claim_value(cs.get("owner_direct"), lambda v: "Owner direct")
         if cs.get("owner_direct").known else claim_value(cs.get("seller_type"))),
        ("Phone", claim_value(cs.get("phone"))),
    ])
    body.append(card("What the listing claims", facts
                     + '<p style="font-size:11.5px;color:#8a8880;margin:12px 0 0;'
                       'line-height:1.5">Every badge above says where the value came '
                       'from. 💬 means the seller said it and nobody has checked.</p>',
                     "📋"))

    if a["conflicts"]:
        body.append(card("Sources disagree", bullets(a["conflicts"], "#633806"), "⚡"))

    # -- location -------------------------------------------------------------
    r = loc["resolved"]
    map_link = ""
    if r.get("lat") and r.get("lon"):
        map_link = (f'<a href="https://www.google.com/maps/@{r["lat"]},{r["lon"]},15z" '
                    f'target="_blank" rel="noopener">Open in Maps</a> · '
                    f'<a href="https://www.google.com/maps/dir/Mysuru/'
                    f'{r["lat"]},{r["lon"]}" target="_blank" rel="noopener">'
                    f'Route from Mysuru</a>')
    loc_rows = [
        ("Position", esc(f"{r.get('lat')}, {r.get('lon')}") +
         f' <span style="color:#8a8880">({esc(r.get("method", "").replace("_", " "))}'
         f', {esc(r.get("coord_confidence", ""))})</span>' if r.get("lat") else "Unresolved"),
        ("Straight line", f'{loc["straight_km"]} km' if loc["straight_km"] else "—"),
        ("Driving (estimated)",
         f'<b>{loc["driving_km"]:.0f} km</b> · ~{loc["drive_minutes"]} min '
         f'<span style="color:#8a8880">(computed, not routed — measure it '
         f'yourself)</span>' if loc["driving_km"] else "—"),
        ("Seller stated", claim_value(cs.get("seller_stated_distance"))),
        ("Radius", badge(loc["radius_status"].replace("_", " "),
                         "good" if loc["radius_status"] == "PREFERRED" else
                         "watch" if "OUTSIDE" not in loc["radius_status"] else "bad",
                         "small")),
    ]

    # Connectivity to a main tarred road — a different question from road
    # frontage, and the one that decides whether everything below is
    # reachable in August. Placed directly under the distance rows for that
    # reason, not down with the amenities.
    band = ret.get("main_road_band") or "UNKNOWN"
    band_status = {"ON_MAIN_ROAD": "good", "EXCELLENT": "good", "GOOD": "good",
                   "ACCEPTABLE": "watch", "CONCERNING": "watch",
                   "POOR": "bad", "UNKNOWN": "muted"}.get(band, "muted")
    road_m = ret.get("main_road_m")
    loc_rows.append((
        "To main tarred road",
        (claim_value(cs.get("main_road_distance_m"),
                     lambda v: ("fronts it" if float(v) == 0
                                else f"{float(v):,.0f} m"),
                     unknown="Not stated — ask") + " "
         + badge(band.replace("_", " ").title(), band_status, "small"))))

    # Amenity distances, all town-level. Grouped and labelled as such in one
    # place so the granularity caveat is stated once and applies visibly to
    # every row rather than being attached to each.
    amenity_rows = []
    for label, km_key, name_key in (
            ("Hospital facilities", "hospital_km", "hospital_name"),
            ("Yoga shalas", "yoga_km", "yoga_name"),
            ("Ayurveda / wellness", "wellness_km", "wellness_name"),
            ("Schools", "school_km", "school_name"),
            ("Market / groceries", "market_km", None)):
        km = ret.get(km_key)
        if km is None:
            amenity_rows.append((label, '<span style="color:#8a8880">'
                                        'Not estimated</span>'))
            continue
        name = ret.get(name_key) if name_key else None
        # Colour by that amenity's own threshold — 15 km to a hospital and
        # 15 km to a yoga shala are not the same news.
        limits = {"Hospital facilities": (12, 20), "Yoga shalas": (12, 20),
                  "Ayurveda / wellness": (12, 22), "Schools": (8, 15),
                  "Market / groceries": (8, 15)}[label]
        st = "good" if km <= limits[0] else "watch" if km <= limits[1] else "bad"
        amenity_rows.append((
            label, f'<b>~{km:.0f} km</b>'
                   + (f' <span style="color:#8a8880">({esc(name)})</span>' if name else "")
                   + " " + badge({"good": "close", "watch": "a drive",
                                  "bad": "far"}[st], st, "small")))
    loc_rows.extend(amenity_rows)
    if map_link:
        loc_rows.append(("Maps", map_link))
    disc = cs.get("distance_discrepancy")
    body.append(card("Location", kv_table(loc_rows)
                     + (warning_box(str(disc.value), "watch",
                                    "Seller's distance does not match")
                        if disc.known else "")
                     + f'<p style="font-size:11.5px;color:#8a8880;margin:12px 0 0;'
                       f'line-height:1.5">{esc(loc["radius_why"])}</p>'
                     + '<p style="font-size:11.5px;color:#8a8880;margin:8px 0 0;'
                       'line-height:1.5">Amenity distances are <b>town-level and '
                       'unverified</b>: they measure to the nearest place known to '
                       'have facilities of that kind, not to a specific confirmed '
                       'hospital, shala or school. Yoga and wellness cluster far '
                       'more tightly than the others — around Mysuru they are '
                       'concentrated in the city, chiefly Gokulam.</p>', "📍"))

    # -- the five engines -----------------------------------------------------
    def engine_card(title, icon, result, extra=""):
        inner = (f'<div style="margin-bottom:12px">{score_pill(result["score"])} '
                 f'<span style="font-size:12.5px;color:#6a6a66;margin-left:6px">'
                 f'{esc(result["label"])}</span></div>')
        if result.get("drivers"):
            inner += ('<div style="font-size:11px;color:#6a6a66;margin:12px 0 6px;'
                      'text-transform:uppercase;letter-spacing:0.04em">What earned '
                      'points</div>' + bullets(result["drivers"], icon="✓"))
        if result.get("warnings"):
            inner += ('<div style="font-size:11px;color:#6a6a66;margin:14px 0 6px;'
                      'text-transform:uppercase;letter-spacing:0.04em">Warnings</div>'
                      + bullets(result["warnings"], "#791F1F", icon="⚠"))
        return card(title, inner + extra, icon)

    body.append(engine_card("Water assessment", "💧", water))

    # -- watershed: rivers, rainfall, undulation, harvesting ----------------
    ws = a["watershed"]
    riv, vols = ws["rivers"], ws["volumes"]

    def _riv(km):
        if km is None:
            return '<span style="color:#8a8880">Not computed</span>'
        from findfarms.core.watershed import RIVER_PRECISION_KM
        if km <= RIVER_PRECISION_KM:
            return (f'<b>within ~{RIVER_PRECISION_KM:.0f} km</b> '
                    + badge("below data resolution", "watch", "small"))
        return f'<b>~{km:.1f} km</b>'

    ws_rows = [
        ("Kaveri (Cauvery)", _riv(riv.get("kaveri_km"))),
        ("Kabini (Kapila)", _riv(riv.get("kabini_km"))),
        ("Seller's river claim", claim_value(cs.get("seller_stated_river_distance"),
                                             unknown="Not stated")),
        ("Annual rainfall",
         f'<b>~{ws["rainfall_mm"]:.0f} mm</b> '
         f'<span style="color:#8a8880">({esc(ws["rainfall_source"])})</span>'),
        ("Land undulation",
         claim_value(cs.get("undulation"),
                     lambda v: esc(str(v).replace("_", " ")),
                     unknown="Not stated — walk it and find the low point")),
        ("Runoff coefficient",
         f'{ws["runoff_coefficient"]:.2f} '
         f'<span style="color:#8a8880">(from slope and soil)</span>'),
    ]

    if vols.get("harvestable_m3"):
        ws_rows += [
            ("Rain falling on the land",
             f'{vols["gross_m3"]:,} m³/yr '
             f'<span style="color:#8a8880">(gross — not what you can keep)</span>'),
            ("Runs off as surface flow", f'{vols["runoff_m3"]:,} m³/yr'),
            ("Realistically harvestable",
             f'<b>{vols["harvestable_m3"]:,} m³/yr</b> — '
             f'<b>~{vols["harvestable_litres"] / 1_000_000:.1f} million litres</b>'),
            ("Suggested farm pond", f'~{vols["suggested_pond_m3"]:,} m³'),
        ]

    ws_html = (f'<div style="margin-bottom:12px">{score_pill(ws["score"])} '
               f'<span style="font-size:12.5px;color:#6a6a66;margin-left:6px">'
               f'{esc(ws["label"])} harvesting potential</span></div>'
               + kv_table(ws_rows))
    if ws.get("drivers"):
        ws_html += ('<div style="font-size:11px;color:#6a6a66;margin:14px 0 6px;'
                    'text-transform:uppercase;letter-spacing:0.04em">What earned '
                    'points</div>' + bullets(ws["drivers"], icon="✓"))
    if ws.get("recommendations"):
        ws_html += ('<div style="font-size:11px;color:#6a6a66;margin:14px 0 6px;'
                    'text-transform:uppercase;letter-spacing:0.04em">'
                    'How to build the water</div>'
                    + bullets(ws["recommendations"], "#0C447C", icon="→"))
    if ws.get("warnings"):
        ws_html += ('<div style="font-size:11px;color:#6a6a66;margin:14px 0 6px;'
                    'text-transform:uppercase;letter-spacing:0.04em">Warnings</div>'
                    + bullets(ws["warnings"], "#791F1F", icon="⚠"))
    ws_html += (f'<p style="font-size:11.5px;color:#8a8880;margin:14px 0 0;'
                f'line-height:1.5">{esc(ws["caveat"])}</p>')
    body.append(card("Rivers, rainfall & harvesting potential", ws_html, "🌧️"))
    body.append(engine_card("Agricultural assessment", "🌳", agri))
    body.append(engine_card("Retirement suitability", "🏡", ret))

    # -- legal ----------------------------------------------------------------
    legal_html = (f'<div style="margin-bottom:12px">'
                  f'{badge(legal["level"], LEGAL_STATUS.get(legal["level"], "muted"))}'
                  f'</div>'
                  f'<p style="font-size:12.5px;line-height:1.6;color:#3a3a37;'
                  f'margin:0 0 14px">{esc(legal["rationale"])}</p>')
    if legal["findings"]:
        for f in legal["findings"]:
            kind = {"HIGH": "bad", "MEDIUM": "watch"}.get(f["severity"], "info")
            legal_html += warning_box(f["why"], kind,
                                      f'{f["severity"]} — {f["label"]}')
    legal_html += ('<div style="font-size:11px;color:#6a6a66;margin:16px 0 6px;'
                   'text-transform:uppercase;letter-spacing:0.04em">'
                   'What this screen did NOT check</div>'
                   + bullets(legal["not_checked"], "#791F1F", icon="✗"))
    legal_html += warning_box(legal["disclaimer"], "bad")
    body.append(card("Legal risk screen", legal_html, "⚖️"))

    # -- price ----------------------------------------------------------------
    price_html = (f'<div style="margin-bottom:10px">'
                  f'{badge(price["position"], PRICE_STATUS.get(price["position"], "muted"))}'
                  f'</div>'
                  f'<p style="font-size:12.5px;line-height:1.6;margin:0 0 14px">'
                  f'{esc(price["rationale"])}</p>')
    if price["comparables"]:
        price_html += data_table(
            ["Comparable", "Acres", "Asking ₹/ac", "Adjusted ₹/ac", "Adjustments"],
            [[property_link(c["property_id"], c["village"]),
              format_area(c["acres"]),
              format_price(c["raw_ppa"]),
              format_price(c["adjusted_ppa"]),
              esc("; ".join(c["adjustments"]) or "none")]
             for c in price["comparables"][:10]], align_right=(1, 2, 3))
    for w in price["warnings"]:
        price_html += warning_box(w, "watch")
    body.append(card("Price analysis", price_html, "💰"))

    # -- price history --------------------------------------------------------
    tl = db.price_timeline(pid)
    if len(tl) >= 2:
        steps = " → ".join(f'{format_price(e["price_per_acre"])}' for e in tl)
        first, last = tl[0]["price_per_acre"], tl[-1]["price_per_acre"]
        pct = (last - first) / first * 100 if first else 0
        body.append(card("Price history", (
            f'<div style="font-size:16px;font-weight:650;margin-bottom:8px">'
            f'{esc(steps)}</div>'
            f'<div style="font-size:12.5px;color:#6a6a66">'
            f'{pct:+.0f}% since first observed on {esc(tl[0]["date"])} · '
            f'{len(tl)} recorded changes</div>'
            + (warning_box(
                "The seller has already demonstrated the asking price was not "
                "the real price. This is the strongest negotiating signal this "
                "system produces.", "good", "Possible negotiation opportunity")
               if last < first else "")), "📉"))

    # -- motivation -----------------------------------------------------------
    body.append(card("Seller motivation", (
        f'<div style="margin-bottom:10px">'
        f'{badge(motiv["level"].replace("_", " ").title(), "good" if motiv["level"] == "HIGHLY_MOTIVATED" else "watch" if motiv["level"] == "POSSIBLY_MOTIVATED" else "muted")}'
        f'</div>'
        f'<p style="font-size:12.5px;line-height:1.6;margin:0 0 12px">'
        f'{esc(motiv["rationale"])}</p>'
        + bullets(motiv["signals"], icon="•")
        + f'<p style="font-size:11.5px;color:#8a8880;margin:14px 0 0;'
          f'line-height:1.5">{esc(motiv["caveat"])}</p>'), "🤝"))

    # -- deal breakdown -------------------------------------------------------
    body.append(card("Deal score breakdown", data_table(
        ["Factor", "Weight", "Earned", "Why"],
        [[esc(b["factor"]), f'{b["weight"]}%', f'{b["points"]}',
          esc(b["why"])] for b in deal["breakdown"]],
        align_right=(1, 2)) +
        f'<p style="font-size:12.5px;margin:12px 0 0"><b>Total {deal["raw_score"]}'
        f'</b> → <b>{deal["score"]}/100</b> after gates · Category '
        f'{deal["category"]} ({deal["category_name"]}) — {esc(deal["category_meaning"])}'
        f'</p>', "🎯"))

    # -- the three checklists -------------------------------------------------
    missing = a["missing_information"]
    miss_html = ""
    for pri, colour in (("CRITICAL", "#791F1F"), ("HIGH", "#633806"),
                        ("MEDIUM", "#3a3a37")):
        items = [m for m in missing if m["priority"] == pri]
        if items:
            miss_html += (f'<div style="font-size:11px;color:#6a6a66;'
                          f'margin:14px 0 6px;text-transform:uppercase;'
                          f'letter-spacing:0.04em">{pri}</div>'
                          + bullets([m["item"] for m in items], colour, icon="?"))
    body.append(card("Missing information — what to ask", miss_html
                     or '<p style="color:#8a8880">Nothing outstanding.</p>', "❓"))

    visit = a["site_visit_checklist"]
    areas = {}
    for item in visit:
        areas.setdefault(item["area"], []).append(item["item"])
    visit_html = "".join(
        f'<div style="font-size:11px;color:#6a6a66;margin:14px 0 6px;'
        f'text-transform:uppercase;letter-spacing:0.04em">{esc(area)}</div>'
        + bullets(items, icon="☐") for area, items in areas.items())
    body.append(card("Site-visit checklist", visit_html, "👣"))

    body.append(card("Documents to obtain and verify independently",
                     bullets(a["document_checklist"], icon="☐")
                     + '<div style="font-size:11px;color:#6a6a66;margin:16px 0 6px;'
                       'text-transform:uppercase;letter-spacing:0.04em">'
                       'Standing items</div>'
                     + bullets(legal["standing_items"], "#633806", icon="•"), "📜"))

    # -- workflow -------------------------------------------------------------
    status_opts = "".join(
        f'<option value="{s}"{" selected" if prop.get("status") == s else ""}>{s}</option>'
        for s in ("NEW", "SHORTLISTED", "CONTACTED", "DOCUMENTS_REQUESTED",
                  "VISITED", "LAWYER_REVIEW", "NEGOTIATING", "ARCHIVED", "REJECTED"))
    notes_html = bullets(
        [f'{n["at"][:10]} · {n["text"]}' for n in reversed(prop.get("human_notes", []))],
        icon="•")
    body.append(card("Your workflow", (
        f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;'
        f'margin-bottom:14px">'
        f'<span style="font-size:12px;color:#6a6a66">Stage</span>'
        f'<select id="st" style="width:auto">{status_opts}</select>'
        f'<button onclick="setStatus()">Update</button></div>'
        f'<textarea id="note" placeholder="Add a note — what the seller said, '
        f'what you saw, what to do next"></textarea>'
        f'<div style="margin-top:9px"><button onclick="addNote()">Add note</button>'
        f'</div>'
        f'<div style="font-size:11px;color:#6a6a66;margin:18px 0 6px;'
        f'text-transform:uppercase;letter-spacing:0.04em">History</div>'
        f'{notes_html}'), "✅"))

    # -- verification form ----------------------------------------------------
    fields = ("summer_yield", "borewell_depth_ft", "water_sources", "acres",
              "survey_number", "road_surface", "electricity", "mentions_rtc",
              "mentions_ec", "mentions_mutation", "mentions_sale_deed",
              "neighbouring_houses", "mobile_signal", "water_tested",
              "flood_risk", "caretaker")
    fopts = "".join(f'<option value="{f}">{f}</option>' for f in fields)
    body.append(card("Record something you verified", (
        '<p style="font-size:12.5px;line-height:1.6;color:#3a3a37;margin:0 0 14px">'
        'This is how a property graduates. Recording a verified fact replaces the '
        'seller\'s claim and every score recomputes against the stronger evidence — '
        'the water cap lifts, the legal screen can move off UNKNOWN, and the deal '
        'score moves on its own.</p>'
        f'<div style="display:grid;gap:9px;grid-template-columns:1fr 1fr">'
        f'<select id="vf">{fopts}</select>'
        f'<select id="vc"><option value="VERIFIED">✅ Verified (document read)</option>'
        f'<option value="SITE_VISIT">👣 Seen on site</option>'
        f'<option value="OBSERVED_FROM_MEDIA">📷 Seen in photo/video</option>'
        f'<option value="THIRD_PARTY">🗣 Third party told me</option></select></div>'
        '<div style="margin-top:9px"><input type="text" id="vv" '
        'placeholder="Value — e.g. 2 inch sustained through May"></div>'
        '<div style="margin-top:9px"><input type="text" id="vs" '
        'placeholder="Source — e.g. Site visit 20 Aug, pump run 45 min"></div>'
        '<div style="margin-top:9px"><button onclick="verify()">Record</button></div>'
    ), "🔬"))

    js = f"""
    const PID = {pid!r};
    async function post(url, data) {{
      const r = await fetch(url, {{method:'POST',
        headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(data)}});
      return r.json();
    }}
    async function setStatus() {{
      await post('/api/status', {{id:PID, status:document.getElementById('st').value}});
      location.reload();
    }}
    async function addNote() {{
      const t = document.getElementById('note').value.trim();
      if(!t) return;
      await post('/api/note', {{id:PID, text:t}});
      location.reload();
    }}
    async function verify() {{
      const v = document.getElementById('vv').value.trim();
      const s = document.getElementById('vs').value.trim();
      if(!v || !s) {{ alert('A value and a source are both required — a verified '
        + 'claim with no cited source is how unverified things become verified.');
        return; }}
      await post('/api/verify', {{id:PID, field:document.getElementById('vf').value,
        value:v, source:s, confidence:document.getElementById('vc').value}});
      location.reload();
    }}
    """
    return "".join(body), js


# ------------------------------------------------------------- add ------

def add_page(params=None):
    body = [
        '<h1>Add a listing</h1>',
        '<p class="sub">Paste listing text from anywhere — a portal, a broker\'s '
        'WhatsApp message, a YouTube description, a photo you transcribed. It goes '
        'through the same pipeline regardless of where it came from.</p>',
        card("Paste a listing", (
            '<div style="display:grid;gap:9px;grid-template-columns:1fr 1fr;'
            'margin-bottom:9px">'
            '<input type="text" id="src" placeholder="Source — e.g. MagicBricks, '
            'WhatsApp from Ramesh, YouTube">'
            '<input type="url" id="url" placeholder="Source URL (optional)">'
            '</div>'
            '<textarea id="txt" placeholder="Paste the full listing text here — '
            'price, extent, village, water, road, contact. The more complete the '
            'text, the more the extractor can read."></textarea>'
            '<div style="margin-top:10px;display:flex;gap:9px;flex-wrap:wrap">'
            '<button onclick="add(false)">Add listing</button>'
            '<button class="sec" onclick="add(true)">Add several (blank line '
            'between each)</button></div>'
            '<div id="out" style="margin-top:16px"></div>'), "📥"),
        card("Fetch a URL", (
            '<p style="font-size:12.5px;line-height:1.6;color:#3a3a37;margin:0 0 12px">'
            'Only works for sources that permit automated access. Every fetch is '
            'checked against the site\'s robots.txt first and refused if it is '
            'disallowed, unreadable, or if the source\'s terms prohibit automated '
            'collection — which covers every major property portal. For those, open '
            'the page yourself and paste the text above.</p>'
            '<input type="url" id="furl" placeholder="https://...">'
            '<div style="margin-top:9px"><button onclick="fetchUrl()">Fetch</button>'
            '</div><div id="fout" style="margin-top:14px"></div>'), "🌐"),
    ]
    js = """
    async function post(u,d){const r=await fetch(u,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
      return r.json();}
    function box(html,kind){
      const c={good:['#E1F5EE','#085041'],bad:['#FCEBEB','#791F1F'],
               info:['#E6F1FB','#0C447C']}[kind||'info'];
      return '<div style="background:'+c[0]+';color:'+c[1]+';padding:12px 14px;'
        +'border-radius:7px;font-size:12.5px;line-height:1.6;margin-bottom:9px">'
        +html+'</div>';
    }
    async function add(batch){
      const t=document.getElementById('txt').value.trim();
      if(!t){return;}
      const out=document.getElementById('out');
      out.innerHTML=box('Working...');
      const r=await post('/api/ingest',{text:t,batch:batch,
        source:document.getElementById('src').value||'manual',
        url:document.getElementById('url').value});
      const results = r.results || [r];
      out.innerHTML = results.map(function(x){
        if(!x.ok) return box('❌ '+(x.error||'Failed'),'bad');
        var h = (x.is_new?'✅ New property recorded':'🔗 Merged into an existing property')
          +' — <a href="/property?id='+x.property_id+'">open it</a>';
        if(x.match_reasons && x.match_reasons.length)
          h += '<div style="margin-top:6px;font-size:11.5px">Matched on: '
            + x.match_reasons.join('; ')+'</div>';
        if(x.changes && x.changes.length)
          h += '<div style="margin-top:6px;font-size:11.5px">'+x.changes.join('<br>')+'</div>';
        if(x.suggestions && x.suggestions.length)
          h += '<div style="margin-top:6px;font-size:11.5px">⚠️ Possible duplicates '
            + 'not merged automatically — check them.</div>';
        return box(h, x.is_new?'good':'info');
      }).join('');
      if(!batch) document.getElementById('txt').value='';
    }
    async function fetchUrl(){
      const u=document.getElementById('furl').value.trim();
      if(!u) return;
      const out=document.getElementById('fout');
      out.innerHTML=box('Checking robots.txt and fetching...');
      const r=await post('/api/fetch',{url:u});
      out.innerHTML = r.ok
        ? box('✅ Fetched and added — <a href="/property?id='+r.property_id+'">open it</a>','good')
        : box('🚫 '+(r.error||'Failed'), r.refused?'info':'bad');
    }
    """
    return "".join(body), js


# --------------------------------------------------------- discover -----

def discover_page(params=None):
    wl = ingest_mod.worklist()
    body = [
        '<h1>Discover</h1>',
        '<p class="sub">The keyword × village search matrix, as links to open.</p>',
        card("How discovery actually works here",
             f'<p style="font-size:12.5px;line-height:1.65;white-space:pre-wrap;'
             f'margin:0">{esc(wl["coverage_note"])}</p>', "📖"),
    ]

    for key, group in wl["sources"].items():
        policy_badge = {
            "OPEN": badge("Auto-fetchable", "good", "small"),
            "API_REQUIRED": badge("Needs your API key", "watch", "small"),
            "MANUAL_ONLY": badge("Manual only", "info", "small"),
        }.get(group["policy"], badge(group["policy"], "muted", "small"))

        links = "".join(
            f'<a href="{esc(u["url"])}" target="_blank" rel="noopener" '
            f'style="display:inline-block;padding:4px 9px;margin:0 5px 5px 0;'
            f'background:#f4f2ec;border-radius:5px;font-size:11.5px;'
            f'text-decoration:none;color:#3a3a37">{esc(u["query"])}</a>'
            for u in group["urls"][:54])

        body.append(card(group["name"],
                         f'<p style="font-size:12px;color:#6a6a66;line-height:1.6;'
                         f'margin:0 0 12px">{esc(group["note"])}</p>{links}',
                         right=policy_badge))

    body.append(card("Discovery log", data_table(
        ["When", "Action", "Detail", "Outcome"],
        [[esc(e.get("at", "")[:16]), esc(e.get("action", "")),
          esc((e.get("url") or e.get("source") or "")[:70]),
          esc((e.get("reason") or e.get("robots") or
               ("new" if e.get("is_new") else "merged"))[:80])]
         for e in ingest_mod.discovery_log(60)]) +
        '<p style="font-size:11.5px;color:#8a8880;margin:10px 0 0;line-height:1.5">'
        'Every fetch attempt is logged with the robots.txt decision that permitted '
        'or refused it — including the refusals. Where a listing came from is part '
        'of the record.</p>', "📜"))

    return "".join(body), ""


# ------------------------------------------------------- price drops ----

def price_drops_page(params=None):
    drops = pipeline.price_drops(min_pct=1.0)
    body = [
        '<h1>Price drops</h1>',
        '<p class="sub">Properties whose asking price has fallen since first '
        'discovery.</p>',
        card("Why this page is the point of the whole system",
             '<p style="font-size:12.5px;line-height:1.65;margin:0">'
             'Finding a hundred new listings is easy and mostly worthless. Noticing '
             'that the parcel on Hunsur Road you saw at ₹42L/acre six months ago is '
             'now ₹35L/acre with "urgent sale" attached is worth far more — the '
             'seller has already shown you the list price was not the real price, '
             'and roughly where their reserve sits. That only exists if the same '
             'parcel resolves to the same record every time it is re-discovered, '
             'which is what the deduplication layer is for.</p>', "💡"),
    ]
    if drops:
        body.append(card("", data_table(
            ["Property", "Acres", "First", "Current", "Drop", "Steps", "Days tracked",
             "Deal", "Flag"],
            [[property_link(d["property_id"], d["village"]),
              format_area(d["acres"]), format_price(d["first_price"]),
              f'<b>{format_price(d["current_price"])}</b>',
              badge(f'−{d["drop_pct"]:.0f}%', "good", "small"),
              str(d["steps"]), str(d["days_tracked"] or "—"),
              score_pill((d["scores"] or {}).get("deal")),
              badge("Negotiation opportunity", "good", "small")]
             for d in drops], align_right=(1, 2, 3, 4, 5, 6, 7)), pad="6px 8px 12px"))
    else:
        body.append(card("", '<p style="color:#8a8880;font-size:12.5px;margin:0">'
                             'No drops recorded yet. This fills in over months as '
                             'the same properties are re-discovered — re-add '
                             'listings you see again rather than skipping them, '
                             'even when nothing looks changed.</p>'))
    return "".join(body), ""


# ---------------------------------------------------------- workflow ----

def workflow_page(params=None):
    rows = _rows()
    stages = ("NEW", "SHORTLISTED", "CONTACTED", "DOCUMENTS_REQUESTED", "VISITED",
              "LAWYER_REVIEW", "NEGOTIATING", "ARCHIVED", "REJECTED")
    by_stage = {s: [] for s in stages}
    for pid, prop, cs, sc in rows:
        by_stage.setdefault(prop.get("status", "NEW"), []).append((pid, prop, cs, sc))

    body = [
        '<h1>Workflow</h1>',
        '<p class="sub">Where each property sits in the human process.</p>',
        card("The pipeline",
             '<p style="font-size:12.5px;line-height:1.7;margin:0 0 10px">'
             'DISCOVER → EXTRACT → DEDUPLICATE → GEOLOCATE → SCORE → RISK SCREEN → '
             '<b>HUMAN REVIEW</b> → SELLER CONTACT → DOCUMENT COLLECTION → SITE '
             'VISIT → LAWYER VERIFICATION → SURVEYOR VERIFICATION → PRICE '
             'NEGOTIATION → PURCHASE DECISION</p>'
             '<p style="font-size:12.5px;line-height:1.65;color:#3a3a37;margin:0">'
             'Everything up to HUMAN REVIEW is automated. Nothing past it is, and '
             'nothing in this system will ever recommend buying land. Past that '
             'point every stage is a person doing something in the physical world — '
             'this page only records that it happened.</p>', "🔄"),
    ]
    for stage in stages:
        items = by_stage.get(stage) or []
        if not items and stage not in ("NEW", "SHORTLISTED"):
            continue
        body.append(card(f"{stage.replace('_', ' ').title()} ({len(items)})",
                         data_table(
                             ["Property", "Acres", "₹/acre", "Deal", "Legal", "Last seen"],
                             [[property_link(pid, cs.value("village") or "—"),
                               format_area(cs.value("acres")),
                               format_price(_ppa(cs)) if _ppa(cs) else "—",
                               score_pill(sc.get("deal")),
                               badge(sc.get("legal_risk", "—"),
                                     LEGAL_STATUS.get(sc.get("legal_risk"), "muted"),
                                     "small"),
                               esc((prop.get("last_seen") or "")[:10])]
                              for pid, prop, cs, sc in
                              sorted(items, key=lambda r: -(r[3].get("deal") or 0))],
                             align_right=(1, 2, 3)), pad="6px 8px 12px"))
    return "".join(body), ""


# ------------------------------------------------------------- about ----

def about_page(params=None):
    from findfarms.core.claims import LEVELS, LABEL, SCORE_WEIGHT
    ladder = data_table(
        ["Confidence", "Means", "Scoring weight"],
        [[badge(f"{LABEL[l][0]} {LABEL[l][1]}",
                "good" if l in ("VERIFIED", "SITE_VISIT") else
                "info" if l == "OBSERVED_FROM_MEDIA" else
                "muted" if l == "UNKNOWN" else "watch", "small"),
          esc(d), f"{SCORE_WEIGHT[l]:.0%}"]
         for l, d in (
             ("VERIFIED", "A document was read, or a professional confirmed it."),
             ("SITE_VISIT", "You or someone you sent physically observed it."),
             ("OBSERVED_FROM_MEDIA", "Visible in a listing photo or video."),
             ("THIRD_PARTY", "A neighbour or local official said so."),
             ("SELLER_CLAIM", "The listing said so. The default."),
             ("INFERRED", "This system computed it."),
             ("UNKNOWN", "No information — distinct from a 'no'."))],
        align_right=(2,))

    return "".join([
        '<h1>How this works</h1>',
        '<p class="sub">And, more importantly, what it does not do.</p>',

        card("The core idea", (
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            'A land listing is mostly assertions by someone who profits from you '
            'believing them. The usual failure of a property tool is that those '
            'assertions get stored in a field called <code>water_source</code> and '
            'become indistinguishable from facts — six weeks later a property '
            'scores 88 and nobody can say why.</p>'
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            'So nothing here is stored as a bare value. Every field carries its '
            'source and a confidence level, and the scoring engines read the '
            'confidence, not just the value. A seller-claimed borewell and a '
            'borewell you watched run for 45 minutes are the same word and must '
            'never be the same score.</p>'
            '<p style="font-size:13px;line-height:1.7;margin:0">'
            'That is also why verifying something visibly moves the numbers: record '
            'a pump test and the water cap lifts, record an EC and the legal screen '
            'can leave UNKNOWN. The scores are recomputed from stored claims every '
            'time a page loads, never frozen at import.</p>'), "🎯"),

        card("The confidence ladder", ladder, "📊"),

        card("What it will not do", (
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            '<b>It will not tell you a title is safe.</b> The legal screen reads '
            'advertisements, not documents. It can raise concerns; it can never '
            'clear one. LOW risk is unreachable from a listing by construction — it '
            'requires documents recorded at verified confidence. Most properties '
            'will sit at UNKNOWN forever, and that is the honest answer.</p>'
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            '<b>It will not recommend buying anything.</b> The pipeline stops at '
            'human review. Everything past it — contacting a seller, collecting '
            'documents, visiting, engaging a lawyer and a surveyor, negotiating — '
            'is a person acting in the world.</p>'
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            '<b>It will not bypass access controls.</b> No credentials are stored '
            'anywhere in this codebase, so it cannot log in even by accident. Every '
            'fetch passes a robots.txt gate that fails closed, and sources whose '
            'terms prohibit automated collection are refused before the gate is '
            'even reached.</p>'
            '<p style="font-size:13px;line-height:1.7;margin:0">'
            '<b>It will not claim a market value.</b> Below three comparables it '
            'returns UNKNOWN and says so. Everything it does compare is an asking '
            'price, not a recorded sale.</p>'), "🚫"),

        card("Why the gates beat the weights", (
            '<p style="font-size:13px;line-height:1.7;margin:0 0 12px">'
            'The deal score is weighted as the brief specifies — legal 25%, water '
            '25%, agriculture 15%, location 10%, price 10%, retirement 10%, '
            'optionality 5%. But a weighted average always lets a strong factor '
            'carry a fatal one. So gates are applied on top:</p>'
            '<ul style="font-size:12.5px;line-height:1.7;margin:0 0 12px;'
            'padding-left:20px">'
            '<li>A legal hard stop forces DO NOT PROCEED and drops the property '
            'out of every ranked list. An unwindable title is not a discount.</li>'
            '<li>UNKNOWN legal risk caps the score at 74, so nothing sourced from '
            'an advert can reach category A.</li>'
            '<li>A water score below 35 caps the deal at 55. Water is the one '
            'thing money cannot add to a parcel.</li></ul>'
            '<p style="font-size:13px;line-height:1.7;margin:0">'
            'The legal component is also scored on <em>evidence held</em>, not on '
            'the absence of bad news — a listing that mentions no documents scores '
            'near zero there, not neutral. Otherwise the listings with the least '
            'information float to the top, because there is nothing to hold '
            'against them. That is the most common way these systems go '
            'wrong.</p>'), "⚖️"),

        card("Known limits", (
            '<ul style="font-size:12.5px;line-height:1.75;margin:0;padding-left:20px">'
            '<li><b>Driving distances are estimated, not routed.</b> Straight-line '
            'distance times a corridor circuity factor. Good to a few km; measure '
            'the real one on the visit.</li>'
            '<li><b>Village coordinates are approximate centroids.</b> A parcel can '
            'sit several km from its village centre. Nothing in the seed gazetteer '
            'has been field-verified.</li>'
            '<li><b>Hospital and market distances are town-level.</b> "12 km to a '
            'town with hospital facilities", not to a specific verified '
            'facility.</li>'
            '<li><b>Extraction is keyword-based.</b> Phrasing it has not seen '
            'becomes UNKNOWN rather than being guessed at — deliberate, but it '
            'means coverage gaps show up as missing fields.</li>'
            '<li><b>Comparables are asking prices.</b> Asking runs above achieved '
            'in this market. The bias largely cancels when comparing like with '
            'like, but the absolute level is inflated.</li>'
            '<li><b>Autonomous discovery covers almost nothing.</b> See the '
            'Discover page. Intake is mostly manual by design.</li></ul>'), "📐"),
    ]), ""
