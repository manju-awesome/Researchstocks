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

UNIVERSES = ("daytrade", "watchlist", "longterm", "dividend", "sp500")

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


def job_scan(universe: str, include_portfolio: bool,
            progress: jobstore.Progress) -> str:
    from stockanalysis.scanners import scan_universe as su
    from stockanalysis.reporting.dashboard import generate_dashboard
    tickers = {
        "daytrade": su.DAY_TRADE_TICKERS, "watchlist": su.WATCHLIST_TICKERS,
        "longterm": su.LONGTERM_TICKERS, "dividend": su.DIVIDEND_STOCKS,
        "sp500": su.SP500_TICKERS,
    }[universe]
    rows = su.main(
        list(tickers),
        progress_cb=lambda stage, done, total: progress.stage(stage, done, total))
    progress.stage("research", len(rows), len(rows))
    generate_dashboard(rows, output_dir=OUTPUT_DIR, open_browser=False,
                       include_portfolio=include_portfolio,
                       report_name=f"{universe}Report")
    progress.stage("done", len(rows), len(rows))
    return (f"scanned {len(rows)} tickers ({universe}); dashboard regenerated"
            + ("" if include_portfolio else " (portfolio panel excluded)"))


def job_news(tickers: list[str] | None, progress: jobstore.Progress) -> str:
    from stockanalysis.reporting.research import update_news
    progress.stage("fetching news", 0, len(tickers) if tickers else 0)
    updated = update_news(tickers, OUTPUT_DIR)
    progress.stage("done", len(updated), len(updated))
    return f"latest news spliced into {len(updated)} research page(s)"


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


def dispatch_run(action: str, form: dict) -> str:
    """
    form: dict of lists (as parse_qs returns). Starts the matching job via
    jobstore.start(). Returns "" on success or an error string — never
    raises (bad input just becomes an error string shown to the user).
    """
    def first(key, default=""):
        return (form.get(key) or [default])[0]

    if action == "research":
        raw = first("tickers")
        tickers = [t.strip().upper() for t in raw.replace(",", " ").split()
                   if t.strip()]
        if not tickers:
            from stockanalysis.scheduling.scheduler import DAY_TRADE_TICKERS
            tickers = list(DAY_TRADE_TICKERS)
        label = ("research refresh: " + ", ".join(tickers[:12])
                 + ("…" if len(tickers) > 12 else ""))
        return jobstore.start("research", label,
                              lambda p: job_research(tickers, p))

    if action == "scan":
        universe = first("universe", "daytrade")
        if universe not in UNIVERSES:
            return "unknown universe"
        include_pf = "portfolio" in form
        label = f"scan: {universe}" + ("" if include_pf else " (no portfolio panel)")
        return jobstore.start("scan", label,
                              lambda p: job_scan(universe, include_pf, p))

    if action == "news":
        raw = first("tickers")
        tickers = [t.strip().upper() for t in raw.replace(",", " ").split()
                   if t.strip()] or None
        label = ("news scan: all research pages" if tickers is None
                 else f"news scan: {', '.join(tickers[:12])}"
                 + ("…" if len(tickers) > 12 else ""))
        return jobstore.start("news", label, lambda p: job_news(tickers, p))

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
