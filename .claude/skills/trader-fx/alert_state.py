"""State the alert server keeps between two runs, so a message is never sent twice.

Standard library only. The state lives in the Actions cache (a lost cache means an empty state:
at worst one duplicate message, never a missing one). Everything here is a pure function on a
dictionary except `load_state` and `save_state`.

    {"v": 1, "day": "YYYY-MM-DD", "ideas_sent": [...], "rules_fired": [...],
     "events_sent": [...], "down_notified_day": "YYYY-MM-DD" | None}
"""
import copy
import json

import journal

STATE_VERSION = 1
LIST_KEYS = ("ideas_sent", "rules_fired", "events_sent")


def empty_state(day):
    return {"v": STATE_VERSION, "day": day, "ideas_sent": [], "rules_fired": [],
            "events_sent": [], "down_notified_day": None}


def _valid(doc):
    if not isinstance(doc, dict) or doc.get("v") != STATE_VERSION:
        return False
    if not isinstance(doc.get("day"), str):
        return False
    if doc.get("down_notified_day") is not None and not isinstance(doc["down_notified_day"], str):
        return False
    return all(isinstance(doc.get(k), list) and all(isinstance(x, str) for x in doc[k])
               for k in LIST_KEYS)


def load_state(path, today):
    """The saved state, or an empty one (missing, unreadable, corrupt, other version). A new
    UTC day forgets the ideas already announced and the down notice, and keeps the rest."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):                  # ValueError: bad JSON or bad UTF-8
        return empty_state(today)
    if not _valid(doc):
        return empty_state(today)
    state = copy.deepcopy(doc)
    if state["day"] != today:
        state.update(day=today, ideas_sent=[], down_notified_day=None)
    return state


def prune(state, active_rule_ids, future_event_keys):
    """A copy that forgets fired rules no longer in alerts.json and announced events already past."""
    out = copy.deepcopy(state)
    out["rules_fired"] = [r for r in state["rules_fired"] if r in active_rule_ids]
    out["events_sent"] = [e for e in state["events_sent"] if e in future_event_keys]
    return out


def save_state(path, state):
    """Atomic write; raises journal.JournalError when the file cannot be written."""
    journal.write_json_atomic(path, state)
