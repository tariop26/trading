"""Plan of an intraday signal: rounded entry, stop, target, R:R and validity limit.

Python 3 standard library only. Pure function. It reuses the rounding helpers of
`plan.py` (price grid, direction of rounding, side check) so a signal plan rounds
exactly like the daily trade ideas.
"""
import math
from datetime import datetime, timezone

import alert_state
import intraday_signals
import plan
import sizing

REASON_IMPOSSIBLE = "plan impossible"
REASON_TOO_CLOSE = "stop trop proche"
REASON_TOO_WIDE = "stop trop large"
REASON_RR = "rapport 1:R sous le minimum"
REASON_NO_DAILY_ATR = "ATR journalier indisponible"


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def make_signal_plan(symbol, side, close, stop_raw, target_raw, daily_atr, params):
    """(plan, None) or (None, reason).

    plan = {"reference_price", "stop", "target", "rr", "decimals", "limit_price"}.
    The entry is the close rounded to the nearest tick; the stop is rounded AWAY from
    the entry; the target (`target_raw`, or entry +/- target_r * dist when None) and the
    limit price (entry +/- validity_r * dist, the farthest price still worth entering)
    are rounded TOWARD the entry. `params` is `intraday_signals.signal_params(config)`.
    """
    if not _number(daily_atr) or daily_atr <= 0:
        return None, REASON_NO_DAILY_ATR
    if (not _number(close) or not _number(stop_raw)
            or (target_raw is not None and not _number(target_raw))):
        return None, REASON_IMPOSSIBLE

    decimals = plan.price_decimals(symbol, close)
    tick = 10.0 ** -decimals
    entry = round(close, decimals)
    long_ = side == plan.LONG
    # long: stop (below) rounds away = down, target and limit (above) toward = down;
    # short: all three round up
    away = toward = "down" if long_ else "up"
    sign = 1 if long_ else -1

    stop = plan._round_dir(stop_raw, tick, decimals, away)
    dist = round(abs(entry - stop), decimals)
    if target_raw is None:
        target_raw = entry + sign * params["target_r"] * dist
    target = plan._round_dir(target_raw, tick, decimals, toward)
    limit_price = plan._round_dir(entry + sign * params["validity_r"] * dist,
                                  tick, decimals, toward)

    p = {"reference_price": entry, "stop": stop, "target": target,
         "decimals": decimals}
    if not plan._sides_ok(side, p):
        return None, REASON_IMPOSSIBLE
    # sides ok: stop != entry, dist > 0
    if dist / entry * 100.0 < params["min_stop_pct"]:
        return None, REASON_TOO_CLOSE
    if dist > params["max_stop_daily_atr"] * daily_atr:
        return None, REASON_TOO_WIDE
    rr = round(abs(target - entry) / dist, 2)
    if rr < params["min_rr"]:
        return None, REASON_RR
    return {"reference_price": entry, "stop": stop, "target": target, "rr": rr,
            "decimals": decimals, "limit_price": limit_price}, None


REASON_NO_SIGNAL = "aucun signal récent"
REASON_STALE = "plan caduc"


def _daily_atr(ctx):
    """Daily ATR in price units from `ctx` (last x atr_pct / 100), or None."""
    if not isinstance(ctx, dict):
        return None
    last, atr_pct = ctx.get("last"), ctx.get("atr_pct")
    if _number(last) and _number(atr_pct) and atr_pct > 0:
        return last * atr_pct / 100


def _score(families, side, trend, cfg, details):
    """(points, why lines): score_per_signal per family, +/- score_trend for the trend."""
    points, why = 0, []
    for family in families:
        points += cfg["score_per_signal"]
        text = family + (" (%s)" % details[family] if details.get(family) else "")
        why.append(plan._signed(cfg["score_per_signal"], text))
    if trend in ("up", "down") and cfg["score_trend"]:
        trend_side = plan.LONG if trend == "up" else plan.SHORT
        text = "tendance haussière" if trend == "up" else "tendance baissière"
        delta = cfg["score_trend"] if trend_side == side else -cfg["score_trend"]
        points += delta
        why.append(plan._signed(delta, text if delta > 0 else text + " (à contre-sens)"))
    return points, why


def scan_symbol(symbol, name, bars, ranges, ctx, config, prices, now_utc):
    """(candidate, None) or (None, reason) for one symbol at `now_utc`.

    Only closed bars are read. `ranges` comes from the caller (`session_ranges` on the
    closed bars); `ctx` is `daily_context[symbol]`; `prices` = {forex pair: last close}
    for the USD conversion of the size, which is never invented (a `to_confirm` or
    `too_wide` size keeps the candidate).
    """
    try:
        return _scan_symbol(symbol, name, bars, ranges, ctx, config, prices, now_utc)
    except ArithmeticError as e:
        return None, "calcul impossible (%s)" % type(e).__name__


def _scan_symbol(symbol, name, bars, ranges, ctx, config, prices, now_utc):
    params = intraday_signals.signal_params(config)
    cfg = config["intraday"]
    bars = intraday_signals.closed_bars(bars, now_utc)
    n = len(bars)

    found = []
    for i in range(max(0, n - cfg["window_bars"]), n):
        for signal in intraday_signals.detect_all(bars, i, ranges, params):
            found.append((i, signal))
    if not found:
        return None, REASON_NO_SIGNAL

    j = max(i for i, _ in found)
    age = now_utc.timestamp() - (bars[j][0] + intraday_signals.BAR_S)
    if age > cfg["max_age_minutes"] * 60:
        return None, REASON_STALE

    sides = {s["side"] for _, s in found}
    if len(sides) > 1:
        return None, plan.REASON_CONTRADICTORY
    side = sides.pop()

    in_window = {s["family"]: s for _, s in found}
    families = [f for f in intraday_signals.FAMILIES if f in in_window]
    primary = next(s for i, s in found if i == j)
    details = {f: in_window[f].get("detail") for f in families}

    daily_atr = _daily_atr(ctx)
    trend = ctx.get("trend") if isinstance(ctx, dict) else None

    p, reason = make_signal_plan(symbol, side, bars[j][4], primary["stop_raw"],
                                 primary["target_raw"], daily_atr, params)
    if p is None:
        return None, reason

    score, why = _score(families, side, trend, cfg, details)
    size = sizing.size_idea(symbol, p["reference_price"], p["stop"], prices, config)
    bar_ts = bars[j][0]
    display = (cfg.get("mt5_symbols") or {}).get(symbol) or name
    return {"symbol": symbol, "display_name": display, "side": side, "score": score,
            "why": why, "families": families, "primary": primary["family"],
            "detail": primary.get("detail", ""), "bar_ts": bar_ts,
            "bar_iso": datetime.fromtimestamp(bar_ts, timezone.utc).isoformat(),
            "plan": p, "size": size, "exposures": plan.exposures(symbol, side)}, None


def select(candidates, state, config, now_utc):
    """(chosen, cap_reached): the candidates to announce, in sending order.

    Drops a bar already announced and a symbol at rest unless its score is strictly higher
    than the last alert's (a reinforcement: the kept copy carries `"previous"`), applies
    `min_score`, ranks by score, then number of families, then symbol, keeps at most
    `max_per_exposure` per currency exposure, and cuts to `max_per_run` and to what is left of
    `max_per_day` (alerts already marked today count). `cap_reached` is True only when the DAY
    cap, not the per-run cap, left candidates unsent."""
    cfg = config["intraday"]
    kept = []
    for c in candidates:
        if alert_state.signal_sent_for_bar(state, c["symbol"], c["side"], c["bar_iso"]):
            continue
        prev = alert_state.last_signal(state, c["symbol"], c["side"], now_utc,
                                       cfg["cooldown_minutes"])
        if prev is not None:
            if not c["score"] > prev["score"]:
                continue
            c = dict(c, previous=prev)
        if cfg["min_score"] is not None and c["score"] < cfg["min_score"]:
            continue
        kept.append(c)
    kept.sort(key=lambda c: (-c["score"], -len(c["families"]), c["symbol"]))
    retained, _skipped, _ties = plan._diversify(kept, len(kept) or 1,
                                                cfg["max_per_exposure"])
    remaining_day = max(0, cfg["max_per_day"] - state.get("signals_count", 0))
    take = min(cfg["max_per_run"], remaining_day)
    cap_reached = len(retained) > remaining_day and remaining_day <= cfg["max_per_run"]
    return retained[:take], cap_reached
