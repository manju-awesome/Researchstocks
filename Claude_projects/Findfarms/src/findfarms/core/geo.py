"""
geo.py
======
Where the parcel actually is, computed independently of what the seller said.

The rule this module enforces: **the seller's stated distance is a claim, not
a measurement.** "25 minutes from Mysore" is the single most inflated number
in Indian land listings — it usually means 25 minutes at 2am with no traffic
from the city's outer edge, and the parcel is 38 km from anywhere you would
actually drive to. So the pipeline resolves a village name against a
gazetteer, computes its own straight-line distance, and reports the seller's
figure alongside as a separate, labelled claim.

Driving distance without a routing API
--------------------------------------
There is no routing service wired in, so driving distance is estimated as
straight-line distance times a **circuity factor** that depends on the
corridor. That is a real approximation and it is labelled INFERRED
everywhere it surfaces — never presented as a measured road distance.

The factors below come from how the road network around Mysuru is actually
shaped: the highways radiate from the city, so a parcel sitting on one is
close to its straight-line distance (1.15), while a parcel off a village
road has to come back out to a highway before it can head to the city (1.45).
Getting this wrong is not catastrophic in the way a price error is — it
shifts a parcel a few km in the ranking — but it is wrong in a *biased*
direction if ignored, and always in the seller's favour.

Any parcel that survives screening gets its real driving distance measured on
the site visit, which replaces this estimate with a SITE_VISIT claim.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from findfarms.core.claims import Claim, INFERRED, SELLER_CLAIM

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
GAZETTEER_PATH = DATA_DIR / "reference" / "villages.json"

# Mysuru reference point: the city centre near the Palace / K.R. Circle.
# Distances are measured to here rather than to the ring road, because the
# things that make a retirement property livable — hospitals, the railway
# station, the airport road — are referenced from the centre.
MYSURU_LAT = 12.3052
MYSURU_LON = 76.6552

# Straight-line -> driving multiplier by road context.
CIRCUITY = {
    "highway":      1.15,   # on or immediately off NH/SH (Bangalore, Ooty,
                            # Nanjangud, Hunsur, T.N.pura highways)
    "state_road":   1.25,   # main district roads, tarred, two-lane
    "village_road": 1.45,   # interior village road, often single-track
    "unknown":      1.30,   # the honest middle when the corridor is unclear
}

EARTH_RADIUS_KM = 6371.0

# Target radius from the brief. Beyond MAX_KM a parcel is flagged, not
# silently dropped — a genuinely exceptional 34 km parcel is a decision for
# the buyer to make, not for a filter to make on their behalf.
PREFERRED_MIN_KM = 10.0
PREFERRED_MAX_KM = 30.0
MAX_KM = 30.0

_gazetteer_cache: dict | None = None


def haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle distance in km."""
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def load_gazetteer(force: bool = False) -> dict:
    """Village reference data, keyed by normalised name.

    The gazetteer is seed data, not authority — coordinates are village
    centroids, and every entry carries its own `coord_confidence`. A parcel
    can sit 4 km from its village centre, so this locates a parcel to a
    neighbourhood, never to a boundary.
    """
    global _gazetteer_cache
    if _gazetteer_cache is not None and not force:
        return _gazetteer_cache
    try:
        raw = json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {"places": []}
    index = {}
    for place in raw.get("places", []):
        for name in [place.get("name", "")] + list(place.get("aliases", []) or []):
            key = normalise_place(name)
            if key and key not in index:
                index[key] = place
    _gazetteer_cache = {"places": raw.get("places", []), "index": index,
                        "notes": raw.get("notes", "")}
    return _gazetteer_cache


def normalise_place(name) -> str:
    """Fold the spelling variants that make village matching hard.

    Karnataka place names reach listings through several transliteration
    conventions at once — Mysore/Mysuru, Bannur/Bannuru, T. Narasipura/
    Tirumakudalu Narasipura/T.N.Pura — and a listing will use a different one
    than the gazetteer. Without this, the same parcel from two portals fails
    to match and becomes two properties in the database.
    """
    if not name:
        return ""
    s = str(name).strip().lower()
    for ch in ".,-_'()/":
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    # Trailing honorific/suffix noise seen in listings.
    for suffix in (" village", " grama", " gram", " post", " hobli", " taluk", " taluq"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    # Token-level transliteration first, so a variant survives being part of
    # a longer phrase. Whole-string swaps alone missed "mysore city", because
    # only the exact string "mysuru city" was listed — the folding has to
    # happen at the word, not at the phrase.
    token_aliases = {"mysore": "mysuru", "maisuru": "mysuru",
                     "bannuru": "bannur", "bannoor": "bannur",
                     "hunasuru": "hunsur", "hunsoor": "hunsur",
                     "nanjanagud": "nanjangud", "nanjangudu": "nanjangud",
                     "srirangapattana": "srirangapatna",
                     "periyapattana": "periyapatna", "piriyapatna": "periyapatna",
                     "ilavala": "ilwala", "elwala": "ilwala",
                     "yelawala": "yelwal"}
    s = " ".join(token_aliases.get(t, t) for t in s.split())
    # A trailing "city"/"town" is descriptive, not part of the name.
    for suffix in (" city", " town"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)].strip()

    # Common transliteration equivalences, applied as whole-string swaps.
    aliases = {
        "mysore": "mysuru", "maisuru": "mysuru", "mysuru city": "mysuru",
        "bannuru": "bannur", "bannoor": "bannur",
        "t narasipura": "t narasipura", "tn pura": "t narasipura",
        "tnpura": "t narasipura", "tirumakudalu narasipura": "t narasipura",
        "thirumakudalu narasipura": "t narasipura", "t n pura": "t narasipura",
        "h d kote": "h d kote", "hd kote": "h d kote", "heggadadevanakote": "h d kote",
        "hunasuru": "hunsur", "hunsoor": "hunsur",
        "k r nagar": "k r nagar", "kr nagar": "k r nagar",
        "krishnarajanagara": "k r nagar", "krishnaraja nagara": "k r nagar",
        "srirangapattana": "srirangapatna", "seringapatam": "srirangapatna",
        "nanjanagud": "nanjangud", "nanjangudu": "nanjangud",
        "periyapattana": "periyapatna", "piriyapatna": "periyapatna",
        "ilavala": "ilwala", "elwala": "ilwala", "ilwal": "ilwala",
        "yelawala": "yelwal", "yelahanka": "yelahanka",
    }
    return aliases.get(s, s)


def lookup_place(name):
    """Gazetteer entry for a village/town name, or None."""
    if not name:
        return None
    g = load_gazetteer()
    key = normalise_place(name)
    hit = g["index"].get(key)
    if hit:
        return hit
    # Listings write "Kadakola, Nanjangud Road" or "near Bilikere". Try each
    # token group before giving up, longest first so a two-word village name
    # is preferred over either of its halves.
    parts = [p.strip() for p in str(name).replace("/", ",").split(",") if p.strip()]
    for part in parts:
        cleaned = normalise_place(part)
        for prefix in ("near ", "at ", "in ", "close to "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        if cleaned in g["index"]:
            return g["index"][cleaned]
    return None


def resolve_location(village=None, lat=None, lon=None, taluk=None):
    """Best available position for a parcel.

    Explicit coordinates win when present — they are more specific than a
    village centroid. Otherwise the village name resolves through the
    gazetteer. The returned dict always says which of the two happened, so
    the property page can show "coordinates from listing" versus "positioned
    at the village centre, parcel may be several km away".
    """
    out = {"lat": None, "lon": None, "village": village, "taluk": taluk,
           "hobli": None, "corridor": "unknown", "method": "none",
           "coord_confidence": "UNKNOWN", "matched_name": None}

    try:
        flat, flon = float(lat), float(lon)
        # Sanity-bound to the Mysuru region. A swapped lat/lon or a stray
        # coordinate from another listing is common enough to be worth
        # catching, and a parcel "0.3 km away" would otherwise rank first.
        if 11.0 <= flat <= 13.5 and 75.5 <= flon <= 78.0:
            out.update(lat=flat, lon=flon, method="listing_coordinates",
                       coord_confidence="LISTING")
    except (TypeError, ValueError):
        pass

    place = lookup_place(village) or lookup_place(taluk)
    if place:
        out["matched_name"] = place.get("name")
        out["taluk"] = out["taluk"] or place.get("taluk")
        out["hobli"] = place.get("hobli")
        out["corridor"] = place.get("corridor", "unknown")
        if out["lat"] is None:
            out.update(lat=place.get("lat"), lon=place.get("lon"),
                       method="village_centroid",
                       coord_confidence=place.get("coord_confidence", "APPROXIMATE"))
    return out


def distances_from_mysuru(lat, lon, corridor: str = "unknown") -> dict:
    """Straight-line and estimated-driving distance, plus a drive-time guess.

    Drive time uses corridor-appropriate average speeds rather than one
    number: 45 km/h on a highway and 28 km/h on a village road is roughly
    what this region actually returns door to door, including the slow first
    and last kilometre through a village. Both outputs are estimates and are
    labelled as such wherever they appear.
    """
    straight = haversine_km(lat, lon, MYSURU_LAT, MYSURU_LON)
    if straight is None:
        return {"straight_km": None, "driving_km": None, "drive_minutes": None,
                "circuity": None, "corridor": corridor}
    factor = CIRCUITY.get(corridor, CIRCUITY["unknown"])
    driving = straight * factor
    speed = {"highway": 45.0, "state_road": 35.0,
             "village_road": 28.0, "unknown": 33.0}.get(corridor, 33.0)
    # Flat 8-minute allowance for getting out of the city itself, which no
    # average speed over the whole distance captures.
    minutes = (driving / speed) * 60.0 + 8.0
    return {"straight_km": round(straight, 2),
            "driving_km": round(driving, 1),
            "drive_minutes": int(round(minutes)),
            "circuity": factor, "corridor": corridor}


# Amenity kinds the gazetteer can tag a place with. Each is town-level: the
# tag means "this place has facilities of this kind", never a specific named
# institution at a verified position.
AMENITY_KINDS = ("hospital", "market", "town", "school", "yoga", "wellness")

# How each amenity reads on a property page, and what a "close" figure means
# for it. Distances differ by kind because the trips differ: a hospital run
# happens once at 2am under pressure, a yoga class happens five mornings a
# week and a 20 km round trip quietly stops happening after a month.
AMENITY_LABELS = {
    "hospital": "hospital facilities",
    "market":   "a market / groceries",
    "town":     "a town",
    "school":   "schools",
    "yoga":     "yoga shalas / studios",
    "wellness": "ayurveda / wellness centres",
}


def nearest_amenities(lat, lon) -> dict:
    """Distance to the nearest gazetteer place offering each amenity kind.

    Amenity positions are town-level, so this answers "how far to a town with
    a hospital", not "how far to a hospital". For retirement scoring that is
    the right granularity — what matters is whether a 2am emergency means a
    12-minute drive or a 50-minute one — but it must not be read as a
    verified travel time to a specific facility.

    The same caveat applies with more force to yoga and wellness. Mysuru is a
    genuine international yoga destination and the shalas cluster tightly in
    a few city neighbourhoods rather than spreading across the district, so
    "12 km to yoga" means 12 km to the neighbourhood where they are — not to
    a particular shala with space for a new student.
    """
    g = load_gazetteer()
    best = {}
    for kind in AMENITY_KINDS:
        best[kind] = None
        best[f"{kind}_name"] = None
    if lat is None or lon is None:
        return best
    for place in g["places"]:
        d = haversine_km(lat, lon, place.get("lat"), place.get("lon"))
        if d is None:
            continue
        amenities = place.get("amenities", []) or []
        for kind in AMENITY_KINDS:
            if kind in amenities and (best[kind] is None or d < best[kind]):
                best[kind] = round(d, 1)
                best[f"{kind}_name"] = place.get("name")
    return best


# ------------------------------------------- connectivity to a main road ----
#
# Distance from the parcel to the nearest main tarred road. This is a
# different question from "does the parcel have road frontage", and a more
# important one: frontage says the parcel touches *a* road, which may be a
# single-track mud lane. What decides whether an ambulance reaches the gate in
# August is how long the unpaved last stretch is.
#
# The bands are set by what the last mile actually costs, not by round
# numbers. Under 200 m you are effectively on the road. Past a kilometre of
# mud you are committing to a stretch that floods, that couriers refuse, and
# that a seventy-year-old will not drive after dark.
MAIN_ROAD_BANDS = (
    (0,    "ON_MAIN_ROAD",  "The parcel fronts a main tarred road."),
    (200,  "EXCELLENT",     "Effectively on the main road — a very short approach."),
    (500,  "GOOD",          "A short approach off the main road."),
    (1000, "ACCEPTABLE",    "Up to about a kilometre off the main road."),
    (2000, "CONCERNING",    "One to two kilometres off the main road."),
    (10**9, "POOR",         "More than two kilometres off the main road."),
)


def main_road_band(metres, surface: str | None = None) -> tuple[str, str]:
    """Classify the approach from the main road. Returns (band, why).

    `surface` is the approach road's surface when known. It changes the
    reading completely and so it changes the text: 800 m of tar is a
    non-issue, 800 m of mud is the thing that decides whether this property
    works in the monsoon.
    """
    if metres is None:
        return "UNKNOWN", ("Distance to the nearest main tarred road is not "
                           "stated. Ask, and measure it on the drive — this is "
                           "the number sellers omit most often when it is bad.")
    try:
        m = float(metres)
    except (TypeError, ValueError):
        return "UNKNOWN", "Approach distance could not be read."

    band, why = "POOR", MAIN_ROAD_BANDS[-1][2]
    for limit, name, text in MAIN_ROAD_BANDS:
        if m <= limit:
            band, why = name, text
            break

    unpaved = surface is not None and str(surface).lower() != "tarred"
    if unpaved and m >= 300:
        why += (f" That approach is unpaved: {m:.0f} m of mud road is what you "
                f"drive in every monsoon, in the dark, and in an emergency. "
                f"Treat it as the property's real access, not a detail.")
        # An unpaved approach is worth roughly a band of penalty past 500 m.
        if m >= 500:
            order = [b[1] for b in MAIN_ROAD_BANDS]
            band = order[min(order.index(band) + 1, len(order) - 1)]
    elif not unpaved and m > 0:
        why += " The approach is tarred, which is what makes the distance workable."
    return band, why


MAIN_ROAD_POINTS = {
    "ON_MAIN_ROAD": 1.00, "EXCELLENT": 0.92, "GOOD": 0.78,
    "ACCEPTABLE": 0.58, "CONCERNING": 0.30, "POOR": 0.08, "UNKNOWN": 0.0,
}


def distance_claims(resolved: dict, seller_distance_text=None) -> dict:
    """Build the distance claims for a property.

    Returns the computed estimate and, separately, whatever the seller said —
    never reconciled into one number. When they disagree by more than 20% the
    gap itself is recorded, because a seller who understates distance by 40%
    has told you something useful about the rest of their listing.
    """
    d = distances_from_mysuru(resolved.get("lat"), resolved.get("lon"),
                              resolved.get("corridor", "unknown"))
    method = resolved.get("method", "none")
    basis = ("listing coordinates" if method == "listing_coordinates"
             else f"{resolved.get('matched_name') or 'village'} centroid")
    out = {
        "straight_km": Claim(
            value=d["straight_km"], source=f"haversine from {basis}",
            confidence=INFERRED if d["straight_km"] is not None else "UNKNOWN"),
        "driving_km": Claim(
            value=d["driving_km"],
            source=f"straight-line x {d['circuity']} ({d['corridor']} circuity)",
            confidence=INFERRED if d["driving_km"] is not None else "UNKNOWN",
            note="Estimated, not routed. Measure on the site visit."),
        "drive_minutes": Claim(
            value=d["drive_minutes"], source="corridor average speed + 8 min city exit",
            confidence=INFERRED if d["drive_minutes"] is not None else "UNKNOWN"),
        "_raw": d,
    }
    if seller_distance_text:
        out["seller_stated_distance"] = Claim(
            value=str(seller_distance_text).strip(), source="listing",
            confidence=SELLER_CLAIM)
        stated_km = _km_from_text(seller_distance_text)
        if stated_km is not None and d["driving_km"]:
            gap = d["driving_km"] - stated_km
            if abs(gap) / max(d["driving_km"], 1) > 0.20:
                out["distance_discrepancy"] = Claim(
                    value=f"seller says {stated_km:.0f} km, estimate is "
                          f"{d['driving_km']:.0f} km ({gap:+.0f} km)",
                    source="comparison", confidence=INFERRED,
                    note="Treat other distance and time claims in this listing "
                         "with the same scepticism.")
    return out


def _km_from_text(text) -> float | None:
    """Pull a kilometre figure out of a free-text distance phrase."""
    import re
    if not text:
        return None
    s = str(text).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilometer|kilometre)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def radius_status(driving_km) -> tuple[str, str]:
    """Classify a parcel against the 30 km target. Returns (status, why).

    Nothing is rejected here — `OUTSIDE` is a flag that travels with the
    property and costs it location points, exactly as the brief asks. The
    band structure also encodes the preference for 10-30 km over very close
    parcels, where land is priced as city fringe rather than as farmland.
    """
    if driving_km is None:
        return "UNKNOWN", "No usable location — distance could not be estimated."
    if driving_km <= PREFERRED_MIN_KM:
        return "INSIDE_CLOSE", (
            f"~{driving_km:.0f} km — very close to the city. Convenient, but "
            f"this belt is usually priced as urban-fringe land rather than "
            f"farmland, and is the most exposed to acquisition and zoning change.")
    if driving_km <= PREFERRED_MAX_KM:
        return "PREFERRED", f"~{driving_km:.0f} km — inside the preferred 10-30 km band."
    if driving_km <= MAX_KM * 1.25:
        return "OUTSIDE_NEAR", (
            f"~{driving_km:.0f} km — beyond the 30 km target but within reach. "
            f"Flagged, not rejected: worth it only if water and land quality are strong.")
    return "OUTSIDE", (
        f"~{driving_km:.0f} km — well outside the 30 km target. For a retirement "
        f"property this distance is a recurring daily cost, not a one-time one.")
