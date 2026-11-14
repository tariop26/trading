"""Forex session hours (DST from zoneinfo) and the weekend market state."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SESSIONS = {
    "Sydney": ("Australia/Sydney", 7, 16),
    "Tokyo": ("Asia/Tokyo", 9, 18),
    "London": ("Europe/London", 8, 17),
    "New York": ("America/New_York", 8, 17),
}

PARIS = ZoneInfo("Europe/Paris")
NEW_YORK = ZoneInfo("America/New_York")


def _aware_utc(now_utc):
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return now_utc.astimezone(timezone.utc)


def market_state(now_utc):
    """'closed_weekend' from Friday 17:00 to Sunday 17:00 New York, else 'open'.

    Friday 17:00 itself is closed; Sunday 17:00 itself is open.
    """
    t = _aware_utc(now_utc).astimezone(NEW_YORK)
    wd = t.weekday()  # Mon=0 ... Sun=6
    if wd == 4 and t.hour >= 17:
        return "closed_weekend"
    if wd == 5:
        return "closed_weekend"
    if wd == 6 and t.hour < 17:
        return "closed_weekend"
    return "open"


def _local_at(day, hour, tz):
    """Wall-clock `hour`:00 on local date `day` in `tz`, as an aware datetime."""
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)


def session_table(now_utc):
    """One entry per session for its own local date of `now_utc`."""
    now = _aware_utc(now_utc)
    rows = []
    for name, (tzname, open_h, close_h) in SESSIONS.items():
        tz = ZoneInfo(tzname)
        day = now.astimezone(tz).date()
        opened = _local_at(day, open_h, tz)
        closed = _local_at(day, close_h, tz)
        rows.append({
            "name": name,
            "open_paris": opened.astimezone(PARIS).strftime("%H:%M"),
            "close_paris": closed.astimezone(PARIS).strftime("%H:%M"),
            "open_ny": opened.astimezone(NEW_YORK).strftime("%H:%M"),
            "close_ny": closed.astimezone(NEW_YORK).strftime("%H:%M"),
            "active": opened <= now < closed,
        })
    return rows


def entry_session(when_utc, sessions=SESSIONS):
    """Name of the session of an entry: among the sessions active at `when_utc` (same hours
    as `session_table`), the one that opened most recently; "hors session" when none is."""
    now = _aware_utc(when_utc)
    best = None
    for name, (tzname, open_h, close_h) in sessions.items():
        tz = ZoneInfo(tzname)
        day = now.astimezone(tz).date()
        opened = _local_at(day, open_h, tz)
        closed = _local_at(day, close_h, tz)
        if opened <= now < closed and (best is None or opened > best[0]):
            best = (opened, name)
    return best[1] if best else "hors session"
