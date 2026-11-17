"""Plan of an intraday signal: rounded entry, stop, target, R:R and validity limit.

Python 3 standard library only. Pure function. It reuses the rounding helpers of
`plan.py` (price grid, direction of rounding, side check) so a signal plan rounds
exactly like the daily trade ideas.
"""
import math

import plan

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
