"""
app.py — localhost trading workstation web app
================================================
A small stdlib-only web app (no Flask/FastAPI/DB — see the note below on why)
serving the workstation's pages: Dashboard (home), AI Sentiment, Scanner,
Research, Portfolio, Journal, Alerts, Day Trade, Automation. HTTP plumbing
lives here; page HTML is built in views.py/pages.py, background jobs run
through jobstore.py, and job/search/watchlist logic lives in api.py.

Day Trade is the one section not backed by `stockanalysis.*`: it's the SPY
0DTE signal engine in the sibling `spydaytrader` package, wired in here as an
independent feature. It shares this server, this layout and the market-regime
scorer, and nothing else — its state lives under data/spy/ and its core logic
imports nothing from stockanalysis.core.

Run it:
    python src/stockanalysis/webapp/app.py            # http://localhost:8899
    python -m stockanalysis.webapp.app --port 9000

Why stdlib http.server instead of FastAPI+Redis+Postgres+WebSocket: this is a
single-user local tool run from the command line, not a hosted multi-user
service — there's no concurrent-write contention to arbitrate (a queue/DB
solves), and no client outside this machine to push updates to (a WebSocket
solves). Background jobs run as daemon threads in this one process; the UI
gets "live" progress via short-interval polling (see views.py's pollJobs()),
which is indistinguishable from push at this latency for a single browser
tab. If this ever needs multiple concurrent users or long-running jobs that
must survive a server restart, that's the point to revisit the stack — not
before, since a database and queue are new failure modes and operational
surface for a tool that until then only needs to talk to itself.

LOCAL tool: binds 127.0.0.1, no auth. Don't expose it beyond localhost.
"""

from __future__ import annotations

import argparse
import json
import os
import inspect
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):   # direct run: make `stockanalysis.*` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spydaytrader.webapp import pages as spy_pages
from stockanalysis.webapp import api, jobstore, pages
from stockanalysis.webapp.views import render_page, OUTPUT_DIR

DEFAULT_PORT = 8899

# path -> page-body function returning (html_body, extra_js)
ROUTES = {
    "/":            ("dashboard", "Dashboard", pages.dashboard_page),
    "/ai-sentiment":("ai-sentiment", "AI Sentiment", pages.ai_sentiment_page),
    "/scanner":     ("scanner",   "Scanner",   pages.scanner_page),
    "/screener":    ("screener",  "Screener",  pages.screener_page),
    "/research":    ("research",  "Research",  pages.research_page),
    "/portfolio":   ("portfolio", "Portfolio", pages.portfolio_page),
    "/journal":     ("journal",   "Journal",   pages.journal_page),
    "/alerts":      ("alerts",    "Alerts",    pages.alerts_page),
    "/daytrade":    ("daytrade",  "Day Trade", spy_pages.daytrade_page),
    "/daytrade/proposals": ("daytrade", "Day Trade · Proposals",
                            spy_pages.daytrade_proposals_page),
    # Its own route rather than a /daytrade sub-page: that section is the SPY
    # 0DTE options engine and this ranks equities across all three market-cap
    # profiles. Nesting them would imply a shared model they do not have.
    "/stockdaytrade": ("stockdaytrade", "StockDayTrade", pages.stockdaytrade_page),
    # Former path, kept so existing bookmarks and any saved links still land
    # on the page. It renders identically and lights up the same nav entry.
    "/smallcap":      ("stockdaytrade", "StockDayTrade", pages.stockdaytrade_page),
    "/longterm":    ("longterm",  "Long-Term Buy Engine", pages.longterm_page),
    # Its own route rather than a /longterm sub-page: it consumes that
    # engine's company verdict wholesale, but adds an options layer with
    # its own slow scan, its own snapshot and its own staleness rules.
    "/csp":         ("csp",       "Cash-Secured Puts", pages.csp_page),
    # Both directions on one page. Not folded into /longterm because that
    # engine answers "is this worth owning" and stops; this one treats its
    # rejections as input rather than as a verdict.
    "/shortside":   ("shortside", "Long / Short", pages.shortside_page),
    "/automation":  ("automation","Automation",pages.automation_page),
}


def _wants_query(fn) -> bool:
    """Whether a page function should be handed the parsed query string.

    Pages take no arguments by default. One whose state lives in the URL —
    filters, an overridden market regime — declares a single parameter and
    gets the parse_qs dict. Detected from the signature rather than listed in
    ROUTES so adding such a page means touching one file instead of two.
    """
    try:
        return bool(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return False


class WorkstationHandler(SimpleHTTPRequestHandler):
    """Known page paths render through views/pages; everything else falls
    through to static file serving out of data/output (dashboards, research
    pages, scan CSVs, snapshot.json)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path in ROUTES:
            nav_key, title, page_fn = ROUTES[path]
            try:
                body, extra_js = (page_fn(query) if _wants_query(page_fn)
                                  else page_fn())
            except Exception as e:
                import traceback
                traceback.print_exc()
                body, extra_js = (f'<div style="background:#FCEBEB;color:#791F1F;'
                                  f'padding:16px;border-radius:12px">Page failed to '
                                  f'render: {e}</div>', "")
            # nav_key, not the path: sub-pages like /daytrade/proposals must
            # still light up their parent's sidebar entry.
            self._send_html(render_page(nav_key, title, body, extra_js))
            return

        if path == "/api/jobs":
            self._send_json(jobstore.current())
            return

        if path == "/api/search":
            q = (query.get("q") or [""])[0]
            self._send_json(api.search_tickers(q))
            return

        if path == "/api/analysis":
            # HTML, not JSON — same reasoning as /api/regime below: the
            # Dashboard panel shows the Long-Term engine's own cells and
            # reasoning grid, and a JSON contract here would mean a second
            # copy of fifteen cell renderers in JavaScript.
            from stockanalysis.webapp import longterm_view
            scope = (query.get("scope") or ["all"])[0]
            value = (query.get("value") or [""])[0]
            try:
                panel = longterm_view.analysis_panel(api.analysis(scope, value))
            except Exception as e:
                import traceback
                traceback.print_exc()
                panel = longterm_view.analysis_panel(
                    {"error": f"analysis failed: {e}"})
            self._send_html(panel.encode())
            return

        if path == "/api/screener/meta":
            self._send_json(api.screener_meta())
            return

        if path == "/api/screener/ticker":
            q = (query.get("q") or [""])[0]
            self._send_json(api.screener_ticker(q))
            return

        if path == "/api/screener/suggest":
            q = (query.get("q") or [""])[0]
            self._send_json(api.screener_suggest(q))
            return

        super().do_GET()

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        # rfile can only be drained once, and the Day Trade endpoints post JSON
        # while everything else posts a form — so keep the raw bytes too.
        raw = self.rfile.read(length) if length else b""
        form = parse_qs(raw.decode())

        if self.path == "/api/spy/scan":
            from spydaytrader.daemon import scheduler as spy_scheduler
            try:
                self._send_json(spy_scheduler.job_scan_spy(force=True))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({"error": f"scan failed: {e}"})
            return

        if self.path == "/api/spy/proposals/decide":
            from spydaytrader.core import trade_proposals as spy_proposals
            try:
                payload = json.loads(raw)
                proposal_id, status = payload["id"], payload["status"]
            except (ValueError, KeyError, TypeError):
                self._send_json({"error": "expected JSON {id, status}"})
                return
            if status not in ("approved", "rejected"):
                self._send_json({"error": "status must be 'approved' or 'rejected'"})
                return
            updated = spy_proposals.set_status(proposal_id, status)
            self._send_json(updated or {"error": f"no proposal {proposal_id}"})
            return

        if self.path == "/api/regime":
            # Runs the shared market-regime scorer (~15s) and returns rendered
            # HTML rather than JSON — the report is presentation, not an API
            # contract. Kept out of jobstore because it's a short synchronous
            # read the caller waits on, not a long background scan.
            from stockanalysis.core import regime_client
            # _send_html takes bytes here (render_page already encodes).
            self._send_html(pages.render_regime(regime_client.run_regime()).encode())
            return

        if self.path == "/run":
            action = (form.get("action") or [""])[0]
            err = api.dispatch_run(action, form)
            self._send_json({"ok": not err, "message": err or "Started"})
            return

        # The screener posts JSON, not a form: a condition tree is nested,
        # and urlencoded form fields can't express that without inventing a
        # flattening scheme on both sides.
        if self.path in ("/api/screen", "/api/screener/save",
                         "/api/screener/delete"):
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                self._send_json({"ok": False, "message": "expected JSON body"})
                return
            try:
                if self.path == "/api/screen":
                    self._send_json(api.screen(payload))
                elif self.path == "/api/screener/save":
                    self._send_json(api.save_screen(payload))
                else:
                    self._send_json(api.delete_screen(
                        str(payload.get("name") or "")))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({"ok": False, "message": f"screen failed: {e}"})
            return

        if self.path == "/api/watchlist/toggle":
            name = (form.get("name") or ["Starred"])[0]
            ticker = (form.get("ticker") or [""])[0]
            if not ticker:
                self._send_json({"ok": False, "message": "no ticker given"})
                return
            watchlists = api.watchlist_toggle(name, ticker)
            self._send_json({"ok": True, "watchlists": watchlists})
            return

        if self.path == "/api/etf/portfolio":
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                self._send_json({"ok": False, "message": "expected JSON body"})
                return
            try:
                self._send_json(api.etf_portfolio(payload))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({"ok": False, "message": f"analysis failed: {e}"})
            return

        if self.path == "/api/etf/theme":
            self._send_json(api.etf_set_theme(form))
            return

        if self.path == "/api/risk/save":
            self._send_json(api.save_risk_settings(form))
            return

        if self.path == "/api/schedule/save":
            self._send_json(api.schedule_save(form))
            return

        if self.path == "/api/portfolio/save":
            self._send_json(api.portfolio_save(form))
            return

        if self.path == "/api/portfolio/delete":
            ticker = (form.get("ticker") or [""])[0]
            self._send_json(api.portfolio_delete(ticker))
            return

        if self.path == "/api/journal/save":
            self._send_json(api.journal_save(form))
            return

        if self.path == "/api/journal/delete":
            trade_id = (form.get("trade_id") or [""])[0]
            self._send_json(api.journal_delete(trade_id))
            return

        self.send_error(404)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):   # quieter default access logging
        pass


def _start_scheduler_thread() -> None:
    """Run the scheduling loop (pre-market/intraday/close scans, emails,
    nightly cleanup) on a daemon thread inside this process, so starting the
    web UI is enough to have jobs firing on schedule — no second terminal
    running scheduler.py needed."""
    from stockanalysis.scheduling.scheduler import _start_scheduler

    def _runner():
        try:
            _start_scheduler()
        except Exception:
            import traceback
            traceback.print_exc()

    threading.Thread(target=_runner, daemon=True, name="scheduler-loop").start()


def _start_spy_daemon_thread() -> None:
    """Run the SPY 0DTE signal daemon on its own daemon thread, same deal as
    the scan scheduler above: starting the web UI is enough to have Day Trade
    signals firing. It polls yfinance every 30s and only acts during market
    hours; it can never place an order, only write a pending_review proposal."""
    from spydaytrader.daemon.scheduler import run_forever

    def _runner():
        try:
            run_forever()
        except Exception:
            import traceback
            traceback.print_exc()

    threading.Thread(target=_runner, daemon=True, name="spy-signal-daemon").start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading workstation web app")
    # PORT lets a supervisor (the preview harness, a container) assign a free
    # port without editing the launch config. Explicit --port still wins, so
    # `python app.py` on its own is unchanged: 8899.
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT") or DEFAULT_PORT))
    parser.add_argument("--no-scheduler", action="store_true",
                        help="Don't run the automatic scan scheduler alongside the UI")
    parser.add_argument("--no-spy-daemon", action="store_true",
                        help="Don't run the SPY day-trade signal daemon alongside the UI")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_scheduler:
        _start_scheduler_thread()
        print("Scheduler loop → running in background (pass --no-scheduler to disable)")

    if not args.no_spy_daemon:
        _start_spy_daemon_thread()
        print("SPY signal daemon → running in background (pass --no-spy-daemon to disable)")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), WorkstationHandler)
    print(f"Trading Workstation → http://localhost:{args.port}  "
          f"(serving {OUTPUT_DIR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
