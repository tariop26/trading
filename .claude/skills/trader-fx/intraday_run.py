"""Orchestration of the intraday signal alerts for one run of the alert server.

Python 3 standard library only. Pure orchestration: no file or network access other than the
`fetch_bars` and `get_events` callables the caller injects. `collect` returns the same kind of
`(text, mark)` items as the queue of `alerts_run.py` (`mark(state)` is called once Telegram
answered 200) plus short French log lines, which the caller prints; this module prints nothing.
"""
import math
from collections import Counter

import alert_checks
import alert_messages
import alert_state
import data
import intraday_plan
import intraday_signals
import sessions
import strength

MAX_NAMED_FAILURES = 5


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _failure_line(failed):
    names = [f.get("symbol") if isinstance(f, dict) else f for f in failed]
    names = [str(n) for n in names]
    shown = ", ".join(names[:MAX_NAMED_FAILURES])
    more = ", …" if len(names) > MAX_NAMED_FAILURES else ""
    return "signaux en séance : %d symbole(s) sans données (%s%s)." % (len(names), shown, more)


def _summary_line(n_candidates, reasons):
    parts = ["%s ×%d" % (reason, n) for reason, n in sorted(reasons.items())
             if reason != intraday_plan.REASON_NO_SIGNAL]
    return "signaux en séance : %d candidat(s)%s." % (
        n_candidates, " ; refus : " + ", ".join(parts) if parts else "")


def collect(now, document, get_events, open_rules, state, config, fetch_bars, workers=3):
    """-> (items, log). items = [(text, mark(state))] in sending order; log = French lines."""
    cfg = config["intraday"]
    if not cfg["enabled"]:
        return [], []
    if sessions.market_state(now) == "closed_weekend":
        return [], ["signaux en séance : marché fermé (week-end)."]
    if document is None:
        return [], ["briefing indisponible : signaux en séance sautés."]
    context = document.get("daily_context")
    if not isinstance(context, dict) or not context:
        return [], ["contexte journalier absent : signaux en séance sautés."]

    wanted = cfg["symbols"]
    symbols = [s for s in context if not wanted or s in wanted]
    log = []
    series, failed = fetch_bars(symbols, *data.INTRADAY_15, cache_dir=None, ttl_s=0,
                                use_cache=False, workers=workers)
    if failed:
        log.append(_failure_line(failed))
    if not series:
        return [], log

    params = intraday_signals.signal_params(config)
    prices = {}
    for sym, ctx in context.items():       # the whole context: a USD conversion may need a pair
        if (strength.pair_currencies(sym) is not None and isinstance(ctx, dict)
                and _number(ctx.get("last"))):
            prices[sym] = ctx["last"]

    candidates, reasons = [], Counter()
    for sym in symbols:
        if sym not in series:
            continue
        ctx = context[sym]
        try:
            bars = intraday_signals.closed_bars(series[sym].bars, now)
            ranges = intraday_signals.session_ranges(bars, now, params)
            name = (ctx.get("name") if isinstance(ctx, dict) else None) or sym
            cand, reason = intraday_plan.scan_symbol(sym, name, bars, ranges, ctx, config,
                                                     prices, now)
        except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the others: type only
            log.append("%s : erreur inattendue (%s), symbole sauté." % (sym, type(e).__name__))
            continue
        if cand is not None:
            candidates.append(cand)
        else:
            reasons[reason] += 1
    log.append(_summary_line(len(candidates), reasons))

    candidates = [c for c in candidates
                  if not alert_checks.is_held(c["symbol"], c["side"], open_rules)]
    if candidates:
        events = get_events()
        candidates = [c for c in candidates
                      if not alert_checks.news_blocked(c["symbol"], events, now)]

    chosen, cap_reached = intraday_plan.select(candidates, state, config, now)
    account = (document.get("trade_ideas") or {}).get("account") or {}
    items = [(alert_messages.signal_message(c, account, c.get("previous")),
              lambda st, c=c: alert_state.mark_signal(st, c, now))
             for c in chosen]
    today = now.date().isoformat()
    if cap_reached and state.get("signals_cap_day") != today:
        items.append((alert_messages.cap_message(cfg["max_per_day"]),
                      lambda st: st.update(signals_cap_day=today)))
    return items, log
