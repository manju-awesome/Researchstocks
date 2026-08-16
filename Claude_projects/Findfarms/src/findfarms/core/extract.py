"""
extract.py
==========
Listing text -> a ClaimSet. Every field this produces is tagged SELLER_CLAIM
unless it was computed here, in which case it is INFERRED. Nothing this
module emits is ever a fact — it is a structured record of what someone
wrote in an advertisement.

Design: deterministic keyword and pattern matching, no LLM. Two reasons.
First, the output feeds scores that gate a multi-crore decision, and a
deterministic extractor is auditable — when a property scores 84 you can
point at the exact phrase that earned each point. Second, an LLM asked to
"extract the water source" will happily smooth "borewell was there earlier"
into `water_source: borewell`, which is precisely the claim-to-fact laundering
this system is built to prevent.

The cost is recall: phrasing this module hasn't seen becomes UNKNOWN rather
than being guessed at. That is the intended trade — an UNKNOWN field shows up
on the property page as a question to ask the seller, which is a useful
output. A hallucinated field shows up as a score.

Adding patterns is expected and easy: they are plain tuples at the top of
each section, in the order they are tried.
"""

from __future__ import annotations

import re
from datetime import date

from findfarms.core import units
from findfarms.core.claims import Claim, ClaimSet, seller, inferred, SELLER_CLAIM

# ------------------------------------------------------------ helpers ----

def _norm(text) -> str:
    """Lowercase, collapse whitespace, normalise the punctuation listings use."""
    if not text:
        return ""
    s = str(text).lower()
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = re.sub(r"[\r\n\t]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _has(text: str, *phrases) -> str | None:
    """First phrase present in text, else None. Returns the phrase so the
    caller can record *which* wording triggered a claim — the difference
    between 'borewell' and 'borewell can be dug' matters enormously and the
    property page shows the matched phrase for exactly that reason.

    Matching is word-bounded on the outer edges. Short domain words are
    substrings of ordinary words and of place names: "kere" (village tank)
    sits inside "Bilikere", "tank" inside "storage tank", "ec" inside
    "hectare". A phantom match here invents a water source or a document out
    of a village's name, which then scores.
    """
    for p in phrases:
        pat = p.strip()
        if not pat:
            continue
        left = r"\b" if pat[0].isalnum() else ""
        right = r"\b" if pat[-1].isalnum() else ""
        if re.search(left + re.escape(pat) + right, text):
            return p
    return None


def _context(text: str, phrase: str, width: int = 60) -> str:
    """Surrounding text for a matched phrase, for the evidence trail."""
    i = text.find(phrase)
    if i < 0:
        return ""
    return "..." + text[max(0, i - width): i + len(phrase) + width].strip() + "..."


# Phrases that negate whatever follows or precedes them. Without this,
# "no borewell" and "borewell" extract identically, which is the single
# most dangerous class of extraction bug in this domain.
_NEGATORS = ("no ", "not ", "without ", "n't ", "never ", "yet to ", "needs to be ",
             "can be ", "have to ", "has to ", "should be ", "must be ",
             "planning to ", "plan to ", "will be ", "to be dug", "absent")


def _followed_by_clear(text: str, phrase: str, window: int = 22) -> bool:
    """Catch the trailing form: 'dispute free', 'litigation free', 'no
    encumbrance'. The negator sits AFTER the risk word, so the backwards
    check in `_negated` misses it."""
    i = text.find(phrase)
    if i < 0:
        return False
    after = text[i + len(phrase): i + len(phrase) + window]
    return any(w in after for w in (" free", "-free", " cleared", " settled",
                                    " resolved", " nil", " none"))


def _negated(text: str, phrase: str, window: int = 28) -> bool:
    """Whether a matched phrase sits inside a negation.

    Looks backwards from the match — "no borewell", "borewell can be dug",
    "yet to dig a borewell". The forward check catches the Indian-listing
    idiom "borewell can be arranged", which means there is no borewell.
    """
    i = text.find(phrase)
    if i < 0:
        return False
    before = text[max(0, i - window): i]
    after = text[i + len(phrase): i + len(phrase) + window]
    if any(n in before for n in _NEGATORS):
        return True
    return any(n in after for n in ("can be dug", "can be arranged", "to be dug",
                                    "not available", "is not there", "yet to"))


# ------------------------------------------------------------- fields ----

_WATER_PATTERNS = (
    ("canal",         ("canal", "nala water", "irrigation channel", "kalve",
                       "command area", "vc canal", "cauvery canal")),
    ("river",         ("river", "kaveri", "cauvery", "kabini", "kapila",
                       "riverside", "river front", "river facing")),
    ("open_well",     ("open well", "openwell", "kalyani", "bavi", "dug well")),
    ("borewell",      ("borewell", "bore well", "bore-well", "borwell",
                       "tube well", "tubewell", "kolave")),
    # "tank" here means a village irrigation tank (kere), not a storage tank.
    # Matching bare "tank" pulled in "water storage tank" and invented a water
    # body, so the phrases are specific and the storage sense is excluded
    # below before this list is consulted.
    ("lake_tank",     ("lake", "irrigation tank", "village tank", "kere",
                       "pond", "check dam", "kunte")),
    ("rain_fed",      ("rain fed", "rainfed", "rain-fed", "khushki", "dry land",
                       "dryland")),
)

_CROP_PATTERNS = (
    "coconut", "arecanut", "areca", "supari", "mango", "sapota", "chikoo",
    "banana", "sugarcane", "paddy", "ragi", "maize", "jowar", "cotton",
    "turmeric", "ginger", "coffee", "pepper", "silver oak", "teak", "sandalwood",
    "tamarind", "jackfruit", "guava", "pomegranate", "vegetables", "flowers",
    "mulberry", "cashew", "lemon", "sunflower", "groundnut", "tur", "avare",
)

_SOIL_PATTERNS = (
    ("red_soil",      ("red soil", "red loam", "kempu mannu")),
    ("black_soil",    ("black soil", "black cotton", "karé mannu", "kari mannu")),
    ("sandy",         ("sandy soil", "sandy loam", "sand")),
    ("loam",          ("loamy", "loam soil", "fertile soil", "alluvial")),
    ("rocky",         ("rocky", "stony", "gravel", "murram", "hard soil")),
)


def extract_water(text: str, cs: ClaimSet) -> None:
    """Water sources named in the listing, negation-aware."""
    found = []
    # Storage vessels read as water bodies if left in. Blanked before the
    # source scan so "water storage tank" cannot become a village tank, and
    # storage is picked up separately further down where it belongs.
    scan = text
    for phrase in ("water storage tank", "storage tank", "water tank",
                   "sump tank", "overhead tank", "syntex tank", "sintex tank"):
        scan = scan.replace(phrase, " __storage__ ")

    for label, phrases in _WATER_PATTERNS:
        hit = _has(scan, *phrases)
        if not hit:
            continue
        # Negation and context are read off `scan`, not `text`: the blanking
        # above shifts character offsets, so mixing the two would quote the
        # wrong span back to the user as evidence.
        if _negated(scan, hit):
            cs.add(f"water_{label}_absent", Claim(
                value=True, source=f'listing says "{_context(scan, hit, 30)}"',
                confidence=SELLER_CLAIM,
                note=f"Listing appears to state there is NO {label.replace('_', ' ')}."))
            continue
        found.append(label)
        cs.add(f"water_{label}", Claim(
            value=True, source=f'listing: "{hit}"', confidence=SELLER_CLAIM,
            note=_context(scan, hit)))
    if found:
        cs.add("water_sources", seller(", ".join(found), "listing keywords"))

    # Borewell depth. Feet is the local unit; the number is worth capturing
    # because a 200 ft borewell and an 850 ft borewell in the same village
    # say opposite things about the water table.
    m = re.search(r"(\d{2,4})\s*(?:ft|feet|foot|adi)\b[^.]{0,25}(?:bore|well|depth)", text)
    if not m:
        m = re.search(r"(?:bore\s?well|borewell|depth)[^.]{0,25}?(\d{2,4})\s*(?:ft|feet|foot|adi)\b", text)
    if m:
        cs.add("borewell_depth_ft", seller(int(m.group(1)), "listing"))

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|inches|\")\s*(?:water|yield|pipe)", text)
    if m:
        cs.add("borewell_yield_inches", seller(m.group(1) + " inch", "listing"))

    m = re.search(r"(\d+)\s*(?:no\.?s?\.?\s*)?(?:bore\s?wells|borewells)", text)
    if m:
        cs.add("borewell_count", seller(int(m.group(1)), "listing"))
    elif cs.get("water_borewell").known:
        cs.add("borewell_count", inferred(1, "listing mentions a borewell, count not stated"))

    if _has(text, "3 phase", "three phase", "3-phase"):
        cs.add("three_phase_power", seller(True, "listing"))
        # Three-phase implies a connection exists. Recorded separately so
        # the retirement scorer doesn't have to know about pump wiring.
        cs.add("electricity", seller(True, "listing mentions 3-phase supply"))
    if _has(text, "pump set", "pumpset", "submersible", "motor"):
        cs.add("pump", seller(True, "listing"))
    hit = _has(text, "drip irrigation", "drip system", "sprinkler")
    if hit:
        cs.add("irrigation_system", seller(hit, "listing"))
    hit = _has(text, "water tank", "sump", "farm pond", "water storage")
    if hit:
        cs.add("water_storage", seller(hit, "listing"))


def extract_agriculture(text: str, cs: ClaimSet) -> None:
    # Word-bounded: short crop names are substrings of ordinary words
    # ("tur" inside "agricultural", "avare" inside "aware"), and a phantom
    # crop inflates the agriculture score off a word the seller never wrote.
    crops = [c for c in _CROP_PATTERNS
             if re.search(r"\b" + re.escape(c) + r"\b", text) and not _negated(text, c)]
    if crops:
        cs.add("crops", seller(", ".join(sorted(set(crops))), "listing keywords"))

    for label, phrases in _SOIL_PATTERNS:
        hit = _has(text, *phrases)
        if hit:
            cs.add("soil", seller(label.replace("_", " "), f'listing: "{hit}"'))
            break

    m = re.search(r"(\d{2,5})\s*(?:nos\.?\s*)?(?:coconut|arecanut|areca|mango|"
                  r"sapota|silver oak|teak|trees)", text)
    if m:
        cs.add("tree_count", seller(int(m.group(1)), "listing"))

    hit = _has(text, "fully cultivated", "under cultivation", "cultivated",
               "yielding", "bearing", "income generating", "produces")
    if hit and not _negated(text, hit):
        cs.add("under_cultivation", seller(True, f'listing: "{hit}"'))
    hit = _has(text, "barren", "fallow", "uncultivated", "vacant land",
               "not cultivated", "empty land")
    if hit:
        cs.add("under_cultivation", seller(False, f'listing: "{hit}"'))

    hit = _has(text, "organic", "natural farming", "zbnf")
    if hit:
        cs.add("organic", seller(True, f'listing: "{hit}"'))

    # Terrain, ordered most-specific first. "undulating" is split out from
    # "sloping" rather than lumped with it, because the two score in opposite
    # directions for water harvesting — see watershed.py.
    for label, phrases in (
            ("gentle_slope", ("gentle slope", "slight slope", "mild slope",
                              "gentle gradient", "slightly sloping",
                              "gentle fall", "slopes gently")),
            ("undulating", ("undulating", "undulation", "rolling", "uneven land",
                            "ups and downs", "up and down", "gently rolling")),
            ("steep", ("steep", "hilly", "hillock", "steep slope", "hill slope")),
            ("flat", ("flat land", "plain land", "level land", "flat terrain",
                      "levelled land", "plain terrain")),
            ("sloping", ("sloping", "slope", "gradient", "inclined"))):
        hit = _has(text, *phrases)
        if hit:
            cs.add("terrain", seller(label.replace("_", " "), f'listing: "{hit}"'))
            cs.add("undulation", seller(label, f'listing: "{hit}"'))
            break

    # Elevation difference across the parcel, when stated. The single most
    # useful harvesting number a listing can carry, and rarely present.
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:ft|feet|m|meter|metre)s?\s*"
                  r"(?:of\s*)?(?:fall|drop|slope|gradient|elevation difference)", text)
    if m:
        cs.add("elevation_fall", seller(m.group(0).strip(), "listing"))

    # Existing water-harvesting structures. Worth real points in the
    # watershed score and almost never mentioned, so each one found is a
    # genuine differentiator.
    # Plurals are listed explicitly: `_has` matches on word boundaries, so
    # "contour bund" does not match "contour bunds". Longest form first so the
    # plural wins where both would match.
    for key, phrases in (
            ("farm_pond", ("farm ponds", "farm pond", "farmpond", "krishi honda",
                           "water pond", "percolation pond", "storage pond")),
            ("contour_bunds", ("contour bunds", "contour bund", "contour bunding",
                               "bunding done", "field bunds", "field bund",
                               "contour trenches", "contour trench")),
            ("recharge_pit", ("recharge pits", "recharge pit", "borewell recharge",
                              "recharge structure", "soak pit",
                              "rainwater harvesting", "rain water harvesting")),
            ("check_dam", ("check dams", "check dam", "checkdam", "nala bund",
                           "gully plug"))):
        hit = _has(text, *phrases)
        if hit and not _negated(text, hit):
            cs.add(key, seller(True, f'listing: "{hit}"'))


def extract_access(text: str, cs: ClaimSet) -> None:
    hit = _has(text, "road facing", "road frontage", "main road", "highway facing",
               "touching road", "road touch", "front road")
    if hit and not _negated(text, hit):
        cs.add("road_frontage", seller(True, f'listing: "{hit}"'))

    # Allows a surface word between the width and "road" — "30 ft tar road"
    # is how these are actually written.
    m = re.search(r"(\d{1,3})\s*(?:ft|feet|foot)\s*(?:wide\s*)?"
                  r"(?:tar|bt|mud|kaccha|kutcha|gravel|asphalt|concrete|cc\s?)?\s*road", text)
    if m:
        cs.add("road_width_ft", seller(int(m.group(1)), "listing"))

    hit = _has(text, "tar road", "asphalt", "bt road", "black top", "concrete road")
    if hit:
        cs.add("road_surface", seller("tarred", f'listing: "{hit}"'))
    else:
        hit = _has(text, "mud road", "kaccha road", "kutcha road", "gravel road",
                   "dirt road", "mud track")
        if hit:
            cs.add("road_surface", seller("unpaved", f'listing: "{hit}"'),)

    hit = _has(text, "private road", "common road", "shared access", "through others land")
    if hit:
        cs.add("access_type", seller("private/shared", f'listing: "{hit}"'),)

    extract_main_road_distance(text, cs)

    for key, phrases in (("fencing", ("fenced", "fencing", "compound wall", "barbed wire")),
                         ("electricity", ("electricity", "power connection", "current",
                                          "electric connection", "transformer")),
                         ("farmhouse", ("farm house", "farmhouse", "house built",
                                        "villa", "cottage", "bungalow")),
                         ("shed", ("shed", "cattle shed", "store room", "godown")),
                         ("caretaker", ("caretaker", "watchman", "care taker", "maintained by"))):
        hit = _has(text, *phrases)
        if hit and not _negated(text, hit):
            cs.add(key, seller(True, f'listing: "{hit}"'))


# Words a listing uses for "a road that is actually maintained and tarred",
# as distinct from the lane the parcel happens to touch.
_MAIN_ROAD_WORDS = (r"main\s*road", r"highway", r"nh\s*\d*", r"sh\s*\d*",
                    r"state\s*highway", r"national\s*highway", r"ring\s*road",
                    r"tar\s*road", r"bt\s*road", r"black\s*top",
                    r"mysore\s*road", r"mysuru\s*road", r"district\s*road")


def extract_main_road_distance(text: str, cs: ClaimSet) -> None:
    """How far the parcel sits from a main tarred road, in metres.

    A distinct question from road frontage, and a more decisive one. Frontage
    only says the parcel touches *a* road; that road may be a single-track mud
    lane that becomes impassable in August. What determines whether an
    ambulance, a delivery or a seventy-year-old driver reaches the gate is the
    length of the unpaved last stretch.

    Sellers state this when it is good ("200 mtr from main road") and omit it
    when it is not — so an absent value is recorded as UNKNOWN and becomes a
    question, never assumed to be zero.
    """
    # Frontage on a main road: distance is zero.
    for w in _MAIN_ROAD_WORDS:
        if re.search(r"(?:touching|abutting|on the|facing|front(?:age)? (?:on|to))\s*"
                     + w, text) or re.search(w + r"\s*(?:facing|touch|frontage)", text):
            cs.add("main_road_distance_m", seller(
                0, f"listing describes frontage on a main road"))
            cs.add("main_road_frontage", seller(True, "listing"))
            return

    # "500 metres / 1.5 km from the main road", either word order.
    num = r"(\d+(?:\.\d+)?)"
    unit_m = r"(?:m|mt|mtr|mtrs|meter|meters|metre|metres)"
    unit_km = r"(?:km|kms|kilometer|kilometre)"

    for w in _MAIN_ROAD_WORDS:
        for unit, mult in ((unit_km, 1000.0), (unit_m, 1.0)):
            m = (re.search(num + r"\s*" + unit + r"\s*(?:away\s*)?(?:from|to|off)?\s*"
                           r"(?:the\s*)?" + w, text)
                 or re.search(w + r"\s*(?:is\s*)?(?:just\s*)?" + num + r"\s*" + unit,
                              text))
            if m:
                try:
                    metres = float(m.group(1)) * mult
                except (TypeError, ValueError):
                    continue
                # A "main road" 40 km away is the seller describing the route
                # to Mysuru, not the parcel's approach.
                if metres > 15000:
                    continue
                cs.add("main_road_distance_m", seller(
                    round(metres), f'listing: "{m.group(0).strip()}"'))
                return

    # Qualitative forms, converted conservatively — the generous reading of a
    # vague phrase is the seller's reading, and this is the one number where
    # being wrong in their favour costs the most.
    hit = _has(text, "just off the main road", "off the main road",
               "near main road", "close to main road", "walkable from main road")
    if hit:
        cs.add("main_road_distance_m", seller(
            500, f'listing: "{hit}" — no figure given, read conservatively as '
                 f'~500 m. Measure it.'))
        return

    hit = _has(text, "interior", "inside village", "deep inside", "off road")
    if hit:
        cs.add("main_road_distance_m", seller(
            1500, f'listing: "{hit}" — described as interior, read as ~1.5 km. '
                  f'Measure it.'))


def extract_legal_mentions(text: str, cs: ClaimSet) -> None:
    """Record document and title *mentions*. This does not assess them — that
    is legal.py's job — it only notes what the listing raised, so the risk
    screen has something to read and so 'documents never mentioned' is
    itself recorded as a finding."""
    docs = {
        "rtc": ("rtc", "pahani", "phani", "record of rights"),
        "mutation": ("mutation", "mutated", "khata transfer"),
        "survey_number": ("survey no", "survey number", "sy no", "sy.no", "s.no"),
        "ec": ("encumbrance", " ec ", "ec certificate", "nil ec"),
        "sale_deed": ("sale deed", "registered deed", "khata", "title deed"),
        "parent_document": ("parent document", "mother deed", "parent deed", "link document"),
        "conversion": ("dc converted", "converted land", "conversion order",
                       "na land", "non agricultural", "94cc", "e-swathu"),
        "clear_title": ("clear title", "clean title", "no dispute", "dispute free",
                        "litigation free", "no litigation"),
    }
    for key, phrases in docs.items():
        hit = _has(text, *phrases)
        if hit:
            cs.add(f"mentions_{key}", Claim(
                value=True, source=f'listing: "{hit.strip()}"', confidence=SELLER_CLAIM,
                note=_context(text, hit)))

    m = re.search(r"(?:survey|sy\.?)\s*(?:no\.?|number)?\s*[:\-]?\s*(\d+[/\d]*)", text)
    if m:
        cs.add("survey_number", seller(m.group(1), "listing"))

    # Risk words. Recorded here, weighted in legal.py.
    risks = {
        "grant_land": ("grant land", "granted land", "darkhast", "ptcl"),
        "government_land": ("gomala", "gomal", "government land", "sarkari",
                            "inam", "bhoodan", "kharab"),
        "forest_land": ("forest land", "forest boundary", "reserve forest",
                        "wildlife", "eco sensitive", "buffer zone"),
        "acquisition": ("acquisition", "acquired", "notification", "kiadb",
                        "muda", "road widening", "highway expansion", "ring road"),
        "dispute": ("dispute", "litigation", "court case", "partition",
                    "family settlement", "stay order", "civil suit"),
        "multiple_owners": ("joint owners", "multiple owners", "co-owners",
                            "brothers", "heirs", "khata holders"),
        "buffer": ("lake buffer", "river buffer", "raja kaluve", "buffer",
                   "nala buffer", "catchment"),
        "tenancy": ("tenant", "tenancy", "form 7", "form no 7", "occupancy right"),
    }
    for key, phrases in risks.items():
        hit = _has(text, *phrases)
        if not hit:
            continue
        # Negation matters more here than anywhere else in the extractor.
        # "no dispute", "litigation free" and "dispute free" are the single
        # most common phrases in these adverts, and without this check they
        # each register AS a dispute risk — turning the standard reassurance
        # every listing carries into a MEDIUM legal finding.
        if _negated(text, hit) or _followed_by_clear(text, hit):
            cs.add(f"risk_{key}_denied", Claim(
                value=True, source=f'listing: "{_context(text, hit, 30)}"',
                confidence=SELLER_CLAIM,
                note=f"The listing asserts there is no {key.replace('_', ' ')} "
                     f"issue. This is advertising copy, not evidence — it does "
                     f"not lower the assessed risk, and it does not raise it."))
            continue
        cs.add(f"risk_{key}", Claim(
            value=True, source=f'listing: "{hit.strip()}"', confidence=SELLER_CLAIM,
            note=_context(text, hit)))


_MOTIVATION_SIGNALS = {
    "HIGHLY_MOTIVATED": ("urgent sale", "urgently", "distress sale", "immediate sale",
                         "immediately sell", "quick sale", "must sell",
                         "price reduced", "reduced price", "negotiable heavily",
                         "final price reduced", "below market"),
    "POSSIBLY_MOTIVATED": ("family settlement", "partition", "inheritance",
                           "ancestral property", "relocating", "shifting abroad",
                           "settled abroad", "moving to", "not able to maintain",
                           "unable to maintain", "unused", "idle land",
                           "old age", "health reasons", "financial requirement",
                           "need money", "genuine buyers only", "direct owner",
                           "no brokers", "owner selling", "price negotiable"),
}


def extract_seller(text: str, cs: ClaimSet, raw_text: str = "") -> None:
    """Seller type and motivation language.

    Motivation is read from wording only. The brief is explicit that this must
    not become an inference about someone's personal circumstances — so the
    output records *which phrase the seller chose to publish*, and nothing
    about why. "Family settlement" in an advert is a negotiation-relevant fact
    about the advert; it is not a finding about a family.
    """
    hit = _has(text, "direct owner", "owner direct", "no broker", "no brokers",
               "without broker", "owner selling", "by owner", "genuine owner")
    if hit:
        cs.add("owner_direct", seller(True, f'listing: "{hit}"'))
    hit = _has(text, "broker", "agent", "consultancy", "realtors", "properties pvt",
               "real estate", "commission")
    if hit and not cs.get("owner_direct").known:
        cs.add("seller_type", seller("broker/agent", f'listing: "{hit}"'))

    for level, phrases in _MOTIVATION_SIGNALS.items():
        matched = [p for p in phrases if p in text]
        if matched:
            cs.add("motivation_signals", seller(", ".join(matched), "listing language"))
            cs.add("motivation_level_hint", inferred(
                level, "listing language",
                note="Read from the advert's own wording only — not an inference "
                     "about the seller's circumstances."))
            break

    # Contact details, only if the listing published them. Stored so a
    # shortlisted property is actionable, and used as a strong dedup key.
    src = raw_text or text
    m = re.search(r"(?:\+?91[\-\s]?)?([6-9]\d{9})\b", re.sub(r"[\s\-]", "", src))
    if m:
        cs.add("phone", seller(m.group(1), "listing (publicly posted)"))

    hit = _has(text, "whatsapp", "whats app", "wa.me")
    if hit:
        cs.add("whatsapp_available", seller(True, "listing"))


def extract_price_and_size(text: str, cs: ClaimSet, raw_text: str = "") -> None:
    """Price and area, with the per-acre form worked out both ways.

    Listings quote either a total or a per-acre figure, sometimes both and
    occasionally inconsistently. Whichever is given, the other is derived and
    labelled INFERRED; when both are given and they disagree by more than 5%,
    that contradiction is recorded rather than resolved.
    """
    src = raw_text or text
    acres, how = units.parse_area(src)
    if acres is not None:
        cs.add("acres", seller(round(acres, 3), f"listing ({how})"))
        warn = units.area_sanity(acres)
        if warn:
            cs.add("area_warning", inferred(warn, "sanity check"))

    per_acre_stated = None
    m = re.search(r"([\d.,]+\s*(?:cr|crore|lakhs?|lacs?|l)\b)[^.]{0,20}"
                  r"(?:per\s*acre|/\s*acre|an acre|each acre)", text)
    if m:
        per_acre_stated = units.parse_price(m.group(1))
        if per_acre_stated:
            cs.add("price_per_acre_stated", seller(per_acre_stated, "listing"))

    total_stated = None
    m = re.search(r"(?:total|asking|price|cost|rate|selling at|expecting)"
                  r"[^.\d]{0,15}([\d.,]+\s*(?:cr|crore|lakhs?|lacs?|l)\b)", text)
    if m:
        cand = units.parse_price(m.group(1))
        # Guard against re-reading the per-acre figure as the total.
        if cand and cand != per_acre_stated:
            total_stated = cand
    if total_stated is None and per_acre_stated is None:
        total_stated = units.parse_price(text)
    if total_stated:
        cs.add("asking_price", seller(total_stated, "listing"))

    # Reconcile. The stated total governs when present; a derived one is
    # clearly labelled so nobody negotiates against a number we computed.
    if total_stated and acres:
        derived = units.price_per_acre(total_stated, acres)
        if per_acre_stated and derived:
            if abs(derived - per_acre_stated) / max(per_acre_stated, 1) > 0.05:
                cs.add("price_inconsistency", inferred(
                    f"listing's ₹/acre ({units.format_price(per_acre_stated)}) does not "
                    f"match total ÷ acres ({units.format_price(derived)})",
                    "cross-check",
                    note="Ask which figure is real and whether the acreage is the "
                         "registered extent or an approximation."))
        cs.add("price_per_acre", inferred(round(derived, 0), "asking price ÷ acres"))
        warn = units.price_sanity(total_stated, acres)
        if warn:
            cs.add("price_warning", inferred(warn, "sanity check"))
    elif per_acre_stated and acres:
        cs.add("price_per_acre", seller(per_acre_stated, "listing"))
        cs.add("asking_price", inferred(round(per_acre_stated * acres), "₹/acre x acres"))
    elif per_acre_stated:
        cs.add("price_per_acre", seller(per_acre_stated, "listing"))

    hit = _has(text, "negotiable", "nego", "slightly negotiable", "price negotiable")
    if hit:
        cs.add("negotiable", seller(True, f'listing: "{hit}"'))
    elif _has(text, "fixed price", "no negotiation", "non negotiable", "final price"):
        cs.add("negotiable", seller(False, "listing"))


def extract_location(text: str, cs: ClaimSet, raw_text: str = "") -> None:
    """Village/taluk mentions and any distance the seller asserted.

    Only records what the listing says. Resolving it to coordinates and
    computing a real distance happens in geo.py, deliberately separated so
    the seller's geography and ours never share a field.
    """
    from findfarms.core.geo import load_gazetteer, normalise_place

    g = load_gazetteer()
    src = raw_text or text
    hits = []
    for place in g["places"]:
        names = [place.get("name", "")] + list(place.get("aliases") or [])
        for n in names:
            if not n:
                continue
            if re.search(r"\b" + re.escape(n.lower()) + r"\b", text):
                hits.append(place)
                break
    # Prefer the most specific match: a listing naming both "Bannur" and
    # "Mysuru" is in Bannur, and Mysuru is the reference point it is being
    # sold against. Village entries beat taluk HQs beat the city.
    hits = [h for h in hits if normalise_place(h.get("name")) != "mysuru"] or hits
    if hits:
        hits.sort(key=lambda p: ("city" in (p.get("amenities") or []),
                                 "town" in (p.get("amenities") or [])))
        cs.add("village", seller(hits[0].get("name"), "listing (matched to gazetteer)"))
        if hits[0].get("taluk"):
            cs.add("taluk", seller(hits[0]["taluk"], "gazetteer"))
        if len(hits) > 1:
            cs.add("other_places_mentioned",
                   seller(", ".join(h.get("name") for h in hits[1:]), "listing"))

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilometer|kilometre)s?\s*"
                  r"(?:from|to|away from)?\s*(?:mysore|mysuru|city)?", text)
    if m:
        cs.add("seller_stated_distance", seller(m.group(0).strip(), "listing"))

    m = re.search(r"(\d+)\s*(?:min|mins|minutes)\s*(?:from|to|drive|away)", text)
    if m:
        cs.add("seller_stated_drive_time", seller(m.group(0).strip(), "listing"))

    # Seller's claimed distance to a river. Recorded as a claim only — the
    # system computes its own from the river polyline, and the two are shown
    # side by side rather than reconciled. "200 metres from the Kaveri" is
    # among the most oversold lines in these listings.
    for river in ("kaveri", "cauvery", "kabini", "kapila"):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(km|kms|m|mt|mtr|meters?|metres?)\s*"
                      r"(?:away\s*)?(?:from|to)?\s*(?:the\s*)?" + river, text)
        if not m:
            m = re.search(river + r"[^.]{0,25}?(\d+(?:\.\d+)?)\s*"
                          r"(km|kms|m|mt|mtr|meters?|metres?)\b", text)
        if m:
            cs.add("seller_stated_river_distance",
                   seller(f"{m.group(1)} {m.group(2)} from the {river.title()}",
                          "listing"))
            break

    # Coordinates, when a listing or a map link carries them.
    m = re.search(r"(1[12]\.\d{3,})\s*[,\s]\s*(7[5-8]\.\d{3,})", src)
    if m:
        cs.add("latitude", seller(float(m.group(1)), "listing/map link"))
        cs.add("longitude", seller(float(m.group(2)), "listing/map link"))


# --------------------------------------------------------------- main ----

def extract_listing(raw_text: str, source: str = "", source_url: str = "",
                    extra: dict | None = None) -> ClaimSet:
    """Turn one listing into a ClaimSet.

    `extra` is for fields the caller already has structured (a portal's own
    price field, a seller name from a form). Those still become SELLER_CLAIMs
    — a structured field from a listing site is no more verified than a
    sentence from the same listing.
    """
    text = _norm(raw_text)
    cs = ClaimSet()

    cs.add("source", Claim(value=source or "unspecified", source=source,
                           confidence="INFERRED"))
    if source_url:
        cs.add("source_url", Claim(value=source_url, source=source,
                                   confidence="INFERRED"))
    cs.add("date_discovered", Claim(value=date.today().isoformat(),
                                    source="findfarms", confidence="VERIFIED",
                                    note="Date this system first saw the listing."))
    cs.add("raw_text", Claim(value=(raw_text or "")[:8000], source=source,
                             confidence="INFERRED",
                             note="Verbatim listing text, kept for re-extraction."))

    if not text:
        return cs

    from findfarms.core.freshness import extract_posted_date
    extract_posted_date(raw_text or text, cs, extra)

    extract_price_and_size(text, cs, raw_text)
    extract_location(text, cs, raw_text)
    extract_water(text, cs)
    extract_agriculture(text, cs)
    extract_access(text, cs)
    extract_legal_mentions(text, cs)
    extract_seller(text, cs, raw_text)

    for k, v in (extra or {}).items():
        if isinstance(v, Claim):
            cs.add(k, v)
        elif v is not None and v != "":
            cs.add(k, seller(v, source or "structured listing field"))

    # A listing that names no documents at all is a finding in its own right,
    # not an absence of one — the legal screen reads this directly.
    doc_keys = ("mentions_rtc", "mentions_mutation", "mentions_ec",
                "mentions_sale_deed", "mentions_survey_number", "survey_number")
    if not any(cs.get(k).known for k in doc_keys):
        cs.add("no_documents_mentioned", inferred(
            True, "extraction",
            note="The listing names no title document, survey number or "
                 "encumbrance status. Normal for an advert; means the legal "
                 "screen has nothing to work with."))
    return cs
