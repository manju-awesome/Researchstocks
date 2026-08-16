# Findfarms — Mysuru Retirement Farmland Discovery & Deal Intelligence

A local research system for buying agricultural land around Mysuru, Karnataka —
for retirement living, family use and sustainable agriculture.

Target: **within ~30 km of Mysuru**, preferring the 10–30 km band; **1–5 acres**
preferred, 0.5–10 acres accepted; optimising for **legal safety + water security
+ agricultural productivity + retirement livability + fair price**, in that
order. Explicitly *not* optimising for the cheapest land.

Stdlib-only Python. No database, no framework, no API keys required. State lives
in flat JSON under `data/`.

---

## Quick start

```bash
python3 scripts/seed_demo.py --reset
```

```bash
python3 src/findfarms/webapp/app.py
```

Then open <http://localhost:8877>. Run the tests with:

```bash
python3 -m unittest discover tests
```

The seed script loads 14 **invented** example listings (not real properties) so
the dashboard has something to show and the scoring behaviour is inspectable.
Delete `data/properties.json`, `data/observations.json` and
`data/price_history.json` when you start entering real listings.

---

## The one idea everything rests on

A land listing is mostly assertions by someone who profits from you believing
them. The usual failure of a property tool is that those assertions get stored
in a field called `water_source` and become indistinguishable from facts — six
weeks later a property scores 88 and nobody can say why.

So nothing here is stored as a bare value. Every field is a **Claim**:

```python
Claim(value="borewell", source="MagicBricks listing #4471",
      confidence=SELLER_CLAIM, observed_at="2026-08-14")
```

The scoring engines read the confidence, not just the value. A seller-claimed
borewell and a borewell you watched run for 45 minutes are the same word and
never the same score.

| Confidence | Means | Scoring weight |
|---|---|---|
| ✅ `VERIFIED` | A document was read, or a professional confirmed it | 100% |
| 👣 `SITE_VISIT` | You or someone you sent physically observed it | 97% |
| 📷 `OBSERVED_FROM_MEDIA` | Visible in a listing photo or video | 90% |
| 🗣 `THIRD_PARTY` | A neighbour or local official said so | 85% |
| 💬 `SELLER_CLAIM` | The listing said so — **the default** | 80% |
| 🧮 `INFERRED` | This system computed it | 85% |
| ❔ `UNKNOWN` | No information — *distinct from a "no"* | 0% |

Because scores are recomputed from stored claims on every page load, verifying
something visibly moves the numbers. Record a pump test and the water cap lifts;
record an EC and the legal screen can leave `UNKNOWN`.

---

## Scoring

**DEAL_SCORE /100** — legal 25%, water 25%, agriculture 15%, location 10%,
price 10%, retirement 10%, optionality 5%. Then categories A–E.

### Gates beat weights

A weighted average always lets a strong factor carry a fatal one. So gates are
applied on top of the score:

| Gate | Effect |
|---|---|
| Legal hard stop (PTCL, gomala, forest, acquisition, tenancy) | `DO NOT PROCEED`, dropped from every ranked list |
| Legal risk `UNKNOWN` | Capped at **74** — nothing from an advert reaches category A |
| Water score < 35 | Capped at **55** — water is what money cannot add |
| Size outside 0.5–10 acres | Flagged, not rejected |

The legal component is scored on **evidence held**, not on the absence of bad
news. A listing mentioning no documents scores near zero there, not neutral —
otherwise the listings with the least information float to the top, because
there is nothing to hold against them. That is the most common way these
systems go wrong.

### The five engines

- **`water.py`** — `WATER_SCORE`. Ranks canal > multiple sources > borewell +
  open well > proven borewell > seasonal > unverified claim > none. **Capped at
  55 when every claim is unverified**, so seller enthusiasm cannot outrank
  observed water. Two traps refused explicitly: river proximity is not an
  irrigation right, and a deep borewell is a negative signal about the local
  table, not a positive one about the investment.
- **`agriculture.py`** — `AGRICULTURE_SCORE`. Water carries 30 of 100 (not
  double counting — unirrigated land in this belt is worth little regardless of
  soil). Established perennials score above annual crops: they yield with modest
  labour and survive a neglected season. Size is scored *against the 1–5 acre
  target*, so ten acres is penalised, not rewarded.
- **`retirement.py`** — `RETIREMENT_SCORE`. Built around the days that go wrong.
  Land appreciation is deliberately **not** a factor. Weights total exactly 100
  (there is a test guarding that):

  | Factor | Wt | Why |
  |---|---|---|
  | Road access & **main-road connectivity** | 22 | The unpaved last mile decides whether everything else is reachable in August |
  | Healthcare access | 20 | Irreversible when it fails |
  | Distance to Mysuru | 14 | For how often family actually come |
  | Water for living | 13 | Drinking and washing, not irrigation |
  | Community / neighbours | 10 | Isolation is the quiet killer of rural retirement plans |
  | Power + connectivity | 8 | Ambulance calls, telemedicine, banking |
  | **Yoga / wellness access** | 7 | Mysuru-specific; a daily practice is one of the few things that structures a retirement |
  | **Schools (family use)** | 4 | Grandchildren staying a term, and caretaker families willing to live nearby |
  | Existing structure | 2 | Somewhere to stay from day one |

  **Connectivity to a main tarred road** is a distinct question from road
  frontage and a more decisive one: frontage only says the parcel touches *a*
  road, which may be a mud lane. Bands run `ON_MAIN_ROAD` → `POOR`, and an
  unpaved approach past 500 m costs a whole band. Sellers state this figure when
  it is good and omit it when it is not, so silence is recorded as `UNKNOWN` and
  becomes a question — never read as zero.

  **Yoga and schools are tie-breakers by design.** At 7 and 4 points they can
  separate two otherwise comparable parcels but can never carry a parcel with no
  water past one that has it — there is a test for that too. Their distance
  thresholds are much tighter than healthcare's, because trip frequency is
  inverted: a hospital 20 km away is acceptable (rare trips, under duress), a
  yoga class 20 km away is a trip you stop making within a month.
- **`legal.py`** — `LEGAL_RISK`. `LOW` requires positive documentary evidence at
  verified confidence and is **unreachable from an advertisement by
  construction**. Most properties sit at `UNKNOWN` forever, which is the honest
  answer. Hard stops are the specific Karnataka failure modes that unwind a
  completed sale years later.
- **`watershed.py`** — `HARVEST_SCORE`, and the question `water.py` doesn't
  answer. Where `water.py` asks *what water does this parcel have*, this asks
  *what water could it have* — kept separate because one is an observation and
  the other is a plan. Three inputs:
  - **River distance** to the Kaveri and Kabini, computed from polylines of each
    river's course, not from the seller's claim (which is stored separately and
    shown alongside). Scored as **groundwater context only** — the rule that
    river proximity is not an irrigation right is restated at every band. Very
    close is a *mixed* signal, not a good one: buffer-zone restrictions and
    flood exposure live there.
  - **Rainfall** by taluk. The gradient is large and runs against the distance
    preference — ~700 mm at Nanjangud and T. Narasipura against 1000+ mm at
    H.D. Kote and Periyapatna, and the wetter taluks are the further ones.
  - **Undulation.** The counter-intuitive one: **a gentle fall beats dead-flat
    land** for harvesting, because runoff concentrates at a natural low point
    where a pond sites itself and gravity distributes the water without a pump.
    `agriculture.py` marks undulating land *down* (harder to plough) while this
    marks it *up* — that disagreement is correct, and there's a test asserting
    both still say so.

  Output includes worked volumes — gross rainfall, runoff, and *realistically*
  harvestable (runoff × 0.6 capture) — plus a suggested farm-pond size. All
  three are reported because quoting only the gross figure, which is what
  harvesting marketing tends to do, oversells a pond by roughly four times.

  Harvesting potential feeds only **8 points** into `WATER_SCORE`, applied
  *before* the evidence cap, so a dry parcel with an ideal slope can never look
  wet. It matters as a tie-breaker and a rescue path: of two parcels with
  equally mediocre borewells, the one that can be made wet is worth more.

- **`price.py`** — `PRICE_POSITION`. Comparables from the system's own database
  in widening rings, adjusted for size, water tier and road frontage. Below
  three comparables it returns `UNKNOWN` and says why — two listings is not a
  market. Everything compared is an *asking* price, not a recorded sale.

---

## Why the database matters more than the scraper

> Hunsur Road — 1.8 acres — ₹42L/acre.
> Six months later: same property — ₹35L/acre — urgent sale.

That is worth more than a hundred new listings, and it only exists if the same
parcel resolves to the **same record** every time it is re-discovered.

`dedup.py` matches on published phone number, survey number, coordinates,
village, acreage (with tolerance, because the same parcel is advertised as
"2.5 acres", "2 acre 20 gunta" and "2.4 acres") and description similarity. It
is deliberately conservative: a false merge fuses two parcels' claims into one
incoherent record, so near-misses are surfaced for confirmation rather than
merged automatically.

`store/db.py` enforces the rule that makes this work: **re-discovery updates the
existing record, it never inserts a second one.** Price is excluded from the
canonical ID for exactly this reason — a price drop must not create a new
property.

---

## Discovery: read this before expecting it to fill itself

**Autonomous collection covers almost nothing here, by design and by law.**

| Policy | Sources |
|---|---|
| `MANUAL_ONLY` | MagicBricks, 99acres, Housing.com, OLX, Quikr, Facebook, Instagram, search engines, local broker sites |
| `API_REQUIRED` | YouTube (needs your own Data API key) |
| `OPEN` | Reddit — though its robots.txt currently disallows generic crawlers, so the gate refuses these too |

The major portals prohibit automated collection in their **terms of use**, which
robots.txt does not override — MagicBricks' robots.txt permits crawling that its
terms forbid, which is precisely why the policy layer sits above the robots
layer. Facebook and Instagram require authentication for essentially everything.

This system does not scrape them, does not hold credentials anywhere in the
codebase, and does not work around access controls. Instead:

- `discovery/robots.py` is a **chokepoint**: no HTTP request can leave without
  passing `may_fetch`, which **fails closed** — an unreadable robots.txt means
  refusal, not permission. Per-host rate limiting is enforced, never below a
  2-second floor regardless of what a host permits.
- `discovery/sources.py` generates the full **keyword × geography matrix** (336
  combinations, 594 searches across 11 sources) as links for you to open.
- The **Add Listing** page takes pasted text from anywhere — a portal, a
  broker's WhatsApp message, a YouTube description, a photo you transcribed.

That intake is not a workaround. Around Mysuru the best listings reach you
through brokers, WhatsApp and village contacts anyway, and no crawler was ever
going to see them. Everything the system is actually *for* — deduplication,
independent geolocation, evidence-weighted scoring, price history over months —
works identically whether the text arrived by crawler or by paste.

---

## Human-in-the-loop

```
DISCOVER → EXTRACT → DEDUPLICATE → GEOLOCATE → SCORE → RISK SCREEN
  → [ HUMAN REVIEW ] → SELLER CONTACT → DOCUMENT COLLECTION → SITE VISIT
  → LAWYER → SURVEYOR → NEGOTIATION → PURCHASE DECISION
```

Everything before the bracket is automated. Nothing after it is, and **nothing
in this system will ever recommend buying land**. Each property page generates
three tailored lists: what is missing (the call-the-seller list), the
site-visit checklist ordered by what is hardest to undo, and the documents to
obtain.

---

## Layout

```
Findfarms/
├── data/
│   ├── properties.json          canonical parcels — never duplicated
│   ├── observations.json        append-only log of every sighting
│   ├── price_history.json       per-property price timeline
│   ├── discovery_log.json       every fetch attempt + its robots decision
│   └── reference/villages.json  seed gazetteer (approximate centroids)
├── scripts/seed_demo.py
├── src/findfarms/
│   ├── core/      units, claims, geo, extract, dedup, water, agriculture,
│   │              retirement, legal, price, motivation, deal, checklists,
│   │              pipeline
│   ├── discovery/ robots (the compliance gate), sources, ingest
│   ├── store/     db
│   └── webapp/    app, views, pages
└── tests/test_core.py
```

---

## Known limits

- **Driving distances are estimated, not routed.** Straight-line × a corridor
  circuity factor (1.15 highway → 1.45 village road). Good to a few km. Measure
  the real one on the visit.
- **Village coordinates are approximate centroids**, none field-verified. A
  parcel can sit several km from its village centre. A parcel positioned at a
  centroid gets a 2 km floor on local amenity distances, and says so.
- **All amenity distances are town-level** — "12 km to a town with hospital
  facilities", not to a specific verified hospital, shala or school. Yoga and
  wellness cluster far more tightly than the rest: around Mysuru they are
  concentrated in the city, chiefly **Gokulam**, which is a separate gazetteer
  entry for that reason. Proximity to a shala is not a place at one — the
  established Mysuru schools run waiting lists and fixed terms.
- **A parcel positioned at its village centroid gets a 2 km floor** on every
  amenity distance, and says so. Farmland is the land *around* a village, not
  its centre, so an unfloored figure reads as "schools 0.0 km".
- **Extraction is deterministic keyword matching, no LLM.** Phrasing it hasn't
  seen becomes `UNKNOWN` rather than being guessed at. Deliberate: an unknown
  field becomes a question to ask, a hallucinated one becomes a score.
- **Comparables are asking prices**, which run above achieved prices here. The
  bias largely cancels when comparing like with like; the absolute level is
  inflated. The government guidance value is flagged as the one externally
  anchored number, and is a question rather than a guess.
- **River courses are 7–9 point polylines**, so a computed distance is good to
  roughly **±2 km**. Anything under 2 km is reported as "within ~2 km, below
  data resolution" rather than a number — that is the band where buffer-zone and
  flood restrictions live, so it is the band where false precision costs most.
  It will not tell you whether a parcel is inside a river buffer; that needs the
  revenue map and a licensed surveyor.
- **Rainfall is a taluk-level long-period average.** Check the specific hobli
  against KSNDMC gauge data. And note that the annual total is a weak guide on
  its own: ~55–60% falls June–September, leaving a five-month dry spell, so
  storage decides whether a parcel carries itself through April.
- **Harvest volumes are estimates from approximate inputs** — a taluk rainfall
  average, a slope read from the listing's wording, and standard runoff
  coefficients. Enough to frame a conversation with a watershed engineer, not to
  replace one.
- **The gazetteer is thin** — ~37 places. An unrecognised village costs
  coverage, never accuracy: the parcel is reported as location-unresolved rather
  than positioned by guesswork. Add entries to `data/reference/villages.json` as
  you meet them.

---

## ⚖️ Legal notice

Every legal output of this system is a **preliminary screening result, not legal
advice and not a title clearance**. It reads advertisements, not documents. It
can raise concerns; it can never confirm that a title is good.

Before any advance, agreement or payment, engage a property lawyer in Mysuru who
does agricultural title work, and a licensed surveyor. Separately confirm your
eligibility to purchase agricultural land in Karnataka and the extent you may
hold — this is governed by the Karnataka Land Reforms Act, has changed
materially in recent years, and is a question about the buyer rather than about
any parcel.
