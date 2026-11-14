"""Statistics of the trading journal. Standard library only, pure functions.

Only closed trades count. Every group carries its number of trades `n` and a `few` flag
(fewer than FEW trades); the whole sample carries a warning under MIN_TRADES. A trade whose R is
unknown (`r` is None) is counted in `n` but left out of the R averages. Weekdays and sessions
follow the entry time: weekdays in Paris time, sessions as `sessions.entry_session`.
"""
from datetime import datetime

import plan
import sessions

R_FLAT = 0.05        # |R| below this is break-even
MIN_TRADES = 30      # below this many closed trades, the sample is too small to conclude
FEW = 5              # a group with fewer trades is marked "few"
SAMPLE_WARNING = "échantillon trop petit pour conclure"

WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
SESSION_ORDER = ("Sydney", "Tokyo", "London", "New York", "hors session")
TRIGGERS = tuple(plan.LONG_TRIGGERS) + tuple(plan.SHORT_TRIGGERS)
OFF_PLAN = "hors plan"
NO_RULE = "sans règle"


def classify(trade):
    """"positif", "negatif" or "equilibre" for a closed trade, None for an open one.

    By R when it is known (|R| < R_FLAT is break-even), else by the sign of the result."""
    result = trade.get("result")
    if trade.get("status") != "closed" or not isinstance(result, dict):
        return None
    r = result.get("r")
    if r is not None:
        if abs(r) < R_FLAT:
            return "equilibre"
        return "positif" if r > 0 else "negatif"
    pnl = result.get("pnl_usd") or 0.0
    return "positif" if pnl > 0 else "negatif" if pnl < 0 else "equilibre"


def _rs(trades):
    return [t["result"]["r"] for t in trades if t["result"].get("r") is not None]


def _mean(values):
    return round(sum(values) / len(values), 4) if values else None


def _group(key, trades):
    n = len(trades)
    rs = _rs(trades)
    positives = sum(1 for t in trades if classify(t) == "positif")
    return {
        "key": key,
        "n": n,
        "win_rate": round(positives / n, 4) if n else None,
        "avg_r": _mean(rs),
        "total_r": round(sum(rs), 2),
        "pnl_usd": round(sum(t["result"]["pnl_usd"] for t in trades), 2),
        "few": n < FEW,
    }


def _groups(buckets, order=None):
    """Groups sorted by `order` (fixed key order) or by n descending then key."""
    groups = [_group(key, trades) for key, trades in buckets.items() if trades]
    if order is not None:
        return sorted(groups, key=lambda g: order.index(g["key"]) if g["key"] in order else len(order))
    return sorted(groups, key=lambda g: (-g["n"], g["key"]))


def _entry_dt(trade):
    return datetime.fromisoformat(trade["entry"]["time"])


def _overall(trades):
    classes = [classify(t) for t in trades]
    rs = _rs(trades)
    positive_rs = [t["result"]["r"] for t in trades
                   if classify(t) == "positif" and t["result"].get("r") is not None]
    negative_rs = [t["result"]["r"] for t in trades
                   if classify(t) == "negatif" and t["result"].get("r") is not None]
    n = len(trades)
    return {
        "n": n,
        "positive": classes.count("positif"),
        "negative": classes.count("negatif"),
        "flat": classes.count("equilibre"),
        "win_rate": round(classes.count("positif") / n, 4) if n else None,
        "avg_r_positive": _mean(positive_rs),
        "avg_r_negative": _mean(negative_rs),
        "expectancy_r": _mean(rs),
        "total_r": round(sum(rs), 2),
        "pnl_usd": round(sum(t["result"]["pnl_usd"] for t in trades), 2),
        "n_estimated": sum(1 for t in trades if t["result"].get("source") == "estime"),
        "n_no_r": sum(1 for t in trades if t["result"].get("r") is None),
    }


def _errors(trades):
    buckets = {}
    for t in trades:
        for tag in t.get("tags") or []:
            buckets.setdefault(tag, []).append(t)
    rows = []
    for tag, items in buckets.items():
        rs = _rs(items)
        rows.append({"tag": tag, "n": len(items), "avg_r": _mean(rs), "total_r": round(sum(rs), 2)})
    return sorted(rows, key=lambda r: (-r["n"], r["tag"]))


def _equity(trades, capital, cap_pct):
    ordered = sorted(trades, key=lambda t: datetime.fromisoformat(t["exit"]["time"]))
    equity, peak, worst_dd, worst_dd_pct = capital, capital, 0.0, 0.0
    points = []
    best_run, run_n, run_r = {"n": 0, "r": 0.0}, 0, 0.0
    for t in ordered:
        equity = round(equity + t["result"]["pnl_usd"], 2)
        points.append({"time": t["exit"]["time"], "trade_id": t["id"], "equity": equity})
        peak = max(peak, equity)
        drop = round(peak - equity, 2)
        if drop > worst_dd:
            worst_dd, worst_dd_pct = drop, round(drop / peak * 100, 4)
        if classify(t) == "negatif":
            run_n += 1
            run_r = round(run_r + (t["result"].get("r") or 0.0), 2)
            # the longest run wins; on a tie, the one that cost the most R
            if run_n > best_run["n"] or (run_n == best_run["n"] and run_r < best_run["r"]):
                best_run = {"n": run_n, "r": run_r}
        else:
            run_n, run_r = 0, 0.0
    return {"start": float(capital), "end": float(equity), "points": points,
            "max_drawdown_usd": worst_dd, "max_drawdown_pct": worst_dd_pct,
            "worst_streak": best_run, "cap_pct": cap_pct}


def compute_stats(journal, capital=100000.0, cap_pct=2.0):
    """The statistics of the journal (spec 4.4). The journal is never modified."""
    all_trades = journal.get("trades", [])
    closed = [t for t in all_trades if t.get("status") == "closed" and isinstance(t.get("result"), dict)]
    n_open = sum(1 for t in all_trades if t.get("status") == "open")

    by_rule, by_side, by_symbol, by_session, by_weekday = {}, {}, {}, {}, {}
    for t in closed:
        if t.get("source") == "idee":
            rules = [s for s in (t.get("idea") or {}).get("setups", []) if s in TRIGGERS] or [NO_RULE]
        else:
            rules = [OFF_PLAN]
        for rule in rules:
            by_rule.setdefault(rule, []).append(t)
        by_side.setdefault(t["side"], []).append(t)
        by_symbol.setdefault(t["symbol"], []).append(t)
        when = _entry_dt(t)
        by_session.setdefault(sessions.entry_session(when), []).append(t)
        by_weekday.setdefault(WEEKDAYS[when.astimezone(sessions.PARIS).weekday()], []).append(t)

    return {
        "n_closed": len(closed),
        "n_open": n_open,
        "sample_warning": SAMPLE_WARNING if len(closed) < MIN_TRADES else None,
        "overall": _overall(closed),
        "by_rule": _groups(by_rule),
        "by_side": _groups(by_side),
        "by_symbol": _groups(by_symbol),
        "by_session": _groups(by_session, SESSION_ORDER),
        "by_weekday": _groups(by_weekday, WEEKDAYS),
        "errors": _errors(closed),
        "equity": _equity(closed, capital, cap_pct),
    }
