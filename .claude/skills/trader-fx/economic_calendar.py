"""Public economic calendar (unofficial feed), parsed and filtered. Standard library only.

The feed is not official and may change or vanish, so this is the only module
that knows about it. fetch_calendar() never raises: it returns a status, and the
briefing always shows that status.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from strength import pair_currencies

URL_THIS = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
URL_NEXT = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

UA = "Mozilla/5.0 (compatible; trader-fx/1.0)"
TIMEOUT = 20

PARIS = ZoneInfo("Europe/Paris")
NEW_YORK = ZoneInfo("America/New_York")


def _http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _text(v):
    return "" if v is None else str(v)


def _parse_one(item):
    if not isinstance(item, dict):
        return None
    country, date = item.get("country"), item.get("date")
    if not isinstance(country, str) or not country or not isinstance(date, str):
        return None
    try:
        dt = datetime.fromisoformat(date)
    except ValueError:
        return None
    if dt.tzinfo is None:  # no offset: cannot place it in time, so skip it
        return None
    utc = dt.astimezone(timezone.utc)
    paris, ny = utc.astimezone(PARIS), utc.astimezone(NEW_YORK)
    return {
        "utc": utc.isoformat(),
        "time_paris": paris.strftime("%H:%M"),
        "time_ny": ny.strftime("%H:%M"),
        "date_paris": paris.strftime("%Y-%m-%d"),
        "date_ny": ny.strftime("%Y-%m-%d"),
        "currency": country,
        "title": _text(item.get("title")),
        "impact": _text(item.get("impact")),
        "forecast": _text(item.get("forecast")),
        "previous": _text(item.get("previous")),
    }


def parse_events(doc):
    """Feed JSON (a list of dicts) -> normalized events. Malformed entries are skipped."""
    if not isinstance(doc, list):
        return []
    out = []
    for item in doc:
        ev = _parse_one(item)
        if ev is not None:
            out.append(ev)
    return out


def filter_events(events, currencies, impacts=("High",)):
    """Keep events whose currency is in `currencies` and impact in `impacts`.
    Country "All" (not a currency) is always dropped."""
    return [e for e in events
            if e["currency"] != "All" and e["currency"] in currencies
            and e["impact"] in impacts]


def within_hours(events, start_utc, hours=24):
    """Events with start <= time < start + hours."""
    end = start_utc + timedelta(hours=hours)
    return [e for e in events if start_utc <= datetime.fromisoformat(e["utc"]) < end]


def _load(url, http_get):
    """-> (events, None) or (None, reason). Never raises."""
    try:
        doc = json.loads(http_get(url))
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:  # network, timeout, bad JSON: all just "not available"
        return None, "%s: %s" % (type(e).__name__, e)
    if not isinstance(doc, list):
        return None, "unexpected feed format"
    return parse_events(doc), None


def fetch_calendar(*, http_get=None):
    """-> {"status": "ok"|"partial"|"unavailable", "events": [...]} sorted by time.
    This week failing gives unavailable; next week missing (404 means not yet
    published) or failing gives partial."""
    get = http_get or _http_get
    this_week, _ = _load(URL_THIS, get)
    if this_week is None:
        return {"status": "unavailable", "events": []}
    next_week, _ = _load(URL_NEXT, get)
    events = this_week + (next_week or [])
    events.sort(key=lambda e: e["utc"])
    return {"status": "ok" if next_week is not None else "partial", "events": events}


def focus_currencies(symbols):
    """Currencies of the forex pairs among `symbols`, plus USD."""
    out = {"USD"}
    for s in symbols:
        pair = pair_currencies(s)
        if pair:
            out.update(pair)
    return out
