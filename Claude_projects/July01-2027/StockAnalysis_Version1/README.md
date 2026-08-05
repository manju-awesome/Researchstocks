# StockAnalysis — Trading Workstation

A local, single-user trading research workstation: S&P 500 / watchlist scanning,
signal grading, conviction scoring, walk-forward backtesting, a priority alert
engine with email digests, and a stdlib-only web UI — all built on **yfinance**
as the only market-data dependency (plus Resend for email and, optionally, the
Claude API for AI-generated summaries and trade coaching).

Everything runs on `localhost` from one Python process. No database, no
external services to stand up — state lives in flat JSON/CSV files under
`data/` (a deliberate choice for a single-user tool; see the docstring in
`src/stockanalysis/webapp/app.py` for the reasoning).

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in RESEND_API_KEY etc. (see Configuration)

# Web app (http://localhost:8899)
python src/stockanalysis/webapp/app.py

# One-off scan from the command line
python -m stockanalysis.scanners.scan_universe

# Scheduler (all timed jobs: scans, briefs, alert monitors)
python -m stockanalysis.scheduling.scheduler

# Tests (no network — all yfinance calls are mocked)
python -m unittest discover tests

# Verify email setup end-to-end
python3 scripts/send_test_alert.py
```

Run from the repo root with `src/` on `PYTHONPATH` (the entry points handle
this themselves when run directly).

---

## Web app pages

`webapp/app.py` serves nine pages (stdlib `http.server`, background jobs as
daemon threads via `jobstore.py`, page HTML in `pages.py`/`views.py`, job and
JSON-endpoint logic in `api.py`). Binds `127.0.0.1` only — no auth, don't
expose it beyond localhost.

### 🏠 Dashboard (`/`)
Home page: latest generated HTML report per universe, market-pulse snapshot
(VIX, SPY/QQQ strength, mega-cap concentration), quick links to recent scan
CSVs, and an AI Sentiment teaser card.

### 🤖 AI Sentiment (`/ai-sentiment`)
The AI-infrastructure market dashboard. `scanners/ai_pulse.py` fetches tiered
AI leaders (Leadership / Networking / Power), 10Y yield, DXY, SOXX, and NVDA
VWAP; `core/ai_sentiment.py` turns those into five deterministic readings:
**Risk Score**, **Rotation Detection**, **AI Health Index**, **Macro Event
Filter**, and a composite **AI Market Sentiment Score** — pure functions, unit
tested with synthetic fixtures.

### 📡 Scanner (`/scanner`)
Run a scan against any universe — built-ins (`daytrade`, `watchlist`,
`longterm`, `dividend`, `sp500`) or any user-curated watchlist from
`data/watchlists.json` — with a live pipeline-step progress view
(fetch → scan → grade → write → research) instead of a spinner.

### 🔎 Research (`/research`)
Per-ticker research: search any symbol, browse the generated mini research
pages (`data/output/research/<TICKER>.html` — self-contained HTML with an
inline-SVG chart, EMA/MA overlays, trade-plan level lines, full metric tables,
catalysts, strategy scores, conviction verdict, plain-language summary), and
run the **earnings sentiment engine** (`core/earnings_sentiment.py`): a
deterministic, yfinance-only scoring model that predicts the likely
post-earnings reaction (bullish/bearish split, expected move, confidence,
risk level, trading bias) — same inputs, same output, reproducible.

### 💼 Portfolio (`/portfolio`)
Positions and watchlist from `data/portfolio.csv` (copy
`data/portfolio_template.csv` to start), joined with the latest scan rows:
live P&L per position plus rule-based alerts — stop breach, strategy filters
degrading, earnings inside the blackout window, category flipped to Avoid.
Add/edit positions from the page via a modal form. Below the holdings table,
an **Options** card lists open contracts from `data/options_positions.csv`
(strike/expiry, contracts, premium, P&L, days-to-expiry warnings) — see
**Broker sync** below.

### 📓 Journal (`/journal`)
AI-coached trade journal (`core/trading_journal.py`). Log each trade's plan,
execution, psychology, and rule adherence; the page computes R-multiple,
return, and expectancy, and breaks results down by setup, emotion, and rule
violation, with monthly stats. With `ANTHROPIC_API_KEY` set, an **AI Review**
button sends the trade to Claude for an objective post-mortem (grades, top
mistakes/strengths, one sentence of coaching). Storage:
`data/journal_trades.json`.

### 🔔 Alerts (`/alerts`)
The alert feed: every active alert from the priority engine (see below), plus
the latest **Pre-Market Brief** rendered inline. MEDIUM/LOW alerts live here
only; CRITICAL/HIGH also went out by email when they fired.

### ⚡ Day Trade (`/daytrade`)
The SPY 0DTE options day-trader — the one section not backed by
`stockanalysis.*`. See **Day Trade** below.

### ⚙️ Automation (`/automation`)
Scheduler status and job history: what ran, when, how long it took, what
failed — the web view onto `jobstore`'s bounded job history.

---

## Day Trade — `src/spydaytrader/`

An independent second engine sharing this app: a Python translation of the
`SVMKR_UT_HMA_ORB` TradingView Pine Script (kept at `docs/pine/`) driving a
human-approved SPY 0DTE options pipeline on Robinhood. It was previously its
own project on port 8900; it now runs inside the workstation.

**"Independent" is literal.** `spydaytrader.core` imports nothing from
`stockanalysis.core` and vice versa — the swing scanner and the day-trader
share this server, the page layout (`spydaytrader/webapp/pages.py` renders
through `stockanalysis.webapp.views`) and the market-regime scorer, and
nothing else. In particular they do **not** share state: SPY's proposals and
journal live under `data/spy/`, because `data/trade_proposals.json` and
`data/journal_trades.json` already belong to the swing side with incompatible
schemas (share-based vs. options).

| Piece | What it does |
|---|---|
| `core/` | Pure logic: indicators, signal engine, signal dedup, proposal lifecycle, position sizing. No network, no broker. |
| `daemon/scheduler.py` | Polls SPY every 30s during market hours, runs the signal engine, writes proposals. Runs on a background thread in the webapp (`--no-spy-daemon` to disable), or standalone. |
| `webapp/pages.py` | The `/daytrade` and `/daytrade/proposals` page bodies. |
| `scripts/spy_prepare_order.py` | All order arithmetic and disk writes for placement. |
| `scripts/spy_check_premium_exits.py` | The premium stop/target half of the exit rule. |

### Order placement is deliberately unreachable from here

The daemon and the dashboard can move a proposal to `approved` and no further,
so a misclick on a web page can never spend money. Reaching `placed` happens
only in a Claude Code session via the Robinhood MCP tools, with an explicit
per-order confirmation — see the `spy-place-approved-trade` skill. Don't add an
auto-place path; the split *is* the safety model.

### Exit rule: two halves, two runtimes

"Whichever comes first" — underlying signal flip, or premium stop/target
(−35%/+60%). Different data, so different processes:

| Half | Checked by | Data source |
|---|---|---|
| UT Bot signal flip | the daemon | yfinance SPY bars |
| Premium stop/target | `spy-premium-exit-check` scheduled task | Robinhood connector |

The daemon has no broker session and cannot see option premiums, hence the
split. Both halves only ever write a `pending_review` exit proposal; neither
closes a position.

> ⚠️ **This is not a hard stop-loss.** The scheduled task only runs while the
> Claude app is open, so a five-minute polling loop is a monitoring aid, not a
> guaranteed stop. On a fast 0DTE move the premium can travel far past −35%
> between checks. For a stop you can rely on, place a broker-side stop order
> with Robinhood at entry time and treat the task as a notifier on top of it.

---

## Alert & notification system

### Priority alert engine — `core/alerts.py`
One Alert shape for the whole app: `CRITICAL / HIGH / MEDIUM / LOW` priority,
a dedup/lifecycle store (`data/alerts_state.json`) so a standing condition
("NVDA is oversold") notifies **exactly once** and re-arms only after it
resolves, and an append-only log (`data/alerts_log.json`). CRITICAL and HIGH
batch into a **single digest email** per cycle (never one email per alert);
MEDIUM/LOW surface in the webapp feed only.

### Earnings alerts — `core/earnings_alerts.py`
Watchlist tickers with earnings coming up, gated by size so routine reports
don't fire: market cap > $2B **and** (expected move ≥ 5% **or** historical
avg earnings move ≥ 6%). Three day-granularity tiers:

| Tier | When | Priority | Delivery |
|------|------|----------|----------|
| `T-5` | 2–5 days out (fires once anywhere in the window) | MEDIUM | Alerts feed |
| `T-1` | day before | HIGH | Email + feed |
| `T-0` | day of | HIGH | Email + feed |

### Watchlist alerts — `core/watchlist_alerts.py`
Boolean conditions over already-computed scan fields — support/resistance
touch, breakout/breakdown, gap, volume surge, RSI extremes, MACD cross — each
condition's "currently true" state doubling as its dedup key: fire once when
it turns true, go quiet until it turns false and true again.

### Breaking news monitor — `core/news_monitor.py`
Scans watchlist headlines and alerts only on categories that plausibly move a
stock >3% (earnings surprise, M&A, guidance, regulatory…), reusing the same
catalyst classifier the dashboard's movers use. Runs on the 10-minute monitor
cadence.

### Pre-Market Brief — `core/premarket_brief.py`
The 7:00 AM "under 5 minutes to read" email: futures, VIX, econ calendar,
overnight/pre-market movers with catalysts, today's watchlist earnings, and
stocks near breakout (read from already-active alerts — no fresh scan).
Rendered as text + HTML, emailed, and shown on the Alerts page.

### Email delivery
All email goes through one sender: `market_movers.send_resend_email()`
(Resend SDK with a raw-HTTP fallback). Sandbox note: with the default
`onboarding@resend.dev` from-address, Resend only delivers **to the address
your Resend account is registered under**. Test the pipeline any time with
`python3 scripts/send_test_alert.py`.

---

## Scanning & scoring pipeline

The scan entry point is `scanners/scan_universe.py`: for every ticker it
fetches metrics, classifies a category, grades the setup, scores conviction
and strategy fit, and writes one CSV per run
(`data/output/stock_scan_YYYYMMDD_HHMM.csv`, `Scan_Time` = completion stamp)
plus the HTML dashboard and per-ticker research pages.

### The market funnel (pre-filter)

Big universes don't go straight to the per-ticker scan loop:

```
Universe → Market Regime → Sector Strength → Scanner
```

`scanners/sector_filter.py` + `core/sector_strength.py`: sectors are ranked
by their proxy ETF's return **relative to SPY** (0.6 × 1-month + 0.4 ×
3-month), and the day's regime sets selectivity — Bullish keeps the top 5
sectors, Neutral 4, Defensive 3. Only tickers in those sectors continue to
the scan, typically cutting an S&P 500 run by 60–80%.

Mechanics: ticker→sector lookups are cached
(`data/cache/ticker_sectors.json`) and seeded from prior scan CSVs, so the
funnel itself costs ~1 batch ETF download. It **fails open** — missing ETF
data, regime, or sector info means the name (or whole universe) scans
anyway. Auto-applies at ≥ 100 tickers (i.e. `sp500`), never to curated
watchlists; override with `--focus` / `--no-focus`.

| Module | What it does |
|--------|--------------|
| `core/metrics.py` | ~45 technical + fundamental metrics per ticker (native RSI/ADX/%B with Wilder's smoothing — no pandas_ta — plus ATR, RVOL, gaps, RS vs QQQ, VWAP, CANSLIM composite, entry gate). Daily-bar math lives in a pure `compute_daily_metrics()` so the backtest can reuse it point-in-time. |
| `categorize()` (in `scan_universe.py`) | Structured decision tree classifying each row: Momentum Breakout, Momentum-Pullback, VCP Setup, Turnaround, Longterm Hold, Avoid. |
| `core/grade_signals.py` | A/B/C grade + Entry / Stop / Target / Notes per categorized row. |
| `core/conviction.py` | Splits "should I take this?" into Quality (company), Setup (trade), Timing (now) — each 0–100 — plus overall score, 1–5 stars, and a ✅/⚠/❌ "why this stock" checklist. |
| `core/strategy_scores.py` | Three strategy-specific 0–100 scores with hard-filter pass flags: `Investment_Score` (6–24 mo), `Swing_Score` (2 d–8 wk), `DayTrade_Score` (intraday). |
| `core/key_levels.py` | Nearest support (S1) / resistance (R1) from 5-min swing pivots + volume profile merged with daily structural levels, scored on a 7-factor weighted formula. |
| `core/call_candidate.py` / `core/put_candidate.py` | Options-buying screens with hard disqualifiers: cheap-call turnaround setups and put-candidate scoring, attached to every scanned row. |
| `core/market_regime.py` | Classifies the day Bullish / Neutral / Defensive from VIX + index strength + breadth, and scales position-size multipliers per horizon accordingly. |

### How the dashboard's Top-5 scores are decided

Every card in the scanner HTML carries a number badge and a letter grade. This
section is the full derivation of the three most-asked-about sections —
**Long-Term**, **Puts**, and **Swing** — because the number on a card does not
come from the same place for all three.

#### First: there are two different score families

This is the single most common source of confusion when reading the report.

| Family | Range | Computed in | Used by |
|--------|-------|-------------|---------|
| **Strategy scores** — `Investment_Score`, `Swing_Score`, `DayTrade_Score` | 0–100, bounded, each with a `*_Pass` flag and a `*_Reason` string | `core/strategy_scores.py` (`score_investment` / `score_swing` / `score_day_trade`) | The **CSV** columns, the Research Library, alerts |
| **Card ranks** — `day_card_rank`, `swing_card_rank` | unbounded additive (~0–125 in practice), `-999` = not rankable | `core/strategy_scores.py`, bottom section | The **dashboard Top-5 cards** for Day Trade and Swing |

So the badge on a Swing card — the "Score 113" — is **`swing_card_rank`, not
`Swing_Score`**. They use overlapping inputs but different weights and different
scales, and a name can rank high on one and middling on the other. The Long-Term
and Puts cards, by contrast, badge the strategy/candidate score directly:

| Card section | Badge number is | Source |
|--------------|-----------------|--------|
| Day Trade | `day_card_rank(row)` | unbounded card rank |
| Swing Trade | `swing_card_rank(row)` | unbounded card rank |
| Long-Term | `Investment_Score` | 0–100 strategy score |
| Calls | `Call_Score` | `core/call_candidate.py` |
| Puts | `Put_Score` | `core/put_candidate.py` |

#### The entry gate is the kill switch for three of the five sections

`core/metrics.py` step 6 sets `Entry_Gate_Pass` by testing four conditions.
Any failure records the reason in `Entry_Gate_Reason`:

| Check | Threshold |
|-------|-----------|
| Market cap | ≥ $1B |
| Price | ≥ $5 |
| ADX(14) | ≥ 15 — skipped entirely when ADX is `None` |
| Price vs 200MA | not more than 30% below |

An RVOL ≥ 0.6 gate exists in the source but is **currently commented out**
(`metrics.py:794-797`), so low-volume names are not gated today.

Failing the gate forces `Swing_Score`, `DayTrade_Score`, `day_card_rank`,
`swing_card_rank`, `_call_score` and `_put_score` to zero or `-999` — those
sections have no tradeable plan without it. `Investment_Score` deliberately
**survives** a gate failure: a 6–24 month accumulation does not need a trend
already in place, so a flat-ADX name can still be a long-term buy.

#### Long-Term scoring (`score_investment`)

Two independent things decide whether a name appears on a Long-Term card.

**1. `Investment_Score`, 0–100 additive.** Eight buckets, best matching tier wins
within each bucket; missing data simply forfeits that bucket's points:

| Bucket | Points |
|--------|--------|
| Leadership — `RS_Rank` | 25 if > 80 · 15 if ≥ 60 · 8 if ≥ 40 |
| Earnings growth — `EPS_Growth%` | 20 if > 25% · 12 if > 15% · 5 if > 0 |
| Revenue growth — `Revenue` | 15 if > 20% · 9 if > 10% · 4 if > 0 |
| Stage — `Above_200MA` | 10 |
| Cash generation — `FCF_Positive` | 10 |
| Execution — `EarningsBeat` | 10 |
| Sponsorship level — `Inst_Own%` ≥ 40 | 5 |
| Sponsorship trend — `Inst_Own_Chg` > 0 | 5 |

**2. `Investment_Pass` — all six primary filters, hard AND.** `RS_Rank` > 80,
EPS growth > 25%, revenue growth > 20%, above the 200MA, FCF positive, last
earnings a beat. `_longterm_score()` returns `-999` for anything without the
pass flag, so **a high-scoring name that fails one filter never reaches a
card** — it stays in the CSV for review. That is why the section is titled
"all filters pass".

*Consequence worth knowing:* the six pass filters are worth exactly 90 of the
100 points, so every Long-Term card scores **90–100** and only the two 5-point
sponsorship bonuses move it. Against the grade bands below that means Long-Term
cards can only ever render **A** (90–94) or **A+** (95+) — the B+/B/C bands are
unreachable for this section by construction.

**`RS_Rank` is derived, not raw.** The scan's `RS` column is raw 3-month excess
return vs QQQ in percentage points, so "RS > 80" cannot be applied to it
directly. `attach_rs_rank()` converts it to a 0–99 **percentile within the
scanned universe**. This makes `RS_Rank` relative to what you scanned: the same
ticker gets a different rank in an S&P 500 run than in a 30-name watchlist run.
Below 20 tickers a percentile is noise, so a fixed absolute mapping of excess
return is used instead (`_rs_rank_fallback`).

**`LT_Entry_Timing`** is attached alongside and answers a different question —
not "is this worth owning" but "is now a good time to start" (below 200MA / base
forming / extended +50% vs 200MA → tranches only). It is advisory text, never a
filter. **`Buy_Zone_Score`** (`core/buy_zone.py`) is a third, separate axis: an
8-factor weighted blend (30% fundamental quality, 20% technical trend, 15%
valuation, 10% pullback depth, 10% volume accumulation, 5% each institutional /
RS / catalysts) that renormalizes over whatever factors have data and returns
`None` below 50% weight coverage rather than guessing.

#### Put options scoring (`compute_put_candidate`)

Puts are scored as an **exhaustion/fade screen**, not a downtrend screen — it
looks for strong names running out of buyers, not names already broken.

**Hard disqualifiers run first.** Either one forces `Put_Score = 0`,
`Put_Candidate = False` and a `DISQUALIFIED:` reason, regardless of any signal:

- `ADX > 38` **and** `RS > 50` — trend too strong; overbought can persist for weeks
- `RS > 80` — institutional accumulation, do not fade strength

**Then five signals accumulate a small integer score:**

| Signal | Points |
|--------|--------|
| Near 52W high set within 10 days (`Dist_52W_High%` ≥ −8) — parabolic | +2 |
| Price > 5% above 8EMA — extended | +2 |
| Price 3–5% above 8EMA | +1 |
| `RSI_14` > 72 — overbought | +3 |
| `RSI_14` 68–72 — stretched | +2 |
| `RVOL` < 0.7 — buyers exhausted (the strongest single signal) | +3 |
| `RVOL` 0.7–0.9 — volume fading | +2 |
| `Vol_vs_20D` < 0.9 — below 20-day average (only if RVOL ≥ 0.9) | +1 |
| `BB_PctB` > 1.0 — closed above the upper band | +2 |
| `BB_PctB` 0.85–1.0 — approaching upper band | +1 |
| `ADX_14` > 35 — strong trend, soft penalty | **−1** |

`Put_Candidate` is `True` at **score ≥ 5**. `_put_score()` returns `-1.0` for
non-candidates and the Top-5 filter keeps only scores > 0, so **only confirmed
candidates ever render a Put card**. Practical range on a card is 5–12.

*Quirk worth knowing:* put candidates must also pass the same long-biased
`Entry_Gate_Pass`. A stock more than 30% below its 200MA, or with ADX < 15,
is gate-failed and can never surface as a put — even though those are exactly
the conditions a bearish screen might want. Combined with the ADX > 38
disqualifier and the ADX > 35 penalty, the workable band is roughly ADX 15–35.
This is intentional for a fade-the-exhaustion strategy but it means **this
screen will not find you puts in a bear market**.

#### Swing trade scoring

The dashboard card ranks by **`swing_card_rank`** — unbounded, `-999` when the
entry gate failed or the category is `Avoid`:

| Component | Points |
|-----------|--------|
| Category | Momentum-Pullback 30 · VCP Setup 28 · Momentum 20 · Turnaround 10 |
| `RS` (raw excess vs QQQ) | ≥50 → 20 · ≥20 → 14 · ≥0 → 8 · ≥−10 → 2 · else **−8** |
| Bollinger coil `BB_PctB` | ≤0.1 → 18 · ≤0.2 → 14 · ≤0.3 → 10 · ≤0.4 → 6 |
| `ATR Shrinking` | 12 |
| Pullback volume `Pullback_Vol_Ratio` | ≤0.6 → 10 · ≤0.8 → 7 · ≤1.0 → 4 |
| `Above_200MA` | 8 |
| `VolumeDryingUp` | 6 |
| `RSI_14` | 30–50 → 8 (oversold bouncing) · 50–65 → 5 (healthy) |
| Near 50MA `Price_vs_50MA%` | −5..+5 → 8 · −15..−5 → 4 |
| `EarningsBeat` | 5 |
| ATR penalty | > 12% → **−8** · > 8% → **−3** |

Note this rewards *contraction*, not strength: the best swing card is a quality
name coiling on drying volume, not the one making the biggest move.

The separate 0–100 **`Swing_Score`** in the CSV uses different weights — setup
category 20, R:R to T2 20 (`RR_T2` ≥ 3), ATR shrinking 10, RSI 40–60 15,
`BB_PctB` 15, pullback volume 10, plus 5 each for above-200MA and `RS_Rank` ≥ 60
— and its `Swing_Pass` flag is a hard AND of five primary filters: setup is
Momentum-Pullback or VCP, `RR_T2` ≥ 3, ATR shrinking, RSI in 40–60, `BB_%B` < 0.4.
Unlike Long-Term, `Swing_Pass` is **not** required to render a Swing card.

#### Grade bands

`_score_to_grade()` in `reporting/dashboard.py` maps the badge number to a
letter. Because the scales differ per section, so do the cutoffs:

| Section | A+ | A | B+ | B | C |
|---------|----|---|----|---|---|
| Day Trade | 80 | 65 | 50 | 35 | 20 |
| Swing Trade | 85 | 70 | 55 | 40 | 20 |
| Long-Term | 95 | 85 | 75 | 65 | 40 |
| Calls | 18 | 14 | 10 | 6 | 1 |
| Puts | 8 | 6 | 4 | 2 | 1 |

Anything below the C cutoff grades D. Top-5 selection additionally requires
score > 20 for Day and Swing, and > 0 for Long-Term, Calls and Puts — so a
section renders fewer than five cards, or none, when the tape does not offer
them. That is the intended behaviour, not a bug.

#### What the regime does — and does not — change

`core/market_regime.py` classifies the day and sets per-horizon multipliers
(Bullish 1.0/1.0/1.0, Neutral day 0.5 / swing 0.75 / longterm 1.0, Defensive
0.25/0.5/0.5). These scale the **position size** on the R:R·SIZE line of each
card, never the score or the grade. Options sections ride the swing horizon.
When no regime data is available the source is `"none"` and multipliers stay at
1.0 — an unknown tape must not silently shrink your sizing.

### Market context — `scanners/market_movers.py`
Top-10 pre-market / live / after-hours movers with news-catalyst
classification (regex over Yahoo Finance headlines); VIX with interpretation
bands; the week's high/medium-impact US economic calendar (ForexFactory feed,
cached 1 h in memory + on disk at `data/econ_calendar_cache.json`, serving
the last good copy when the feed rate-limits); a Fed rate outlook computed
from fed funds futures (ZQ); and `market_pulse()` — the dashboard-header
snapshot of mega-cap concentration, SPY/QQQ strength, and upcoming econ
events.

---

## Reporting

| Module | Output |
|--------|--------|
| `reporting/dashboard.py` | Self-contained HTML dashboard: market-pulse header + top-5 cards per section (Day Trade, Swing, Long-Term, Calls, Puts) with R:R-gated trade plans and fixed-risk position sizing from `ACCOUNT_SIZE` / `RISK_PER_TRADE_PCT` / `MAX_POSITION_PCT`. |
| `reporting/research.py` | Per-ticker research pages (see Research page above). |
| `reporting/portfolio.py` | Portfolio & Watchlist panel: P&L + rule-based position alerts. |
| `reporting/csv_writer.py` | Timestamped, Excel-friendly (UTF-8 BOM) scan CSVs. |
| `reporting/signal_tracker.py` | Logs every A/B signal and later resolves it against realized bars → hit rate and expectancy by category and grade. Closes the feedback loop: a persistently negative-expectancy category is a fix-or-retire signal. |

---

## Backtesting — `backtest/`

Walk-forward replay of the live pipeline: for each trading day D, metrics are
recomputed point-in-time (`compute_daily_metrics` on bars sliced to D), the
**same production** `categorize()` + `enrich_row()` run, and each A/B/C signal
resolves through the same `resolve_long()` rules the live tracker uses.

Honesty conventions baked in: signals computed at D's close act at D+1 via
buy-stop triggers a later bar must actually touch (no instant fills);
same-bar stop+target ambiguity resolves to **stop**; one open signal per
(ticker, category) — no pyramiding.

- `data.py` — bulk daily-bar download with a per-ticker local cache (`data/cache/`)
- `resolve.py` — the single outcome-resolution implementation shared with the live tracker
- `engine.py` — the walk-forward loop
- `report.py` — hit rate/expectancy by category, grade, and regime; R:R-gate check; cumulative-R equity curve (inline SVG) with SPY buy-and-hold context

---

## Scheduler — `scheduling/scheduler.py`

All timed jobs in one process, with a VIX-adaptive put-scan frequency, a
market-health gate that suppresses day-trade alerts in bear tape, a grade
filter (only A/A+ signals email), and CLI flags (`--run-now`, `--force`,
`--universe`). Daily schedule (ET):

| Time | Job |
|------|-----|
| 06:30 | Earnings alerts scan (T-5 / T-1 / T-0 tiers) |
| 07:00 | Pre-Market Brief email |
| every 10 min | Watchlist alert + breaking-news monitor |
| 08:00 / 08:05 | Swing + calls pre-market scans |
| 09:30 / 10:00 / 11:35 | Day-trade scans |
| 11:30 | VIX check — adds extra put scans when elevated |
| 11:40 | Puts midday scan |
| 16:30 | Full close scan (whole universe) |
| 16:45 (Fri) | Weekly scan |
| 23:30 | Nightly output cleanup |

---

## Data files

| File | Contents |
|------|----------|
| `data/watchlists.json` | Named, user-curated ticker lists (usable as scan universes) |
| `data/portfolio.csv` | Equity positions + watch rows (`portfolio_template.csv` = starter) |
| `data/options_positions.csv` | Open option contracts (written by the broker sync) |
| `data/backups/` | Timestamped CSV backups taken before every broker sync |
| `data/alerts_state.json` / `alerts_log.json` | Active alert set / append-only history |
| `data/journal_trades.json` | Trade journal records |
| `data/premarket_brief.json` | Latest generated brief |
| `data/econ_calendar_cache.json` | Cached economic calendar (survives restarts) |
| `data/cache/` | Backtest daily-bar cache |
| `data/output/` | Scan CSVs, dashboards, research pages, signal logs (gitignored) |

---

## Broker sync — `core/broker_sync.py`

Pulls real holdings from Robinhood into `data/portfolio.csv` and
`data/options_positions.csv`. Driven by the **`get-portfolio` skill**, which
fetches through the Robinhood MCP tools and pipes the payloads into
`scripts/sync_broker_positions.py`. Read-only against the broker — this path
cannot place, modify or cancel an order.

```bash
python3 scripts/sync_broker_positions.py show        # current local state
python3 scripts/sync_broker_positions.py sync --dry-run \
    --equities @equities.json --options @options.json \
    --premiums '{"SPY260725C00601000": 1.23}'
```

**The merge is deliberately conservative**, because `portfolio.csv` is
hand-maintained state (strategies, stops, targets, notes, and the
`Target_Weight`/`Theme` columns behind the allocation plan) and a broker knows
none of it:

- writes **only** `Shares` and `Avg_Cost`; never touches Strategy, Stop,
  Target, Notes, Entry_Date or any hand-added column;
- **never deletes a row.** A holding the broker stops reporting is zeroed and
  marked `closed at broker`, keeping its notes as a watchlist row;
- **never touches rows it doesn't own.** Ownership is tracked in a `Source`
  column — without it the sync couldn't tell "sold it" from "it's on my
  watchlist and I never held it", and would zero out watchlist rows every run.

Bookkeeping columns (`Source`, `Last_Synced`, `Account`) ride in the `_extra`
dict rather than `POSITION_FIELDS`, so the webapp's Edit Position form —
which doesn't know about them — round-trips them instead of blanking them.

Every write is preceded by a timestamped backup in `data/backups/`. New rows
default to `Strategy=longterm` and are listed under `needs_strategy` in the
report, as is any watchlist row that just became a real holding — Strategy
selects which alerts fire on real money, so the choice gets reviewed rather
than silently inherited.

Options live in their own file because `portfolio.csv`'s contract is "one row
= one equity ticker": `build_portfolio_view()` joins to the day's scan by
ticker and values rows as `price × Shares`, which for an option means no scan
match, no ×100 multiplier and no expiry — a silently wrong number in
`portfolio_totals()`. See `reporting/options_positions.py`.

---

## Configuration (`.env`)

| Variable | Purpose |
|----------|---------|
| `RESEND_API_KEY` | Resend API key (`re_…`) — required for any email |
| `RESEND_FROM_EMAIL` / `ALERT_EMAIL_FROM` | From-address. Use `onboarding@resend.dev` unless you've verified your own domain in Resend. Set **both** (different modules read each). |
| `ALERT_EMAIL_TO` | Recipient. In Resend sandbox mode this must be your Resend account email. |
| `ACCOUNT_SIZE`, `RISK_PER_TRADE_PCT`, `MAX_POSITION_PCT` | Fixed-risk position sizing on dashboard cards |
| `ANTHROPIC_API_KEY` | Optional — enables the dashboard's AI morning-summary polish and the Journal's AI trade review; both degrade gracefully without it |

`.env` is gitignored — **never commit real keys**. (A Resend key was once
hardcoded in `scheduler.py` and had to be rotated; everything reads from the
environment now.)

---

## Project structure

```
StockAnalysis_Version1/
├── src/stockanalysis/
│   ├── core/          # pure scoring/classification logic (metrics, grades,
│   │                  #   conviction, key levels, regime, alerts, earnings,
│   │                  #   watchlist/news monitors, brief, journal)
│   ├── scanners/      # data fetching + orchestration (scan_universe,
│   │                  #   market_movers, ai_pulse)
│   ├── backtest/      # walk-forward backtesting (data, engine, resolve, report)
│   ├── reporting/     # dashboards, research pages, portfolio, CSVs, tracker
│   ├── scheduling/    # scheduler.py — all timed jobs
│   └── webapp/        # localhost UI (app, api, views, pages, jobstore)
├── scripts/           # send_test_alert.py — end-to-end email test
├── tests/             # unittest suite, fully offline (network mocked)
├── data/              # flat-file state + generated output
├── docs/              # day_trading_prompts.md
├── legacy/            # superseded scripts, reference only
└── .env.example       # copy to .env
```

## Tests

Every module with logic has an offline test file under `tests/` (19 files) —
alerts lifecycle, earnings tiers, watchlist conditions, news classification,
premarket brief, journal math, backtest point-in-time correctness, regime,
key levels, conviction, strategy scores, and more:

```bash
python -m unittest discover tests
```

## Gotchas & regression notes

Bug classes that have bitten before — each should keep a permanent regression
test:

1. **yfinance NaN propagation** — trailing NaN rows must be forward-filled
   before computing indicators, or indicators come back NaN.
2. **`categorize()` elif-order / disqualifier edge cases** — condition order
   matters (Momentum-Pullback vs VCP overlap); RVOL must not be an
   unconditional veto (holiday sessions); institutional-quality large caps
   were once misfiled as "Avoid".
3. **`^TNX` returns the yield directly in percent** — do not divide by 10.
4. **numpy/pandas scalar types break `json.dumps()`** — cast to native
   `float`/`int` before serializing anything derived from yfinance frames.
5. **Grading math** — ATR-based stop calc, EMA labeling, and inflated A+
   grades have each regressed once; `tests/` pins the fixes.
6. **Secrets** — API keys live in `.env` only, never in source.
