"""
api.py
======
Job functions and JSON-endpoint logic for the webapp. Kept separate from
app.py (HTTP plumbing) and views.py (HTML rendering) so each file has one
job: this one talks to the scan/research/portfolio pipeline and to
jobstore.Progress; it never touches HTTP request/response objects directly.
"""

from __future__ import annotations

from pathlib import Path

from . import jobstore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR   = PROJECT_ROOT / "data" / "output"

BUILTIN_UNIVERSES = ("daytrade", "watchlist", "longterm", "dividend", "sp500")


def available_universes() -> list[str]:
    """Built-in universes plus every user-curated watchlist (data/watchlists.json)
    — lets the Scanner run against e.g. "AI: Networking" the same way it runs
    against "sp500", without hardcoding each watchlist name into this module."""
    from stockanalysis.reporting.research import load_watchlists
    return list(BUILTIN_UNIVERSES) + sorted(
        name for name in load_watchlists() if name not in BUILTIN_UNIVERSES)

# stage-string prefix -> pipeline step index, shared with the Scanner page's
# step visualization (views.py renders the same list)
SCAN_STEPS = ("fetch_qqq", "scan", "grade", "writing", "research", "done")


def scan_stage_index(stage: str) -> int:
    """Map a raw stage string (e.g. 'scan:NVDA') to an index into SCAN_STEPS."""
    prefix = stage.split(":", 1)[0]
    return SCAN_STEPS.index(prefix) if prefix in SCAN_STEPS else 0


# ─────────────────────────────────────────────────────────────────────────────
# JOB FUNCTIONS — each takes a jobstore.Progress and returns a result string
# ─────────────────────────────────────────────────────────────────────────────

def job_research(tickers: list[str], progress: jobstore.Progress) -> str:
    from stockanalysis.reporting.research import refresh_research
    written = refresh_research(
        tickers, OUTPUT_DIR, charts=True,
        progress_cb=lambda stage, done, total: progress.stage(stage, done, total))
    progress.stage("done", len(tickers), len(tickers))
    return f"{len(written)} page(s) refreshed: {', '.join(sorted(written))}"


def job_scan(universes: list[str], include_portfolio: bool,
            progress: jobstore.Progress) -> str:
    from stockanalysis.scanners import scan_universe as su
    from stockanalysis.reporting.dashboard import generate_dashboard
    from stockanalysis.reporting.research import load_watchlists
    builtin = {
        "daytrade": su.DAY_TRADE_TICKERS, "watchlist": su.WATCHLIST_TICKERS,
        "longterm": su.LONGTERM_TICKERS, "dividend": su.DIVIDEND_STOCKS,
        "sp500": su.SP500_TICKERS,
    }
    user_watchlists = load_watchlists()
    # Union across every selected universe (order-preserving, deduped) so
    # picking several overlapping categories scans each ticker once.
    tickers, seen = [], set()
    for universe in universes:
        for t in builtin.get(universe) or user_watchlists.get(universe) or []:
            if t not in seen:
                seen.add(t)
                tickers.append(t)
    rows = su.main(
        tickers,
        progress_cb=lambda stage, done, total: progress.stage(stage, done, total))
    progress.stage("research", len(rows), len(rows))
    name_tag = "-".join(universes[:3]) + (f"+{len(universes) - 3}" if len(universes) > 3 else "")
    generate_dashboard(rows, output_dir=OUTPUT_DIR, open_browser=False,
                       include_portfolio=include_portfolio,
                       report_name=f"{name_tag}Report")
    progress.stage("done", len(rows), len(rows))
    return (f"scanned {len(rows)} tickers ({', '.join(universes)}); dashboard regenerated"
            + ("" if include_portfolio else " (portfolio panel excluded)"))


def job_news(tickers: list[str] | None, progress: jobstore.Progress) -> str:
    from stockanalysis.reporting.research import update_news
    progress.stage("fetching news", 0, len(tickers) if tickers else 0)
    updated = update_news(tickers, OUTPUT_DIR)
    progress.stage("done", len(updated), len(updated))
    return f"latest news spliced into {len(updated)} research page(s)"


def job_ai_sentiment(progress: jobstore.Progress) -> str:
    import json
    from stockanalysis.scanners import ai_pulse
    from stockanalysis.scanners.market_movers import market_pulse
    from stockanalysis.core import ai_sentiment as aisent

    progress.stage("fetching AI tiers + macro inputs")
    pulse_extra = ai_pulse.fetch_ai_pulse()
    progress.stage("fetching market pulse (VIX, sectors, econ)")
    pulse = market_pulse()
    progress.stage("scoring")
    snapshot = aisent.build_snapshot(pulse_extra, pulse)
    (OUTPUT_DIR / "ai_sentiment.json").write_text(json.dumps(snapshot))
    progress.stage("done")
    s = snapshot["sentiment"]
    return f"AI sentiment {s['score']}/100 — {s['label']}"


def job_earnings_analysis(ticker: str, progress: jobstore.Progress) -> str:
    """Run the deterministic earnings-sentiment engine for one ticker and
    write the result to data/output/earnings/<TICKER>.json — served as a
    static file by app.py's fallback handler, so the Research Library's
    "Earnings Analysis" button just fetches it once this job's status flips
    to done instead of needing a dedicated GET route."""
    import json
    from stockanalysis.core.earnings_sentiment import analyze_earnings_sentiment
    ticker = ticker.upper().strip()
    progress.stage(f"analyzing {ticker}: earnings history, options, market context")
    result = analyze_earnings_sentiment(ticker)
    earnings_dir = OUTPUT_DIR / "earnings"
    earnings_dir.mkdir(parents=True, exist_ok=True)
    (earnings_dir / f"{ticker}.json").write_text(json.dumps(result))
    progress.stage("done")
    move = result.get("expected_move_pct")
    return (f"{ticker}: {result['trading_bias']} · bullish {result['bullish_probability']}%"
            + (f" · expected move ±{move:.1f}%" if move is not None else ""))


def job_cleanup(days: int, progress: jobstore.Progress) -> str:
    from stockanalysis.scheduling.scheduler import cleanup_outputs
    progress.stage("scanning output directory")
    n = cleanup_outputs(days, OUTPUT_DIR)
    progress.stage("done")
    return f"removed {n} file(s) older than {days}d"


def job_run_tests(progress: jobstore.Progress) -> str:
    """Run the pytest suite (tests/) as a subprocess and record the result.
    Full output is written to data/output/last_test_run.txt so a failure can
    be inspected from the dashboard without a terminal."""
    import os
    import subprocess
    import sys

    progress.stage("running pytest")
    tests_dir = PROJECT_ROOT / "tests"
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(tests_dir)],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            timeout=600, env=env,
        )
        output = proc.stdout + proc.stderr
        passed = proc.returncode == 0
    except FileNotFoundError:
        output = "pytest is not installed — run: pip3 install pytest"
        passed = False
    except subprocess.TimeoutExpired:
        output = "test run timed out after 10 minutes"
        passed = False

    (OUTPUT_DIR / "last_test_run.txt").write_text(output)
    summary = next((ln for ln in reversed(output.strip().splitlines())
                    if ln.strip()), "no output")
    progress.stage("done")
    return f"{'PASSED' if passed else 'FAILED'}: {summary}"


def job_trigger_cron(job_name: str, progress: jobstore.Progress) -> str:
    """Run one already-registered `schedule` job's function immediately,
    out of band — for verifying a cron job actually does what it's supposed
    to without waiting for its real trigger time. Calls the job's function
    directly rather than schedule.Job.run(), so it does NOT advance that
    job's next_run — the real schedule is untouched."""
    import schedule

    match = next((j for j in schedule.jobs if jobstore.job_name(j) == job_name), None)
    if match is None:
        raise ValueError(f"no scheduled job named {job_name!r} "
                          f"(is the scheduler running? see the Scheduler card)")

    progress.stage(f"running {job_name}")
    match.job_func()
    progress.stage("done")
    return f"{job_name} executed on demand (its normal schedule is unaffected)"


def job_test_scheduler(progress: jobstore.Progress) -> str:
    """Exercise the scheduler end-to-end: registers a one-off job ~1 minute
    from now (via scheduler._start_scheduler_test) and blocks until it fires,
    so you can confirm cron wiring works without waiting for a real market
    session. Runs on a jobstore background thread so it doesn't block the UI."""
    from stockanalysis.scheduling.scheduler import _start_scheduler_test
    progress.stage("scheduling test job (fires in ~1 min)")
    _start_scheduler_test()
    progress.stage("done")
    return "self-test complete — check the app's console output for the fired job's log lines"


def dispatch_run(action: str, form: dict) -> str:
    """
    form: dict of lists (as parse_qs returns). Starts the matching job via
    jobstore.start(). Returns "" on success or an error string — never
    raises (bad input just becomes an error string shown to the user).
    """
    def first(key, default=""):
        return (form.get(key) or [default])[0]

    def watchlist_tickers(names: list[str]) -> list[str] | None:
        """Union of tickers across one or more data/watchlists.json
        categories (order-preserving, deduped), or None if `names` is empty
        — lets callers fall back to their own default."""
        if not names:
            return None
        from stockanalysis.reporting.research import load_watchlists
        lists = load_watchlists()
        tickers, seen = [], set()
        for name in names:
            for t in lists.get(name) or []:
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)
        return tickers

    if action == "research":
        watchlists = form.get("watchlist") or []
        tickers = watchlist_tickers(watchlists)
        if tickers is None:
            raw = first("tickers")
            tickers = [t.strip().upper() for t in raw.replace(",", " ").split()
                       if t.strip()]
            if not tickers:
                from stockanalysis.scheduling.scheduler import DAY_TRADE_TICKERS
                tickers = list(DAY_TRADE_TICKERS)
        elif not tickers:
            return f"watchlist(s) {', '.join(watchlists)!r} empty or unknown"
        label = (f"research refresh: {'+'.join(watchlists)}" if watchlists else
                 "research refresh: " + ", ".join(tickers[:12])
                 + ("…" if len(tickers) > 12 else ""))
        return jobstore.start("research", label,
                              lambda p: job_research(tickers, p))

    if action == "scan":
        universes = form.get("universe") or ["daytrade"]
        unknown = [u for u in universes if u not in available_universes()]
        if unknown:
            return f"unknown universe(s): {', '.join(unknown)}"
        include_pf = "portfolio" in form
        label = f"scan: {'+'.join(universes)}" + ("" if include_pf else " (no portfolio panel)")
        return jobstore.start("scan", label,
                              lambda p: job_scan(universes, include_pf, p))

    if action == "news":
        watchlists = form.get("watchlist") or []
        tickers = watchlist_tickers(watchlists)
        if tickers is None:
            raw = first("tickers")
            tickers = [t.strip().upper() for t in raw.replace(",", " ").split()
                       if t.strip()] or None
        elif not tickers:
            return f"watchlist(s) {', '.join(watchlists)!r} empty or unknown"
        label = (f"news scan: {'+'.join(watchlists)}" if watchlists else
                 "news scan: all research pages" if tickers is None
                 else f"news scan: {', '.join(tickers[:12])}"
                 + ("…" if len(tickers) > 12 else ""))
        return jobstore.start("news", label, lambda p: job_news(tickers, p))

    if action == "ai_sentiment":
        return jobstore.start("ai_sentiment", "AI sentiment refresh",
                              lambda p: job_ai_sentiment(p))

    if action == "earnings_analysis":
        ticker = first("ticker").strip().upper()
        if not ticker:
            return "no ticker given"
        return jobstore.start("earnings", f"earnings analysis: {ticker}",
                              lambda p: job_earnings_analysis(ticker, p))

    if action == "cleanup":
        try:
            days = max(0, int(first("days", "7")))
        except ValueError:
            days = 7
        return jobstore.start("cleanup", f"cleanup >{days}d",
                              lambda p: job_cleanup(days, p))

    if action == "test":
        return jobstore.start("test", "unit tests: tests/",
                              lambda p: job_run_tests(p))

    if action == "run_cron":
        name = first("job_name")
        if not name:
            return "no job_name given"
        return jobstore.start(f"cron:{name}", f"manual trigger: {name}",
                              lambda p: job_trigger_cron(name, p))

    if action == "test_scheduler":
        return jobstore.start("scheduler_test", "scheduler self-test (fires in ~1 min)",
                              lambda p: job_test_scheduler(p))

    return "unknown action"


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH — ticker autocomplete over the research index + watchlists + portfolio
# ─────────────────────────────────────────────────────────────────────────────

def search_tickers(query: str, limit: int = 10) -> list[dict]:
    from stockanalysis.reporting.research import load_research_index
    q = query.strip().upper()
    index = load_research_index(OUTPUT_DIR)
    if not q:
        items = sorted(index.values(), key=lambda r: r.get("ticker") or "")
        return items[:limit]
    starts = [r for t, r in index.items() if t.startswith(q)]
    contains = [r for t, r in index.items() if q in t and not t.startswith(q)]
    sector_hits = [r for r in index.values()
                   if q in str(r.get("sector") or "").upper()
                   and r not in starts and r not in contains]
    return (starts + contains + sector_hits)[:limit]


def watchlist_toggle(name: str, ticker: str) -> dict:
    from stockanalysis.reporting.research import toggle_watchlist
    return toggle_watchlist(name, ticker)


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO — add/edit/delete rows in data/portfolio.csv from the Portfolio page
# ─────────────────────────────────────────────────────────────────────────────

def portfolio_save(form: dict) -> dict:
    """form: dict of lists (as parse_qs returns), from the Add/Edit Position
    modal. Returns {"ok": True, "message": ...} or {"ok": False, "message":
    ...} — never raises (a blank ticker just becomes an error string)."""
    from stockanalysis.reporting.portfolio import upsert_position

    def first(key, default=""):
        return (form.get(key) or [default])[0]

    fields = {k: first(k) for k in
             ("Ticker", "Shares", "Avg_Cost", "Entry_Date", "Strategy", "Stop", "Target", "Notes")}
    try:
        upsert_position(fields, original_ticker=first("Original_Ticker"))
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": f"{fields['Ticker'].strip().upper()} saved"}


def portfolio_delete(ticker: str) -> dict:
    from stockanalysis.reporting.portfolio import delete_position
    ticker = (ticker or "").strip()
    if not ticker:
        return {"ok": False, "message": "no ticker given"}
    delete_position(ticker)
    return {"ok": True, "message": f"{ticker.upper()} removed"}
