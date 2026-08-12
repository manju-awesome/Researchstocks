"""
Snapshot storage for the CSP engine.

The page renders a stored run rather than scanning on request, for the
same reason StockDayTrade does: a scan fetches an option chain per expiry
per surviving ticker, which is minutes of network, far past any request
timeout.

Option prices go stale much faster than the long-term verdicts they sit
on. A quality score from this morning is still true this afternoon; a
$1.20 bid is not. So the snapshot records `generated_at` AND whether the
market was open when it was taken, and the page leads with both — a
premium quoted from a closed market is a last-trade artifact, not a price
anyone will fill.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

_DIR = Path(__file__).resolve().parents[4] / "data" / "csp"
_SNAPSHOT = _DIR / "csp_snapshot.json"

# US market hours in Eastern. Approximate by design — this drives a
# freshness warning, not an order.
_OPEN, _CLOSE = (9, 30), (16, 0)


def _json_safe(obj):
    """numpy/pandas scalars break json.dumps(); floats and ints do not.

    This has bitten this project repeatedly, and an option chain is full
    of numpy float64 straight out of a DataFrame, so the conversion is
    done once here on the way to disk.
    """
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (bool, str)) or obj is None:
        return obj
    if hasattr(obj, "item"):                       # numpy scalar
        try:
            return _json_safe(obj.item())
        except (ValueError, AttributeError):
            return str(obj)
    if isinstance(obj, (int, float)):
        return None if obj != obj else obj         # NaN
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    return str(obj)


def market_open(now=None) -> bool:
    """Whether US equities are open. Weekends and hours only — holidays
    are not modelled, so this can read True on Thanksgiving. It gates a
    warning banner, and the banner is the conservative direction."""
    try:
        from zoneinfo import ZoneInfo
        now = now or _dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = now or _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return _OPEN <= hm < _CLOSE


# A rejected company needs only enough to appear in the rejected list
# with the rule that fired. Storing its full audit made the snapshot an
# order of magnitude larger for rows the page renders as one word.
_REJECT_KEEP = ("ticker", "name", "sector", "price", "final",
                "no_trade_reason", "lt_action")


def save(rows, meta) -> Path:
    """Write the run.

    Two prunings, both about size rather than secrecy:

    `_lt` is the whole long-term result each row was derived from. It is
    already on /longterm, the page never reads it back, and keeping it
    tripled the file.

    Rejected rows are reduced to `_REJECT_KEEP`. On a typical run they
    are ninety-odd percent of the universe, and the page renders each as
    a ticker in a grouped list — so the full audit was a megabyte of
    data nothing displayed.
    """
    slim = []
    for r in rows:
        if (r.get("final") or {}).get("key") == "REJECT":
            slim.append({k: r.get(k) for k in _REJECT_KEEP})
        else:
            slim.append({k: v for k, v in r.items() if k != "_lt"})

    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "market_open": market_open(),
        **(meta or {}),
        "rows": slim,
    }
    _DIR.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(json.dumps(_json_safe(payload), indent=1))
    return _SNAPSHOT


def load() -> dict | None:
    try:
        return json.loads(_SNAPSHOT.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    except OSError as e:
        print(f"[CSP] snapshot unreadable ({e})")
        return None


def age_note(snapshot) -> tuple[str, str]:
    """(text, status) describing how much to trust the prices.

    Option quotes decay far faster than the equity verdicts under them,
    so this is deliberately blunt about it.
    """
    if not snapshot:
        return "no scan yet", "muted"
    try:
        ts = _dt.datetime.fromisoformat(snapshot["generated_at"])
    except (KeyError, ValueError):
        return "unknown age", "muted"

    mins = (_dt.datetime.now() - ts).total_seconds() / 60.0
    stamp = ts.strftime("%d %b %H:%M")

    if not snapshot.get("market_open"):
        return (f"{stamp} — market was CLOSED; quotes are last-trade "
                f"artifacts, not fillable prices"), "bad"
    if mins < 20:
        return f"{stamp} — {mins:.0f} min old", "good"
    if mins < 90:
        return f"{stamp} — {mins:.0f} min old, re-scan before ordering", "watch"
    hrs = mins / 60.0
    return (f"{stamp} — {hrs:.1f}h old; option quotes this stale are not "
            f"tradable, re-scan"), "bad"
