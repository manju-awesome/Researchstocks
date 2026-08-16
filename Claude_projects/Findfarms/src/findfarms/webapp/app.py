"""
app.py — Mysuru Retirement Farm Finder, local web app
=====================================================
Stdlib-only web app (no Flask, no database), matching the pattern used by the
trading workstation in this repo: single user, single machine, state in flat
JSON under data/, HTTP plumbing here and page HTML in pages.py/views.py.

Why no framework and no database: this is a personal research tool with one
user and a few hundred records. There is no concurrent-write contention to
arbitrate and no client outside this machine to push to — a database and a
queue would be new failure modes and new operational surface for a tool that
until then only needs to talk to itself. If it ever needs multiple users or
jobs that must survive a restart, that is the point to revisit the stack.

Run it:
    python src/findfarms/webapp/app.py            # http://localhost:8877
    python -m findfarms.webapp.app --port 9000

LOCAL tool: binds 127.0.0.1 only, no auth. Do not expose it beyond localhost.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from findfarms.core import pipeline
from findfarms.discovery import ingest as ingest_mod
from findfarms.store import db
from findfarms.webapp import pages
from findfarms.webapp.views import render_page

DEFAULT_PORT = 8877

ROUTES = {
    "/":            ("dashboard", "Dashboard", pages.dashboard_page),
    "/properties":  ("properties", "All Properties", pages.properties_page),
    "/property":    ("properties", "Property", pages.property_page),
    "/discover":    ("discover", "Discover", pages.discover_page),
    "/add":         ("add", "Add Listing", pages.add_page),
    "/price-drops": ("drops", "Price Drops", pages.price_drops_page),
    "/workflow":    ("workflow", "Workflow", pages.workflow_page),
    "/about":       ("about", "How this works", pages.about_page),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "FindfarmsLocal/1.0"

    def log_message(self, fmt, *args):
        # Quieter than the default: one line per request, no client address
        # noise, so an ingest run's own output stays readable.
        sys.stderr.write(f"  {self.command} {self.path.split('?')[0]}\n")

    # -- helpers ----------------------------------------------------------
    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html"):
        self.send_response(status)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        self._send(json.dumps(payload, default=str).encode("utf-8"),
                   status, "application/json")

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return {}

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path, params = parsed.path, parse_qs(parsed.query)

        if path == "/api/properties":
            return self._json(db.load_properties())
        if path == "/api/price-drops":
            return self._json(pipeline.price_drops())
        if path == "/api/alerts":
            return self._json(pipeline.check_alerts(fire=False))
        if path == "/favicon.ico":
            return self._send(b"", 204, "image/x-icon")

        route = ROUTES.get(path)
        if not route:
            return self._send(
                render_page("dashboard", "Not found",
                            '<h1>Not found</h1><p class="sub">'
                            '<a href="/">Back to the dashboard</a></p>'
                            ).encode("utf-8"), 404)

        active, title, fn = route
        try:
            body, js = fn(params)
        except Exception as e:
            import traceback
            traceback.print_exc()
            body = (f'<h1>Something broke</h1><p class="sub">{type(e).__name__}: '
                    f'{e}</p><pre style="font-size:11px;overflow-x:auto;'
                    f'background:#f4f2ec;padding:12px;border-radius:7px">'
                    f'{traceback.format_exc()}</pre>')
            js = ""
        return self._send(render_page(active, title, body, js).encode("utf-8"))

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        data = self._body()
        try:
            if path == "/api/ingest":
                text = (data.get("text") or "").strip()
                source = data.get("source") or "manual"
                if data.get("batch"):
                    results = ingest_mod.ingest_batch(text, source=source)
                    return self._json({"ok": True, "results": results})
                r = ingest_mod.ingest_text(text, source=source,
                                           source_url=data.get("url") or "")
                if r.get("ok"):
                    # Comparables shift when a property is added, so every
                    # other property's price position is now stale.
                    pipeline.rescore_all()
                return self._json(r)

            if path == "/api/fetch":
                r = ingest_mod.ingest_url((data.get("url") or "").strip())
                if r.get("ok"):
                    pipeline.rescore_all()
                return self._json(r)

            if path == "/api/note":
                ok = db.add_note(data.get("id", ""), data.get("text", ""))
                return self._json({"ok": ok})

            if path == "/api/status":
                ok = db.set_status(data.get("id", ""), data.get("status", ""),
                                   data.get("note", ""))
                return self._json({"ok": ok})

            if path == "/api/verify":
                ok = db.record_verification(
                    data.get("id", ""), data.get("field", ""), data.get("value"),
                    data.get("source", ""), data.get("confidence", "VERIFIED"),
                    data.get("note", ""))
                if ok:
                    pipeline.rescore_property(data.get("id", ""))
                return self._json({"ok": ok})

            if path == "/api/rescore":
                return self._json({"ok": True, "count": pipeline.rescore_all()})

            return self._json({"ok": False, "error": "Unknown endpoint"}, 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser(description="Mysuru Retirement Farm Finder")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    n = len(db.load_properties())
    print(f"\n  🌾 Mysuru Farm Finder — http://localhost:{args.port}")
    print(f"     {n} propert{'y' if n == 1 else 'ies'} tracked · "
          f"data in {db.DATA_DIR}")
    print(f"     Local only (127.0.0.1), no auth. Ctrl-C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")


if __name__ == "__main__":
    main()
