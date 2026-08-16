"""
freshness.py
============
When was this listing posted, when did we last see it alive, and does any of
that tell you whether the land is still for sale?

The honest answer to the last question first
--------------------------------------------
**Recency is a weak signal of availability, and staleness is a weaker signal
of unavailability.** Agricultural land around Mysuru sits on the market for a
year or more as a matter of routine, and listings are almost never taken down
when a parcel sells — the broker stops answering, the post stays up. So:

  * A listing posted last week may be for land that was sold in March and
    re-advertised by a second broker who never checked.
  * A listing from fourteen months ago may be perfectly live, with a seller
    who has quietly become much more negotiable.

The second case is the one this whole system exists to catch. So freshness is
computed and shown prominently, and it is **never** used to score a property
or to delete one. The only thing that establishes availability is a phone
call, and the workflow records that separately as an availability check with
its own date.

Three different dates, deliberately not merged
----------------------------------------------
    date_posted      When the seller says the listing went up. Usually a
                     SELLER_CLAIM or portal metadata; often absent entirely.
    first_seen       When this system first observed it. A hard upper bound
                     on "posted" — it cannot have been posted after we saw
                     it — and a lower bound on age.
    last_seen        The most recent time we observed it. The one that
                     matters for a recency window, because a parcel
                     re-listed last week is current news regardless of when
                     it first appeared.

When `date_posted` is unknown, `first_seen` stands in as an explicit lower
bound and is labelled as one. A listing we first met yesterday might have
been posted two years ago; saying "posted yesterday" because that is when we
noticed would be inventing a fact, and it would make every newly imported
old listing look fresh.

The window filter
-----------------
"Only the last 3 months" filters on **most recent activity**, not on first
sighting. Filtering on first sighting would hide exactly the properties worth
the most attention: a parcel first seen eight months ago whose price dropped
last week is the system's single most valuable output, and its first-seen
date is outside any three-month window. See `within_window`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from findfarms.core.claims import Claim, ClaimSet, INFERRED, SELLER_CLAIM

# The user-facing "recent" window.
DEFAULT_WINDOW_DAYS = 90

FRESH = "FRESH"
RECENT = "RECENT"
AGEING = "AGEING"
STALE = "STALE"
DORMANT = "DORMANT"
UNKNOWN = "UNKNOWN"

# Bands by days since the listing was last active. Generous by rural-land
# standards: 120 days on market is an ordinary marketing period here, not a
# stale listing, so nothing is called stale before six months.
BANDS = (
    (14,  FRESH,   "Posted or re-seen within the last two weeks."),
    (90,  RECENT,  "Active within the last three months."),
    (180, AGEING,  "Last seen three to six months ago."),
    (365, STALE,   "Last seen six to twelve months ago."),
    (10**6, DORMANT, "Not seen for over a year."),
)

STATUS_LABEL = {
    FRESH:   ("🟢", "Fresh"),
    RECENT:  ("🟢", "Recent"),
    AGEING:  ("🟡", "Ageing"),
    STALE:   ("🟠", "Stale"),
    DORMANT: ("⚪", "Dormant"),
    UNKNOWN: ("❔", "Unknown"),
}

# Relative phrases portals and posts use, in days.
_RELATIVE = (
    (r"\btoday\b", 0), (r"\bjust now\b", 0), (r"\byesterday\b", 1),
    (r"(\d+)\s*(?:day|days)\s*ago", 1),
    (r"(\d+)\s*(?:week|weeks)\s*ago", 7),
    (r"(\d+)\s*(?:month|months)\s*ago", 30),
    (r"(\d+)\s*(?:year|years)\s*ago", 365),
    (r"a\s*(?:day)\s*ago", 1), (r"a\s*week\s*ago", 7),
    (r"a\s*month\s*ago", 30), (r"an?\s*year\s*ago", 365),
)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def _today() -> date:
    return date.today()


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)).date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None


def parse_posted_date(text) -> tuple[date | None, str]:
    """Read a posting date out of listing text. Returns (date, how_it_was_read).

    Handles the absolute forms ("Posted on 12 Jan 2026", "12/01/2026") and the
    relative ones portals actually use ("Posted 3 days ago", "2 months ago").

    **Numeric dates are read as DD/MM/YYYY**, the Indian convention. Reading
    12/01/2026 as 12 January is right here and reading it as 1 December would
    be wrong by eleven months — enough to move a listing across the three-month
    window in either direction. Where the day is unambiguously above 12 the
    order is confirmed; where both are ≤12 the Indian reading is assumed and
    the ambiguity is reported in the second return value.
    """
    if not text:
        return None, ""
    s = str(text).lower()
    today = _today()

    # Relative first — a portal showing "3 days ago" often also carries an
    # unrelated date elsewhere in the page furniture.
    for pattern, unit_days in _RELATIVE:
        m = re.search(pattern, s)
        if not m:
            continue
        n = 1
        if m.groups():
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                n = 1
        days = n * unit_days if m.groups() else unit_days
        if 0 <= days <= 3650:
            return today - timedelta(days=days), f'"{m.group(0).strip()}"'

    # "12 Jan 2026" / "Jan 12 2026" / "12 January 2026"
    m = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*[-/ ]?\s*"
                  r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                  r"[-/, ]*\s*(\d{4}|\d{2})\b", s)
    if m:
        d = _build(m.group(3), _MONTHS[m.group(2)], m.group(1))
        if d:
            return d, f'"{m.group(0).strip()}"'
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                  r"\s*(\d{1,2})\s*(?:st|nd|rd|th)?[-/, ]*\s*(\d{4})\b", s)
    if m:
        d = _build(m.group(3), _MONTHS[m.group(1)], m.group(2))
        if d:
            return d, f'"{m.group(0).strip()}"'

    # ISO: 2026-01-12
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", s)
    if m:
        d = _build(m.group(1), m.group(2), m.group(3))
        if d:
            return d, f'"{m.group(0).strip()}" (ISO)'

    # Numeric: 12/01/2026 — read DD/MM/YYYY.
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2}|\d{2})\b", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b > 12 and a <= 12:
            d = _build(m.group(3), a, b)          # unambiguously MM/DD
            note = f'"{m.group(0).strip()}" (read as MM/DD)'
        else:
            d = _build(m.group(3), b, a)          # DD/MM, the Indian convention
            note = (f'"{m.group(0).strip()}" (read as DD/MM — Indian convention'
                    + ('; ambiguous, could be MM/DD' if a <= 12 and b <= 12 else '')
                    + ')')
        if d:
            return d, note
    return None, ""


def _build(year, month, day):
    try:
        y, mo, d = int(year), int(month), int(day)
        if y < 100:
            y += 2000
        result = date(y, mo, d)
    except (ValueError, TypeError):
        return None
    # Reject the impossible: a future posting date, or one older than this
    # market has had online listings for. Both indicate a misparse.
    today = _today()
    if result > today + timedelta(days=1) or result < date(2005, 1, 1):
        return None
    return result


def posting_date(cs: ClaimSet, prop: dict | None = None) -> dict:
    """Best available posting date, with an explicit statement of its basis.

    Returns the date, how confident we are, and — importantly — whether it is
    the real posting date or a lower bound standing in for one.
    """
    prop = prop or {}

    claim = cs.get("date_posted")
    if claim.known:
        d = _parse_iso(claim.value)
        if d:
            return {"date": d, "basis": "stated", "exact": True,
                    "confidence": claim.confidence,
                    "source": claim.source or "listing",
                    "note": f"The listing states it was posted on {d.isoformat()}."}

    first = _parse_iso(prop.get("first_seen"))
    if first:
        return {"date": first, "basis": "first_seen", "exact": False,
                "confidence": INFERRED, "source": "findfarms",
                "note": (f"No posting date was given. This system first saw the "
                         f"listing on {first.isoformat()}, which is a LOWER BOUND "
                         f"on its age — it may have been online long before we "
                         f"noticed it.")}

    disc = cs.get("date_discovered")
    d = _parse_iso(disc.value) if disc.known else None
    if d:
        return {"date": d, "basis": "discovered", "exact": False,
                "confidence": INFERRED, "source": "findfarms",
                "note": "Posting date unknown; using the date this listing was "
                        "first extracted, as a lower bound on its age."}
    return {"date": None, "basis": "unknown", "exact": False,
            "confidence": "UNKNOWN", "source": "",
            "note": "No posting date and no discovery date available."}


def last_activity(cs: ClaimSet, prop: dict | None = None) -> date | None:
    """The most recent date this listing was posted, re-posted or observed.

    This — not first sighting — is what a recency window should filter on.
    """
    prop = prop or {}
    candidates = []
    seen = _parse_iso(prop.get("last_seen"))
    if seen:
        candidates.append(seen)
    posted = posting_date(cs, prop)
    if posted["date"] and posted["exact"]:
        candidates.append(posted["date"])
    if not candidates and posted["date"]:
        candidates.append(posted["date"])
    return max(candidates) if candidates else None


def assess_freshness(cs: ClaimSet, prop: dict | None = None) -> dict:
    """Posting date, age, recency band, and an honest availability note."""
    prop = prop or {}
    today = _today()
    posted = posting_date(cs, prop)
    active = last_activity(cs, prop)

    days_since_posted = (today - posted["date"]).days if posted["date"] else None
    days_since_active = (today - active).days if active else None

    if days_since_active is None:
        status, why = UNKNOWN, "No dates available for this listing."
    else:
        status, why = DORMANT, BANDS[-1][2]
        for limit, name, text in BANDS:
            if days_since_active <= limit:
                status, why = name, text
                break

    icon, label = STATUS_LABEL.get(status, STATUS_LABEL[UNKNOWN])

    # The availability note is the point of this module, and it says the same
    # thing at every band because the truth does not vary: only a phone call
    # settles this.
    if status in (FRESH, RECENT):
        availability = (
            "Recently active, which makes it more likely to still be available — "
            "but not much more. Listings here are rarely taken down when a parcel "
            "sells, and re-posts of already-sold land are common. Call to confirm.")
    elif status == AGEING:
        availability = (
            "Nothing seen for a few months. That usually means it simply has not "
            "sold — normal for agricultural land at this size — rather than that "
            "it is gone. Worth a call, and the seller may have softened.")
    elif status == STALE:
        availability = (
            "Not seen for six months or more. Often still available and often "
            "considerably more negotiable by now. This is the band where the "
            "best conversations happen, so treat age as an opening rather than "
            "a reason to skip it.")
    elif status == DORMANT:
        availability = (
            "Not seen in over a year. It may be sold, withdrawn, or simply "
            "forgotten by everyone including the seller. Cheap to check, and a "
            "seller who has been trying this long is the most negotiable of all.")
    else:
        availability = "No dates available, so nothing can be said about currency."

    checks = prop.get("availability_checks") or []
    last_check = checks[-1] if checks else None

    return {
        "status": status,
        "icon": icon,
        "label": label,
        "why": why,
        "availability_note": availability,
        "posted_date": posted["date"].isoformat() if posted["date"] else None,
        "posted_exact": posted["exact"],
        "posted_basis": posted["basis"],
        "posted_note": posted["note"],
        "posted_confidence": posted["confidence"],
        "days_since_posted": days_since_posted,
        "last_active": active.isoformat() if active else None,
        "days_since_active": days_since_active,
        "observation_count": int(prop.get("observation_count", 0) or 0),
        "last_availability_check": last_check,
        "caveat": (
            "Recency does not establish availability and age does not establish "
            "that a parcel is gone. Only a phone call does, and this system never "
            "hides or deletes a listing for being old — the older ones are where "
            "the price drops come from."),
    }


def within_window(cs: ClaimSet, prop: dict | None = None,
                  days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """Whether a property has been active within the last `days`.

    Filters on LAST activity, never on first sighting. A parcel first seen
    eight months ago and re-listed last week is current news, and filtering it
    out because of its first-seen date would hide the single most valuable
    thing this database produces.
    """
    if days is None:
        return True
    active = last_activity(cs, prop)
    if active is None:
        # No dates at all. Kept rather than hidden — a filter should not
        # silently drop records because of missing metadata.
        return True
    return (_today() - active).days <= days


def extract_posted_date(text: str, cs: ClaimSet, extra: dict | None = None) -> None:
    """Pull a posting date out of listing text or supplied portal metadata.

    Metadata passed by the caller wins over text parsing: a portal's own
    "posted on" field is more reliable than a date found somewhere in the
    body, which may be an unrelated date in the description.
    """
    supplied = (extra or {}).get("date_posted")
    if supplied:
        d = _parse_iso(supplied) or parse_posted_date(supplied)[0]
        if d:
            cs.add("date_posted", Claim(
                value=d.isoformat(), source="listing metadata",
                confidence=SELLER_CLAIM,
                note="Taken from the source's own posting-date field."))
            return

    d, how = parse_posted_date(text)
    if d:
        cs.add("date_posted", Claim(
            value=d.isoformat(), source=f"listing text {how}",
            confidence=SELLER_CLAIM,
            note=f"Read from the listing text as {how}. Sellers refresh and "
                 f"re-post listings, so a recent date does not mean the parcel "
                 f"came to market recently."))
