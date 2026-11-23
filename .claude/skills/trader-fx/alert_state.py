"""State the alert server keeps between two runs, so a message is never sent twice.

Standard library only. The state lives in the Actions cache (a lost cache means an empty state:
at worst one duplicate message, never a missing one). Everything here is a pure function on a
dictionary except `load_state` and `save_state`.

    {"v": 1, "day": "YYYY-MM-DD", "ideas_sent": [...], "rules_fired": [...],
     "events_sent": [...], "down_notified_day": "YYYY-MM-DD" | None,
     "signals_sent": [...], "signals_count": 0, "signals_cap_day": "YYYY-MM-DD" | None}

`signals_sent` holds one string per intraday-signal alert,
"SYMBOLE|sens|barre_iso|score|envoi_iso|fam1+fam2"; `signals_count` is the number of signal alerts
marked today; `signals_cap_day` is the day the "plafond atteint" notice went out. `guard_sent` holds
the keys of the FundedNext risk-guard messages sent today ("guard|kind|day"). The signal keys and
`guard_sent` are optional when loading (a state saved before they existed still loads).
"""
import copy
import json
from datetime import datetime, timedelta

import journal

STATE_VERSION = 1
LIST_KEYS = ("ideas_sent", "rules_fired", "events_sent")


def empty_state(day):
    return {"v": STATE_VERSION, "day": day, "ideas_sent": [], "rules_fired": [],
            "events_sent": [], "down_notified_day": None,
            "signals_sent": [], "signals_count": 0, "signals_cap_day": None,
            "guard_sent": []}


def _valid(doc):
    if not isinstance(doc, dict) or doc.get("v") != STATE_VERSION:
        return False
    if not isinstance(doc.get("day"), str):
        return False
    if doc.get("down_notified_day") is not None and not isinstance(doc["down_notified_day"], str):
        return False
    if "signals_sent" in doc and not (isinstance(doc["signals_sent"], list)
                                      and all(isinstance(x, str) for x in doc["signals_sent"])):
        return False
    if "guard_sent" in doc and not (isinstance(doc["guard_sent"], list)
                                    and all(isinstance(x, str) for x in doc["guard_sent"])):
        return False
    if "signals_count" in doc:
        n = doc["signals_count"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            return False
    cap = doc.get("signals_cap_day")
    if cap is not None and not isinstance(cap, str):
        return False
    return all(isinstance(doc.get(k), list) and all(isinstance(x, str) for x in doc[k])
               for k in LIST_KEYS)


def load_state(path, today):
    """The saved state, or an empty one (missing, unreadable, corrupt, other version). A new
    UTC day forgets the ideas already announced, the down notice and the signal alerts (list,
    count, cap notice), and keeps the rest. Missing signal keys are filled with their defaults."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):                  # ValueError: bad JSON or bad UTF-8
        return empty_state(today)
    if not _valid(doc):
        return empty_state(today)
    state = copy.deepcopy(doc)
    state.setdefault("signals_sent", [])
    state.setdefault("signals_count", 0)
    state.setdefault("signals_cap_day", None)
    state.setdefault("guard_sent", [])
    if state["day"] != today:
        state.update(day=today, ideas_sent=[], down_notified_day=None,
                     signals_sent=[], signals_count=0, signals_cap_day=None, guard_sent=[])
    return state


def _parse_sent(entry):
    """(symbol, side, score, send time, families) of a signals_sent entry, None when malformed."""
    parts = entry.split("|")
    if len(parts) != 6:
        return None
    try:
        sent = datetime.fromisoformat(parts[4])
        score = int(parts[3])
    except ValueError:
        return None
    if sent.tzinfo is None:
        return None
    return parts[0], parts[1], score, sent, [f for f in parts[5].split("+") if f]


def last_signal(state, symbol, side, now_utc, cooldown_minutes):
    """The latest signal alert sent for this symbol and side when it is still inside the rest
    period ({"score", "families", "sent_iso"}), else None. Exactly at the cooldown is outside; a
    cooldown of 0 never rests. Malformed entries are skipped."""
    if cooldown_minutes <= 0:
        return None
    best = None
    for entry in state.get("signals_sent", []):
        parsed = _parse_sent(entry) if isinstance(entry, str) else None
        if parsed is None or parsed[0] != symbol or parsed[1] != side:
            continue
        if best is None or parsed[3] > best[3]:
            best = parsed
    if best is None or not now_utc - best[3] < timedelta(minutes=cooldown_minutes):
        return None
    return {"score": best[2], "families": best[4], "sent_iso": best[3].isoformat()}


def signal_sent_for_bar(state, symbol, side, bar_iso):
    """True when a signal alert was already marked for this symbol, side and signal bar."""
    prefix = "%s|%s|%s|" % (symbol, side, bar_iso)
    return any(isinstance(e, str) and e.startswith(prefix) for e in state.get("signals_sent", []))


def mark_signal(state, candidate, now_utc):
    """Records a signal alert (mutates `state`) and counts it for today."""
    state["signals_sent"].append("%s|%s|%s|%d|%s|%s" % (
        candidate["symbol"], candidate["side"], candidate["bar_iso"], candidate["score"],
        now_utc.isoformat(), "+".join(candidate["families"])))
    state["signals_count"] += 1


def prune(state, active_rule_ids, future_event_keys):
    """A copy that forgets fired rules no longer in alerts.json and announced events already past."""
    out = copy.deepcopy(state)
    out["rules_fired"] = [r for r in state["rules_fired"] if r in active_rule_ids]
    out["events_sent"] = [e for e in state["events_sent"] if e in future_event_keys]
    return out


def save_state(path, state):
    """Atomic write; raises journal.JournalError when the file cannot be written."""
    journal.write_json_atomic(path, state)
