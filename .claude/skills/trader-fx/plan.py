"""Mechanical trade ideas: classification, score, diversification, entry/stop/target.

Python 3 standard library only. Pure functions: they take the analyses produced by
`signals.analyze` and the validated configuration dict (parameter `config`), and
return plain dicts ready for briefing.json (`trade_ideas`, spec 4.5).
"""
import math

import sizing
import strength

LONG_TRIGGERS = ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold_bounce")
SHORT_TRIGGERS = ("breakdown_20d", "bear_flag", "lose_ma20", "overbought_reject")

LONG = "haussier"
SHORT = "baissier"

REASON_CONTRADICTORY = "signaux contradictoires"
REASON_NO_ATR = "ATR indisponible"

MINUS = "−"

TRIGGER_LABELS = {
    "breakout_20d": "cassure du plus haut 20 j",
    "bull_flag": "drapeau haussier",
    "reclaim_ma20": "retour au-dessus de la moyenne 20 j",
    "oversold_bounce": "rebond de survente",
    "breakdown_20d": "cassure du plus bas 20 j",
    "bear_flag": "drapeau baissier",
    "lose_ma20": "perte de la moyenne 20 j",
    "overbought_reject": "rejet depuis le surachat",
}


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _all_tags(analysis):
    return list(analysis.get("setups") or []) + list(analysis.get("setups_short") or [])


def classify(analysis):
    """(side, triggers, reason): side is "haussier", "baissier" or None.

    reason is "signaux contradictoires" when both directions trigger, else None.
    """
    tags = _all_tags(analysis)
    longs = [t for t in tags if t in LONG_TRIGGERS]
    shorts = [t for t in tags if t in SHORT_TRIGGERS]
    if longs and shorts:
        return None, [], REASON_CONTRADICTORY
    if longs:
        return LONG, longs, None
    if shorts:
        return SHORT, shorts, None
    return None, [], None


def _signed(points, text):
    return ("+%d %s" if points > 0 else MINUS + "%d %s") % (abs(points), text)


def score(analysis, side, triggers):
    """(points, why lines) for one idea."""
    points = 0
    why = []
    for t in triggers:
        points += 2
        why.append(_signed(2, TRIGGER_LABELS.get(t, t)))

    trend = analysis.get("trend")
    if trend in ("up", "down"):
        trend_side = LONG if trend == "up" else SHORT
        text = "tendance haussière" if trend == "up" else "tendance baissière"
        if trend_side == side:
            points += 1
            why.append(_signed(1, text))
        else:
            points -= 1
            why.append(_signed(-1, text + " (à contre-sens)"))

    rsi = analysis.get("rsi")
    if _number(rsi):
        if side == LONG:
            if rsi < 30:
                points += 1
                why.append(_signed(1, "RSI sous 30 (survente)"))
            elif rsi > 70:
                points -= 1
                why.append(_signed(-1, "RSI déjà au-dessus de 70"))
        else:
            if rsi > 70:
                points += 1
                why.append(_signed(1, "RSI au-dessus de 70 (surachat)"))
            elif rsi < 30:
                points -= 1
                why.append(_signed(-1, "RSI déjà sous 30"))
    return points, why


def exposures(symbol, side):
    """[(devise ou symbole, "+" | "-")] carried by an idea."""
    sign = "+" if side == LONG else "-"
    pair = strength.pair_currencies(symbol)
    if pair is None:
        return [(symbol, sign)]
    base, quote = pair
    other = "-" if sign == "+" else "+"
    return [(base, sign), (quote, other)]


def _step_and_decimals(symbol):
    pair = strength.pair_currencies(symbol)
    if pair is None:
        return 1e-2, 2
    if pair[1] == "JPY":
        return 1e-3, 3
    return 1e-5, 5


def _round_dir(x, step, decimals, direction):
    n = round(x / step, 6)
    n = math.floor(n) if direction == "down" else math.ceil(n)
    return round(n * step, decimals)


def make_plan(analysis, side, config):
    """{"reference_price","stop","target","rr","atr"} or None when ATR/price is unusable.

    `config` is the validated configuration dict (its "plan" section is used).
    """
    last = analysis.get("last")
    atr_pct = analysis.get("atr_pct")
    if not _number(last) or not _number(atr_pct) or atr_pct <= 0:
        return None
    plan_cfg = config.get("plan", config)
    mult = plan_cfg["stop_atr_mult"]
    target_r = plan_cfg["target_r"]

    atr = last * atr_pct / 100.0
    step, decimals = _step_and_decimals(analysis.get("symbol"))
    if side == LONG:
        raw_stop = last - mult * atr
        raw_target = last + target_r * abs(last - raw_stop)
        direction = "down"
    else:
        raw_stop = last + mult * atr
        raw_target = last - target_r * abs(last - raw_stop)
        direction = "up"
    return {
        "reference_price": last,
        "stop": _round_dir(raw_stop, step, decimals, direction),
        "target": _round_dir(raw_target, step, decimals, direction),
        "rr": target_r,
        "atr": round(atr, 6),
    }


def _diversify(candidates, max_shown, max_per_exposure):
    """Walk ranked candidates; return (retained, skipped)."""
    retained = []
    skipped = []
    held = {}   # exposure -> list of retained symbols, in rank order
    for cand in candidates:
        blocker = None
        for exp in cand["exposures"]:
            owners = held.get(exp, [])
            if len(owners) >= max_per_exposure:
                blocker = owners[0]
                break
        if blocker is not None:
            skipped.append({"symbol": cand["symbol"], "reason": "corrélée à %s" % blocker})
            continue
        if len(retained) >= max_shown:
            skipped.append({"symbol": cand["symbol"],
                            "reason": "au-delà des %d idées affichées" % max_shown})
            continue
        retained.append(cand)
        for exp in cand["exposures"]:
            held.setdefault(exp, []).append(cand["symbol"])
    return retained, skipped


def build_trade_ideas(analyses, config):
    """The `trade_ideas` object of briefing.json (spec 4.5)."""
    capital = config["account"]["capital"]
    per_trade_pct = config["risk"]["per_trade_pct"]
    max_total_pct = config["risk"]["max_total_pct"]
    max_shown = config["ideas"]["max_shown"]
    max_per_exposure = config["ideas"]["max_per_exposure"]
    budget = capital * per_trade_pct / 100.0

    prices = {a["symbol"]: a["last"] for a in analyses
              if strength.pair_currencies(a.get("symbol")) is not None}

    dropped = []
    candidates = []
    for a in analyses:
        side, triggers, reason = classify(a)
        if reason is not None:
            dropped.append({"symbol": a["symbol"], "reason": reason})
            continue
        if side is None:
            continue
        p = make_plan(a, side, config)
        if p is None:
            dropped.append({"symbol": a["symbol"], "reason": REASON_NO_ATR})
            continue
        points, why = score(a, side, triggers)
        candidates.append({"analysis": a, "symbol": a["symbol"], "side": side,
                           "triggers": triggers, "score": points, "why": why,
                           "plan": p, "exposures": exposures(a["symbol"], side)})

    candidates.sort(key=lambda c: (-c["score"], -len(c["triggers"]), c["symbol"]))
    retained, skipped = _diversify(candidates, max_shown, max_per_exposure)

    ideas = []
    total = 0.0
    for rank, c in enumerate(retained, start=1):
        a, p = c["analysis"], c["plan"]
        size = sizing.size_idea(c["symbol"], p["reference_price"], p["stop"], prices, config)
        if size["status"] == "ok":
            total += size["risk_usd"]
        elif size["status"] == "to_confirm":
            total += budget
        ideas.append({
            "rank": rank,
            "symbol": c["symbol"],
            "name": a.get("name"),
            "side": c["side"],
            "score": c["score"],
            "setups": _all_tags(a),
            "trend": a.get("trend"),
            "reference_price": p["reference_price"],
            "stop": p["stop"],
            "target": p["target"],
            "rr": p["rr"],
            "atr": p["atr"],
            "size": size,
            "why": c["why"],
        })

    total_pct = total / capital * 100.0
    return {
        "reference": "last_close",
        "account": {"currency": config["account"]["currency"], "capital": capital,
                    "risk_per_trade_usd": round(budget, 2),
                    "leverage_max": config["leverage_max"]},
        "ideas": ideas,
        "skipped": dropped + skipped,
        "total_risk_usd": round(total, 2),
        "total_risk_pct": round(total_pct, 2),
        "max_total_pct": max_total_pct,
        "over_cap": total_pct > max_total_pct,
    }
