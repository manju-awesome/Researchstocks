"""
robots.py
=========
The compliance gate. **No HTTP request leaves this system without passing
through `may_fetch`**, and `may_fetch` fails closed.

The brief lists a set of things not to do — no bypassing logins, CAPTCHAs,
paywalls, robots.txt, private accounts, platform access controls or rate
limits. Written as a rule in a document, that decays: six months from now
someone adds a fetch in a hurry and the rule is not in the code path. So it
is implemented as a chokepoint instead. `fetch()` is the only way to make a
request, and it calls `may_fetch` first.

Fail closed
-----------
If robots.txt cannot be read — network error, timeout, a 500 from the server
— the answer is NO. The permissive reading ("robots.txt is unavailable, so
nothing is disallowed") is the convenient one and the wrong one: an
unreachable robots.txt means we do not know what is permitted, and acting
without knowing is the thing being avoided. The only exception is an explicit
404, which under the standard means no restrictions were published.

What this module cannot decide
------------------------------
robots.txt is a crawling directive, not a licence. A page can be
robots-allowed and still be off-limits under a site's terms of service, and
several major property portals prohibit automated collection in their terms
regardless of what robots.txt says. This module cannot read terms of service,
so each source in `sources.py` carries a hand-set access policy, and the
scraper only ever runs against sources marked as permitting it. robots.txt is
the floor, not the ceiling.

Rate limiting is enforced here too, per host, because "do not bypass rate
limits" also means not hammering a host that has published none.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "FindfarmsResearchBot/1.0 (personal land research; contact via site owner)"

# Minimum seconds between requests to the same host when the host has not
# published a Crawl-delay. Deliberately slow — this is a personal research
# tool making tens of requests, not a crawler, and there is no reason to be
# anywhere near a host's tolerance.
DEFAULT_CRAWL_DELAY = 5.0
MIN_CRAWL_DELAY = 2.0

ROBOTS_CACHE_TTL = 3600     # re-read robots.txt hourly, not per request
FETCH_TIMEOUT = 20

_robots_cache: dict = {}      # host -> (parser|None, fetched_at, status)
_last_request: dict = {}      # host -> monotonic timestamp


class NotPermitted(Exception):
    """Raised when a fetch is refused. Carries the reason for the audit log."""


def _host_of(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _load_robots(base: str):
    """Fetch and parse robots.txt for a host, with caching.

    Returns (parser, status) where status is one of "ok", "absent",
    "unreachable". The caller treats "unreachable" as a refusal.
    """
    now = time.time()
    cached = _robots_cache.get(base)
    if cached and now - cached[1] < ROBOTS_CACHE_TTL:
        return cached[0], cached[2]

    url = base.rstrip("/") + "/robots.txt"
    parser = RobotFileParser()
    parser.set_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parser.parse(body.splitlines())
        status = "ok"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # Access to robots.txt itself is restricted. Under the standard
            # this means the whole site is disallowed.
            parser, status = None, "forbidden"
        elif e.code >= 400 and e.code < 500:
            # 404 and friends: no robots.txt published, no restrictions.
            parser, status = None, "absent"
        else:
            parser, status = None, "unreachable"
    except Exception:
        parser, status = None, "unreachable"

    _robots_cache[base] = (parser, now, status)
    return parser, status


def may_fetch(url: str, user_agent: str = USER_AGENT) -> tuple[bool, str]:
    """Whether robots.txt permits fetching this URL. Returns (allowed, why).

    Fails closed on anything ambiguous. The `why` string is recorded in the
    discovery log for every attempt, allowed or not, so the record of what
    was and was not accessed is auditable after the fact.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, "Not an http(s) URL."

    base = _host_of(url)
    parser, status = _load_robots(base)

    if status == "absent":
        return True, f"No robots.txt published at {base} — no crawl restrictions declared."
    if status == "forbidden":
        return False, (f"robots.txt at {base} is itself access-restricted, which "
                       f"disallows the whole site.")
    if status == "unreachable" or parser is None:
        return False, (f"Could not read robots.txt at {base}. Refusing — an "
                       f"unreadable robots.txt means we do not know what is "
                       f"permitted, and this gate fails closed by design.")

    try:
        allowed = parser.can_fetch(user_agent, url)
    except Exception:
        return False, "robots.txt could not be evaluated for this URL. Refusing."

    if allowed:
        return True, f"Allowed by robots.txt at {base}."
    return False, f"Disallowed by robots.txt at {base} for {user_agent}."


def crawl_delay(url: str, user_agent: str = USER_AGENT) -> float:
    """The host's declared Crawl-delay, or our slower default.

    Never returns less than MIN_CRAWL_DELAY even if a host declares a shorter
    one — a permitted rate is not an obligation to use it.
    """
    base = _host_of(url)
    parser, status = _load_robots(base)
    declared = None
    if parser is not None:
        try:
            declared = parser.crawl_delay(user_agent)
        except Exception:
            declared = None
    if declared is None:
        return DEFAULT_CRAWL_DELAY
    return max(float(declared), MIN_CRAWL_DELAY)


def _wait_for_host(url: str) -> None:
    host = urlparse(url).netloc
    delay = crawl_delay(url)
    last = _last_request.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
    _last_request[host] = time.monotonic()


def fetch(url: str, user_agent: str = USER_AGENT) -> dict:
    """The only sanctioned way to make an HTTP request in this system.

    Checks robots.txt, waits out the per-host rate limit, then fetches.
    Raises NotPermitted rather than returning an error, so a caller cannot
    accidentally treat a refusal as an empty page and carry on.

    Login walls, paywalls and CAPTCHAs are NOT handled and never will be: a
    401/403 or a challenge page is returned as-is for the caller to record
    and move past. There is no session handling, no cookie jar and no
    credential store anywhere in this codebase, which is the structural
    reason it cannot bypass an access control even by mistake.
    """
    allowed, why = may_fetch(url, user_agent)
    if not allowed:
        raise NotPermitted(why)

    _wait_for_host(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read(4_000_000).decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "url": resp.url,
                    "body": body, "robots_note": why}
    except urllib.error.HTTPError as e:
        note = ""
        if e.code in (401, 403):
            note = ("Access-controlled. Not attempting to authenticate — this "
                    "system holds no credentials and does not bypass logins.")
        elif e.code == 429:
            note = ("Rate limited by the host. Backing off; not retrying "
                    "aggressively.")
        return {"ok": False, "status": e.code, "url": url, "body": "",
                "error": str(e), "note": note, "robots_note": why}
    except Exception as e:
        return {"ok": False, "status": None, "url": url, "body": "",
                "error": str(e), "robots_note": why}


def looks_like_access_wall(html: str) -> str | None:
    """Detect a login/CAPTCHA/paywall page so the caller stops rather than
    parsing the wall as though it were content.

    Without this, a login page silently extracts as a property with no
    fields and pollutes the database with empty records — and worse, makes
    it look like the source was successfully covered when it was not.
    """
    if not html:
        return None
    low = html.lower()[:20000]
    checks = (
        ("captcha", "CAPTCHA challenge"),
        ("recaptcha", "reCAPTCHA challenge"),
        ("cf-challenge", "Cloudflare challenge"),
        ("please enable javascript and cookies", "JS/cookie challenge"),
        ("sign in to continue", "login wall"),
        ("log in to continue", "login wall"),
        ("subscribe to read", "paywall"),
        ("this content is for subscribers", "paywall"),
        ("you must be logged in", "login wall"),
    )
    for needle, label in checks:
        if needle in low:
            return label
    return None
