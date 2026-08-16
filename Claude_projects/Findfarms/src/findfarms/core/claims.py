"""
claims.py
=========
The Claim primitive: no fact in this system travels without its source and
its confidence attached.

This is the module the whole design rests on. A farmland listing is mostly
assertions by someone who profits from you believing them — "borewell 400
feet, good water year round, clear title, DC converted" — and the failure
mode of every property tool is that those assertions get stored in a field
called `water_source` and are indistinguishable from a fact by the time a
score reads them. Six weeks later the score says 88 and nobody can say why.

So a value is never stored bare. It is stored as:

    Claim(value="borewell", source="MagicBricks listing #4471",
          confidence=SELLER_CLAIM, observed_at="2026-08-14")

and the scoring engines multiply by the confidence weight rather than
reading the value alone. A seller-claimed borewell and a borewell you stood
next to and watched run are the same string and must not be the same score.

Confidence ladder (this ordering is load-bearing — the scorers index it):

    VERIFIED            A document was read, or a professional confirmed it.
                        RTC in hand, EC from the sub-registrar, surveyor's
                        sketch. This is the only level that may lower legal
                        risk.
    SITE_VISIT          You (or someone you sent) physically observed it.
    OBSERVED_FROM_MEDIA Visible in a listing photo or video. Real evidence
                        about appearance, and no evidence at all about
                        legality or yield — a pipe in a photo proves a pipe.
    THIRD_PARTY         A neighbour, another broker, a local official said
                        it. Useful corroboration, not proof.
    SELLER_CLAIM        The listing or the seller said it. The default, and
                        the reason this module exists.
    INFERRED            This system computed it (distance from coordinates,
                        price per acre). Honest but derived — an inferred
                        value inherits the weakest confidence of its inputs.
    UNKNOWN             No information. Distinct from a value of "no": a
                        property with no water information is not a property
                        with no water, and scoring them the same way is how
                        you reject a good parcel and pursue a dry one.

The gap between UNKNOWN and a negative finding is the single most common
place property tools go wrong, so it is a separate level here rather than a
None that the scorers each handle in their own way.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

VERIFIED = "VERIFIED"
SITE_VISIT = "SITE_VISIT"
OBSERVED_FROM_MEDIA = "OBSERVED_FROM_MEDIA"
THIRD_PARTY = "THIRD_PARTY"
SELLER_CLAIM = "SELLER_CLAIM"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"

LEVELS = (VERIFIED, SITE_VISIT, OBSERVED_FROM_MEDIA, THIRD_PARTY,
          SELLER_CLAIM, INFERRED, UNKNOWN)

# How much a claim at this level is *worth as evidence*. Used where one
# claim is being weighed against another — merging, and any direct
# evidence-quality comparison.
WEIGHT = {
    VERIFIED:            1.00,
    SITE_VISIT:          0.90,
    OBSERVED_FROM_MEDIA: 0.65,
    THIRD_PARTY:         0.55,
    SELLER_CLAIM:        0.45,
    INFERRED:            0.60,
    UNKNOWN:             0.00,
}

# How much of a factor's points a claim at this level may earn *when
# scoring*. Much gentler than WEIGHT, and the difference is deliberate.
#
# The scorers discount unverified claims twice if this is the same curve as
# WEIGHT: once per point here, and again through the evidence caps in
# water.py and deal.py. The first version of this module used WEIGHT for
# both, and the result was that a parcel with a 400 ft borewell, three-phase
# power and a pump — a perfectly ordinary, decently-described listing —
# scored 20/100 for water and was labelled "Critical", while the cap that
# was supposed to be doing that work (55) never came anywhere near binding.
# Every listing looked equally terrible, which ranks nothing.
#
# So the split: this curve preserves the *ordering* (observed beats claimed
# beats inferred) without collapsing the scale, and the caps do the work of
# keeping unverified properties out of the top tier. That puts the penalty
# in one place, where it is visible and explainable on the property page,
# instead of smeared invisibly across every point.
SCORE_WEIGHT = {
    VERIFIED:            1.00,
    SITE_VISIT:          0.97,
    OBSERVED_FROM_MEDIA: 0.90,
    THIRD_PARTY:         0.85,
    SELLER_CLAIM:        0.80,
    INFERRED:            0.85,
    UNKNOWN:             0.00,
}

# Short labels for the UI. The emoji is doing real work here: on a dense
# property page the eye needs to separate evidence from assertion without
# reading, or it stops separating them at all.
LABEL = {
    VERIFIED:            ("✅", "Verified"),
    SITE_VISIT:          ("👣", "Seen on site"),
    OBSERVED_FROM_MEDIA: ("📷", "Seen in media"),
    THIRD_PARTY:         ("🗣", "Third party"),
    SELLER_CLAIM:        ("💬", "Seller says"),
    INFERRED:            ("🧮", "Computed"),
    UNKNOWN:             ("❔", "Unknown"),
}

# Levels that count as independent evidence rather than assertion. Used by
# the legal screen (which may only be lowered by VERIFIED) and by the water
# scorer (which caps unevidenced claims).
EVIDENCE_LEVELS = (VERIFIED, SITE_VISIT, OBSERVED_FROM_MEDIA)


@dataclass
class Claim:
    """A single value plus where it came from and how much to trust it."""

    value: object = None
    source: str = ""
    confidence: str = UNKNOWN
    observed_at: str = ""
    note: str = ""

    def __post_init__(self):
        if self.confidence not in WEIGHT:
            self.confidence = UNKNOWN
        # A value that never arrived is UNKNOWN regardless of what the
        # caller passed. Otherwise an extractor that finds nothing but
        # labels its output SELLER_CLAIM manufactures confidence from
        # absence, which is exactly the bug this module exists to prevent.
        if self.value is None or (isinstance(self.value, str) and not self.value.strip()):
            self.value = None
            self.confidence = UNKNOWN
        if not self.observed_at:
            self.observed_at = date.today().isoformat()

    # -- reading ----------------------------------------------------------

    @property
    def known(self) -> bool:
        return self.value is not None and self.confidence != UNKNOWN

    @property
    def weight(self) -> float:
        """Evidence weight — for comparing claims against each other."""
        return WEIGHT.get(self.confidence, 0.0)

    @property
    def score_weight(self) -> float:
        """Scoring weight — gentler, because the caps do the top-end work."""
        return SCORE_WEIGHT.get(self.confidence, 0.0)

    @property
    def is_evidence(self) -> bool:
        """True when something independent of the seller supports this."""
        return self.confidence in EVIDENCE_LEVELS

    def truthy(self) -> bool:
        """Whether this claim asserts a positive. Used for yes/no features
        like 'has borewell'. UNKNOWN is False here — but callers must check
        `.known` first when absence needs to be distinguished from denial."""
        v = self.value
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("no", "none", "false", "0", "nil", "absent"):
            return False
        return bool(s)

    def scaled(self, points: float) -> float:
        """`points` earned at this claim's confidence — the call every scorer
        uses, so discounting evidence quality is the default path rather than
        something each scorer has to remember. Uses SCORE_WEIGHT; see the
        note there on why scoring and evidence weighting differ."""
        return points * self.score_weight if self.truthy() else 0.0

    # -- display ----------------------------------------------------------

    def badge(self) -> str:
        icon, text = LABEL.get(self.confidence, LABEL[UNKNOWN])
        return f"{icon} {text}"

    def describe(self) -> str:
        if not self.known:
            return "Unknown"
        src = f" — {self.source}" if self.source else ""
        return f"{self.value} ({self.badge()}{src})"

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Claim":
        if isinstance(d, Claim):
            return d
        if not isinstance(d, dict):
            # A bare value from hand-edited JSON. Read it, but say plainly
            # that its provenance was never recorded.
            return cls(value=d, source="unrecorded", confidence=UNKNOWN)
        return cls(value=d.get("value"), source=d.get("source", ""),
                   confidence=d.get("confidence", UNKNOWN),
                   observed_at=d.get("observed_at", ""), note=d.get("note", ""))

    @classmethod
    def unknown(cls, note: str = "") -> "Claim":
        return cls(value=None, confidence=UNKNOWN, note=note)


# Fields whose value legitimately CHANGES over time. For these, a newer
# claim at equal confidence replaces the older one instead of being recorded
# as a conflict.
#
# This distinction is not cosmetic. The default merge rule — keep the
# earliest claim when evidence is equal — is correct for stable attributes: a
# video showing a dry channel must not be overwritten next week by a listing
# that says "canal water". Applied to price it is actively wrong. A parcel
# first seen at ₹42L/acre and relisted at ₹35L is not two sources
# contradicting each other; it is one seller who dropped their price, and the
# current asking price is ₹35L. Without this list the dashboard showed the
# stale ₹42L while the price-history timeline correctly recorded the drop —
# the two disagreeing on the same page, with the wrong one in the ranking.
VOLATILE_FIELDS = frozenset({
    "asking_price", "price_per_acre", "price_per_acre_stated", "negotiable",
    "motivation_signals", "motivation_level_hint", "source", "source_url",
    "raw_text",
})


@dataclass
class ClaimSet:
    """The claims for one property, keyed by field name.

    Merging is the interesting part. The same parcel shows up on MagicBricks,
    in a YouTube walkthrough and in a broker's WhatsApp forward, each
    asserting slightly different things. `merge` keeps the *best-evidenced*
    claim per field rather than the newest — except for VOLATILE_FIELDS,
    where newest wins because the value genuinely moves.
    """

    claims: dict = field(default_factory=dict)

    def get(self, key: str) -> Claim:
        c = self.claims.get(key)
        return Claim.from_dict(c) if c is not None else Claim.unknown()

    def set(self, key: str, claim: Claim) -> None:
        self.claims[key] = claim

    def value(self, key: str, default=None):
        c = self.get(key)
        return c.value if c.known else default

    def add(self, key: str, claim: Claim) -> None:
        """Add a claim, keeping whichever is better evidenced."""
        existing = self.claims.get(key)
        if existing is None:
            self.claims[key] = claim
            return
        cur = Claim.from_dict(existing)
        if not claim.known:
            return
        if not cur.known:
            self.claims[key] = claim
            return
        # Strictly better evidence always wins, for every field.
        if LEVELS.index(claim.confidence) < LEVELS.index(cur.confidence):
            self.claims[key] = claim
            return
        if claim.confidence != cur.confidence:
            return                      # incoming is weaker; keep what we have

        # Equal evidence. For a value that moves, the newer observation is
        # the current truth — a relisted price supersedes the old one.
        if key in VOLATILE_FIELDS:
            if str(claim.value) != str(cur.value):
                claim.note = (f"{claim.note}; was '{cur.value}' "
                              f"({cur.observed_at})").strip("; ")
            self.claims[key] = claim
            return

        # For a stable value, equal evidence keeps the earlier claim and
        # records the disagreement rather than silently picking one. Two
        # sources contradicting each other about water at the same confidence
        # is a fact about the property, and a question to ask the seller.
        if str(claim.value) != str(cur.value):
            note = f"conflicts with '{claim.value}' from {claim.source or 'another source'}"
            cur.note = f"{cur.note}; {note}".strip("; ")
            self.claims[key] = cur

    def merge(self, other: "ClaimSet") -> None:
        for k, v in (other.claims or {}).items():
            self.add(k, Claim.from_dict(v))

    def conflicts(self) -> list[str]:
        """Fields where sources disagree at equal confidence. Surfaced on the
        property page — a contradiction is a question to ask the seller."""
        out = []
        for k, v in (self.claims or {}).items():
            c = Claim.from_dict(v)
            if "conflicts with" in (c.note or ""):
                out.append(f"{k}: {c.value} — {c.note}")
        return out

    def to_dict(self) -> dict:
        return {k: Claim.from_dict(v).to_dict() for k, v in (self.claims or {}).items()}

    @classmethod
    def from_dict(cls, d) -> "ClaimSet":
        return cls(claims={k: Claim.from_dict(v) for k, v in (d or {}).items()})


def seller(value, source: str = "listing", note: str = "") -> Claim:
    """Shorthand for the common case — the listing said so."""
    return Claim(value=value, source=source, confidence=SELLER_CLAIM, note=note)


def inferred(value, source: str = "computed", note: str = "") -> Claim:
    return Claim(value=value, source=source, confidence=INFERRED, note=note)


def observed(value, source: str = "listing media", note: str = "") -> Claim:
    return Claim(value=value, source=source, confidence=OBSERVED_FROM_MEDIA, note=note)


def verified(value, source: str, note: str = "") -> Claim:
    """Only for things a document or professional actually confirmed. The
    required `source` is deliberate: 'verified' with no cited document is
    how unverified things become verified."""
    return Claim(value=value, source=source, confidence=VERIFIED, note=note)
