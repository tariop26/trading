"""What the alert server looks for: new ideas, touched stop and target levels, coming announcements.

Standard library only, pure functions: no file, no network. A malformed input (a rule, an event,
a bar) is skipped, never fatal, so one bad record cannot silence the others.

Bars are `(ts_utc_seconds, open, high, low, close)`, the format of `data.Series.bars`.
"""
from datetime import datetime, timedelta, timezone

import strength

MAX_IDEAS = 3
WINDOW_MAX = timedelta(minutes=30)
KINDS = ("stop", "cible")
SIDES = ("haussier", "baissier")


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _aware(text):
    """An ISO 8601 string with an offset -> aware datetime, else None."""
    try:
        when = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None and when.utcoffset() is not None else None


def _valid_rule(rule):
    return (isinstance(rule, dict) and isinstance(rule.get("id"), str)
            and isinstance(rule.get("trade_id"), str)
            and isinstance(rule.get("symbol"), str) and rule.get("type") in KINDS
            and rule.get("side") in SIDES and _number(rule.get("level")))


# ---------------------------------------------------------------- ideas

def idea_key(idea, today):
    return "%s|%s|%s" % (idea.get("symbol"), idea.get("side"), today)


def new_ideas(briefing, open_rules, state, today, limit=MAX_IDEAS):
    """-> (ideas to announce now, how many more are waiting for the next run).

    An idea is eligible when it was not announced today, is not already an open trade (same
    symbol and side in `open_rules`) and is not void (stop crossed or target reached since the
    close). Nothing is announced on a closed weekend: the prices are closes, nothing is forming."""
    if not isinstance(briefing, dict) or briefing.get("market_state") == "closed_weekend":
        return [], 0
    held = {(r.get("symbol"), r.get("side")) for r in open_rules if isinstance(r, dict)}
    sent = set(state.get("ideas_sent", []))
    ideas = (briefing.get("trade_ideas") or {}).get("ideas") if isinstance(
        briefing.get("trade_ideas"), dict) else None
    eligible = []
    for idea in ideas if isinstance(ideas, list) else []:
        if not isinstance(idea, dict):
            continue
        if idea_key(idea, today) in sent or (idea.get("symbol"), idea.get("side")) in held:
            continue
        since = idea.get("since_close")
        if isinstance(since, dict) and (since.get("stop_crossed") or since.get("target_crossed")):
            continue
        eligible.append(idea)
    eligible.sort(key=lambda i: i["rank"] if _number(i.get("rank")) else float("inf"))
    return eligible[:limit], max(0, len(eligible) - limit)


# ---------------------------------------------------------------- stop and target contacts

def rule_key(rule):
    """What a fired rule is remembered by. The level and `since` are part of it: when the user
    moves a level the rule is new, and is watched from the move."""
    return "%s|%s|%s" % (rule.get("id"), rule.get("level"), rule.get("since"))


def _touch(rule, high, low):
    """(touched, extreme value, "plus haut" | "plus bas") of one bar against one rule."""
    long_side = rule["side"] == "haussier"
    # the loss side of a stop (and the gain side of a target) is below the price for a long trade
    looks_down = (rule["type"] == "stop") == long_side
    if looks_down:
        return low <= rule["level"], low, "plus bas"
    return high >= rule["level"], high, "plus haut"


def touched_rules(rules, bars, state, fallback_since):
    """-> (hits, log lines). `bars` maps a symbol to its list of bars.

    A hit is {"rule", "bar_time", "extreme", "extreme_kind"}: the first bar starting strictly
    after the rule's `since` (else `fallback_since`) whose high or low reaches the level. The
    raw high and low decide, not the close, so a touch between two runs is never missed."""
    fired = set(state.get("rules_fired", []))
    hits, log = [], []
    for rule in rules if isinstance(rules, list) else []:
        if not _valid_rule(rule):
            log.append("règle ignorée (mal formée) : %r" % (rule,))
            continue
        if rule_key(rule) in fired:
            continue
        since = _aware(rule.get("since") if rule.get("since") is not None else fallback_since)
        if since is None:
            log.append("règle %s ignorée : since illisible" % rule["id"])
            continue
        series = bars.get(rule["symbol"]) if isinstance(bars, dict) else None
        if not series:
            log.append("pas de barres pour %s : règle %s sautée" % (rule["symbol"], rule["id"]))
            continue
        for bar in sorted((b for b in series if _number(b[0])), key=lambda b: b[0]):
            if bar[0] <= since.timestamp() or not (_number(bar[2]) and _number(bar[3])):
                continue
            touched, extreme, kind = _touch(rule, bar[2], bar[3])
            if touched:
                when = datetime.fromtimestamp(bar[0], timezone.utc).isoformat()
                hits.append({"rule": rule, "bar_time": when, "extreme": extreme,
                             "extreme_kind": kind})
                break
    return hits, log


# ---------------------------------------------------------------- announcements

def trade_currencies(symbol):
    """The currencies a trade is exposed to: the pair's two for forex, else USD."""
    pair = strength.pair_currencies(symbol)
    return set(pair) if pair else {"USD"}


def event_key(event):
    return "%s|%s|%s" % (event.get("utc"), event.get("currency"), event.get("title"))


def upcoming_events(events, open_rules, now_utc, state):
    """-> [{"event", "minutes", "symbols"}]: high-impact events still to come within 30 minutes
    that touch a currency of an open trade and were not announced yet.

    The window opens at "now", not at 15 minutes: runs are 15 minutes apart, so a run that starts
    late (or is dropped by GitHub) would otherwise leave an event nobody announces. Normally an
    event is announced by the run that sees it 30 to 15 minutes ahead; a late run announces it
    later rather than never."""
    symbols = sorted({r["symbol"] for r in open_rules if _valid_rule(r)})
    if not symbols:
        return []
    sent = set(state.get("events_sent", []))
    out = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("impact") != "High":
            continue
        start = _aware(event.get("utc"))
        if start is None or event_key(event) in sent:
            continue
        ahead = start - now_utc
        if not timedelta(0) < ahead <= WINDOW_MAX:
            continue
        concerned = [s for s in symbols if event.get("currency") in trade_currencies(s)]
        if concerned:
            out.append({"event": event, "minutes": max(1, int(ahead.total_seconds() // 60)),
                        "symbols": concerned})
    return out


# ---------------------------------------------------------------- intraday signal filters

def news_blocked(symbol, events, now_utc, window_minutes=30):
    """True when a high-impact event of a currency of `symbol` starts in (now, now + window].

    Same boundaries as `upcoming_events`: an event exactly at "now" does not block, one exactly
    at the end of the window does. A malformed event is skipped, never fatal."""
    currencies = trade_currencies(symbol)
    window = timedelta(minutes=window_minutes)
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("impact") != "High":
            continue
        currency = event.get("currency")
        start = _aware(event.get("utc"))
        if not isinstance(currency, str) or currency not in currencies or start is None:
            continue
        if timedelta(0) < start - now_utc <= window:
            return True
    return False


def is_held(symbol, side, open_rules):
    """True when a valid open rule already follows this symbol on this side."""
    if not isinstance(open_rules, list):
        return False
    return any(_valid_rule(r) and r["symbol"] == symbol and r["side"] == side
               for r in open_rules)
