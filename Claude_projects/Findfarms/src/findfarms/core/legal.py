"""
legal.py
========
LEGAL_RISK = LOW / MEDIUM / HIGH / UNKNOWN — a preliminary screening result.
**Not legal advice, not a title opinion, and never a clearance.**

What this module is for: reading an advertisement and deciding whether it is
worth a lawyer's time, and what to hand the lawyer when it is. That is a real
and useful job. It is not the job of deciding whether the title is good — no
system that reads adverts can do that, because the documents that determine
title are not in the advert.

The asymmetry that shapes everything here
-----------------------------------------
**Absence of evidence is not evidence of safety.** A listing that says nothing
about title is not a low-risk listing; it is an unassessed one. So:

    LOW      requires *positive documentary evidence*, at VERIFIED
             confidence — an RTC actually read, an EC actually pulled. It
             cannot be reached from an advert, ever. Most properties will
             never be LOW in this system, and that is correct.
    MEDIUM   specific concerns identified, or partial documentation seen.
    HIGH     a category of problem that historically destroys transactions
             in Karnataka is present.
    UNKNOWN  the default, and where nearly everything sits. Not a neutral
             verdict — it means "nobody has checked" and it forces
             DUE DILIGENCE REQUIRED downstream.

The HIGH triggers below are not generic property risks; they are the specific
Karnataka failure modes that make a sale voidable or unregisterable years
later, when the money is gone:

  * **Grant land / PTCL.** Land granted to Scheduled Caste and Scheduled
    Tribe holders under the Karnataka Scheduled Castes and Scheduled Tribes
    (Prohibition of Transfer of Certain Lands) Act carries transfer
    restrictions. A sale in breach can be set aside and the land restored to
    the original grantee's family — decades later, from a good-faith buyer,
    with no compensation. This is the single most dangerous category in the
    state and it is not always visible in the RTC.
  * **Gomala / government / inam / Bhoodan land.** Land that was never
    private to begin with, or was granted for a purpose, cannot be
    transferred as though it were.
  * **Forest land and eco-sensitive buffers.** Especially relevant on the
    H.D. Kote and Hunsur sides. Boundaries move on paper.
  * **Acquisition notifications** (highway, ring road, KIADB, MUDA layouts).
    A notified parcel is bought at the government's compensation rate, not
    yours.
  * **Tenancy claims** under the Karnataka Land Reforms Act. A registered
    tenant's occupancy right survives the sale.

None of these can be cleared by this system. Each one, when triggered, sets
STATUS = DO NOT PROCEED and stops the property from ranking regardless of how
good its water, price and location are — because the brief is right that an
excellent price must never compensate for a title that can be undone.

There is also a Karnataka-specific structural point the screen always raises:
agricultural land purchase and land ceilings are governed by the Karnataka
Land Reforms Act, and the rules on who may buy agricultural land have
changed materially in recent years. Whether the buyer is eligible, and what
extent they may hold, is a question for a lawyer about the buyer, not about
the parcel — so it is surfaced as a standing item rather than scored.
"""

from __future__ import annotations

from findfarms.core.claims import ClaimSet, VERIFIED

LOW, MEDIUM, HIGH, UNKNOWN = "LOW", "MEDIUM", "HIGH", "UNKNOWN"

# Any of these present ⇒ HIGH, and the deal is stopped. Each entry is
# (claim key, short label, why it stops the deal).
HARD_STOPS = (
    ("risk_grant_land", "Grant land / PTCL",
     "Land granted under the PTCL Act carries transfer restrictions. A sale in "
     "breach can be set aside and the land restored to the grantee's family "
     "years later, from a good-faith buyer, without compensation. This does not "
     "always appear on the face of the RTC — it needs a specific check of the "
     "grant record and the tahsildar's endorsement."),
    ("risk_government_land", "Government / gomala / inam / Bhoodan land",
     "Land that was public, or granted for a purpose, cannot be conveyed as "
     "private property. Encroached gomala regularly reaches the market with "
     "documents that look ordinary."),
    ("risk_forest_land", "Forest land or eco-sensitive buffer",
     "Forest and buffer boundaries are redrawn on paper, and a parcel inside one "
     "cannot be built on or, often, sold. Particularly relevant on the H.D. Kote "
     "and Hunsur sides."),
    ("risk_acquisition", "Acquisition or notification",
     "A notified parcel is acquired at the government's compensation rate, not "
     "at what you paid. Check the current status against the relevant authority's "
     "notification, not against the seller's assurance that it was 'dropped'."),
    ("risk_tenancy", "Tenancy / occupancy claim",
     "A registered tenant's occupancy right under the Land Reforms Act survives "
     "the sale. Form 7 entries and old tenancy records must be traced."),
)

# Present ⇒ at least MEDIUM. Serious, but ordinarily resolvable with the right
# documents and the right parties at the sub-registrar.
CONCERNS = (
    ("risk_dispute", "Dispute, litigation or family settlement mentioned",
     "Get the partition deed or decree, and confirm every party to it has "
     "signed. A pending suit or a stay order makes the parcel unsaleable until "
     "it is resolved."),
    ("risk_multiple_owners", "Multiple or joint owners",
     "Every co-owner — including those abroad, minors, and heirs of a deceased "
     "owner — must be party to the sale deed. One missing signature is enough "
     "to reopen the sale later."),
    ("risk_buffer", "Lake / river / raja kaluve buffer",
     "Buffer zones restrict construction and, in some cases, the transfer "
     "itself. Get the extent measured against the revenue map, not eyeballed."),
)

# Positive signals. These only reduce risk at VERIFIED confidence — a listing
# that *says* "clear title" is an advertising claim and moves nothing.
DOCUMENTS = (
    ("mentions_rtc", "RTC / Pahani"),
    ("mentions_mutation", "Mutation (MR)"),
    ("mentions_ec", "Encumbrance Certificate"),
    ("mentions_sale_deed", "Sale deed / Khata"),
    ("mentions_parent_document", "Parent / mother deed"),
    ("survey_number", "Survey number"),
)

# The document set a lawyer will ask for. Emitted for every property because
# it is the actual next step for anything that survives screening.
DOCUMENT_CHECKLIST = [
    "RTC / Pahani for the last 30 years — read the column entries, not just the "
    "current owner. This is where grant conditions, tenancy entries and old "
    "government-land status appear.",
    "Mutation register extracts (MR) for every ownership change in that period.",
    "Encumbrance Certificate (EC) for 30 years from the sub-registrar — "
    "covering the full period, not the 13-year default.",
    "Registered sale deed of the current owner, plus the parent/mother deed "
    "and the full link chain back through each earlier transfer.",
    "Survey sketch / tippani / akarband, and a fresh surveyor's measurement "
    "against the registered extent.",
    "Genealogical tree (vamsha vruksha) certified by the village accountant, "
    "to identify every legal heir with a potential claim.",
    "Khata certificate and extract, and the latest land-tax receipts.",
    "Village map and the parcel's position on it, checked against the "
    "physical boundaries.",
    "Conversion order (DC conversion) if any non-agricultural use is intended "
    "or any structure exists.",
    "No-dues certificates: land revenue, and any electricity or water "
    "connection being transferred.",
    "If any owner is or has been an NRI, a minor, or is deceased: the "
    "additional documents your lawyer will specify for each.",
    "Written confirmation from a lawyer that the parcel is NOT grant/PTCL "
    "land, is not gomala or inam land, and carries no tenancy entry.",
]

STANDING_ITEMS = [
    "Eligibility to buy agricultural land in Karnataka, and the extent a buyer "
    "may hold, are governed by the Karnataka Land Reforms Act and have changed "
    "materially in recent years. Confirm the buyer's eligibility and ceiling "
    "with a lawyer before making any offer — this is a question about the "
    "buyer, not about the parcel.",
    "Confirm the stamp duty and registration cost on the actual guidance value, "
    "and who is paying it, before agreeing a price.",
]


def screen_legal(cs: ClaimSet) -> dict:
    """Preliminary legal-risk screen.

    Returns the risk level, the findings behind it, the documents to obtain,
    and — importantly — an explicit statement of what this screen did not and
    could not check. The property page prints that statement every time.
    """
    findings: list[dict] = []
    hard_stop = False

    for key, label, why in HARD_STOPS:
        c = cs.get(key)
        if c.truthy():
            hard_stop = True
            findings.append({
                "severity": "HIGH", "label": label, "why": why,
                "evidence": c.source or "listing text",
                "note": c.note or "",
            })

    for key, label, why in CONCERNS:
        c = cs.get(key)
        if c.truthy():
            findings.append({
                "severity": "MEDIUM", "label": label, "why": why,
                "evidence": c.source or "listing text", "note": c.note or "",
            })

    # Documents actually verified, versus documents merely mentioned.
    verified_docs = [label for key, label in DOCUMENTS
                     if cs.get(key).confidence == VERIFIED]
    mentioned_docs = [label for key, label in DOCUMENTS
                      if cs.get(key).known and cs.get(key).confidence != VERIFIED]

    # Conversion status. Worth flagging both ways: unconverted land cannot
    # legally carry a house, and converted land is no longer agricultural,
    # which changes the tax treatment and often the reason for buying it.
    conv = cs.get("mentions_conversion")
    if conv.known:
        findings.append({
            "severity": "INFO",
            "label": "Conversion (DC / NA) mentioned",
            "why": "Converted land is no longer agricultural — different tax "
                   "treatment, different price basis, and it defeats the point if "
                   "the intent is farming. Unconverted land cannot legally carry a "
                   "residential structure. Establish which this is, and what the "
                   "intended use requires.",
            "evidence": conv.source or "listing text", "note": conv.note or "",
        })

    if cs.get("mentions_clear_title").known and \
            cs.get("mentions_clear_title").confidence != VERIFIED:
        findings.append({
            "severity": "INFO",
            "label": "Listing asserts 'clear title'",
            "why": "This is advertising copy and carries no weight. Every listing "
                   "says it. It neither raises nor lowers the assessed risk — only "
                   "a document read by a lawyer does that.",
            "evidence": "listing text", "note": "",
        })

    # Only worth saying while it is still true. Once documents have actually
    # been read and recorded, "the listing didn't mention any" is a stale
    # observation about an advert nobody is relying on any more.
    if cs.get("no_documents_mentioned").truthy() and not verified_docs:
        findings.append({
            "severity": "INFO",
            "label": "No title documents referenced anywhere in the listing",
            "why": "Normal for an advert and not itself suspicious. It does mean "
                   "this screen has nothing to assess, which is why the result is "
                   "UNKNOWN rather than low risk.",
            "evidence": "extraction", "note": "",
        })

    # -- level ---------------------------------------------------------------
    # INFO findings are context, not concerns — "the advert says clear title",
    # "conversion is mentioned". Letting them block LOW meant a property with
    # four independently verified documents still read as MEDIUM because its
    # original advert had used the words "clear title", which is backwards.
    concerns = [f for f in findings if f["severity"] in ("HIGH", "MEDIUM")]

    if hard_stop:
        level = HIGH
        rationale = ("A hard-stop category is present. These are the Karnataka "
                     "failure modes that unwind a completed sale years later, and "
                     "no combination of price, water or location offsets one.")
    elif verified_docs and len(verified_docs) >= 4 and not concerns:
        # Reachable only after real documents have been recorded via
        # db.record_verification — never from an advert.
        level = LOW
        rationale = (f"Documentary evidence recorded at verified confidence "
                     f"({', '.join(verified_docs)}) and no concerns raised. Still "
                     f"a screening result, not a title opinion.")
    elif concerns:
        level = MEDIUM
        rationale = ("Specific concerns identified that need documents and a "
                     "lawyer to resolve. Ordinarily resolvable — but resolve them "
                     "before any money moves, not after.")
    elif verified_docs:
        level = MEDIUM
        rationale = (f"Partial documentary evidence ({', '.join(verified_docs)}). "
                     f"Not yet enough for a low-risk read.")
    else:
        level = UNKNOWN
        rationale = ("Nothing in this listing permits any assessment of title. "
                     "UNKNOWN is not a neutral verdict — it means nobody has "
                     "checked, and it is where almost every property sits until a "
                     "lawyer reads the documents.")

    # What this screen could not see. Printed on every property page, because
    # the limits of an automated screen are the part a buyer most needs to
    # keep in view.
    not_checked = [
        "The actual RTC, EC, sale deed or any other document — none were read.",
        "Whether the parcel is grant/PTCL land. This frequently does not appear "
        "in an advertisement and sometimes not on the face of the RTC either.",
        "Whether the seller is the sole legal owner, and whether every heir and "
        "co-owner has been identified.",
        "Whether the physical boundaries match the registered extent.",
        "Any pending litigation, notification or acquisition proceeding.",
        "Whether the buyer is eligible to purchase agricultural land in "
        "Karnataka at all.",
    ]

    return {
        "level": level,
        "rationale": rationale,
        "findings": findings,
        "hard_stop": hard_stop,
        "verified_documents": verified_docs,
        "mentioned_documents": mentioned_docs,
        "document_checklist": DOCUMENT_CHECKLIST,
        "standing_items": STANDING_ITEMS,
        "not_checked": not_checked,
        "disclaimer": (
            "PRELIMINARY SCREENING ONLY — NOT LEGAL ADVICE AND NOT A TITLE "
            "CLEARANCE. This reads advertisements, not documents. It can raise "
            "concerns; it can never confirm that a title is good. No property "
            "should be paid for on the strength of anything on this page. Engage "
            "a property lawyer in Mysuru who does agricultural title work, and a "
            "licensed surveyor, before any advance or agreement."),
    }
