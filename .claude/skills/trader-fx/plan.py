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
REASON_IMPOSSIBLE = "plan impossible : stop ou cible sous zéro"
REASON_NOISE = "ATR trop faible : stop dans le bruit ou l'écart de cotation"

# a stop closer than this percentage of the price is inside the noise / the spread
MIN_STOP_PCT = 0.15

MINUS = "−"

TRIGGER_LABELS = {
    "breakout_20d": "cassure du plus haut 20 j",
    "bull_flag": "drapeau haussier",
    "reclaim_ma20": "reprise de la moyenne 20 j",
    "oversold_bounce": "rebond depuis la survente",
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


def price_decimals(symbol, price):
    """Decimals of the price grid: forex 5 (3 on a JPY quote); any other instrument by
    magnitude: under 10 -> 4, under 100 -> 3, else 2. The tick is 10 ** -decimals."""
    pair = strength.pair_currencies(symbol)
    if pair is not None:
        return 3 if pair[1] == "JPY" else 5
    a = abs(price)
    if a < 10:
        return 4
    if a < 100:
        return 3
    return 2


def _round_dir(x, tick, decimals, direction):
    n = round(x / tick, 6)          # float noise before floor/ceil
    n = math.floor(n) if direction == "down" else math.ceil(n)
    return round(n * tick, decimals)


def make_plan(analysis, side, config):
    """{"reference_price","stop","target","rr","atr","decimals"} or None when the
    ATR or the price is unusable.

    The entry is the last close rounded to the NEAREST tick; the stop is computed from
    the unrounded last and rounded AWAY from the entry; the target is recomputed from
    the rounded distance and rounded TOWARD the entry. `rr` stays the nominal
    target_r. `config` is the validated configuration dict (its "plan" section).
    """
    last = analysis.get("last")
    atr_pct = analysis.get("atr_pct")
    if not _number(last) or last <= 0 or not _number(atr_pct) or atr_pct <= 0:
        return None
    plan_cfg = config.get("plan", config)
    mult = plan_cfg["stop_atr_mult"]
    target_r = plan_cfg["target_r"]

    atr = last * atr_pct / 100.0
    decimals = price_decimals(analysis.get("symbol"), last)
    tick = 10.0 ** -decimals
    entry = round(last, decimals)
    if side == LONG:
        stop = _round_dir(last - mult * atr, tick, decimals, "down")
        dist = round(abs(entry - stop), decimals)
        target = _round_dir(entry + target_r * dist, tick, decimals, "down")
    else:
        stop = _round_dir(last + mult * atr, tick, decimals, "up")
        dist = round(abs(entry - stop), decimals)
        target = _round_dir(entry - target_r * dist, tick, decimals, "up")
    return {
        "reference_price": entry,
        "stop": stop,
        "target": target,
        "rr": target_r,
        "atr": round(atr, 6),
        "decimals": decimals,
    }


def _sides_ok(side, p):
    """Strict order of the rounded plan, with positive stop and target."""
    entry, stop, target = p["reference_price"], p["stop"], p["target"]
    if stop <= 0 or target <= 0:
        return False
    if side == LONG:
        return stop < entry < target
    return target < entry < stop


def _diversify(candidates, max_shown, max_per_exposure):
    """Walk ranked candidates; return (retained, skipped, ties_at_cutoff).

    ties_at_cutoff counts the candidates dropped for the display limit whose score
    equals the score of the last retained idea."""
    retained = []
    skipped = []
    beyond = []     # dropped for the display limit, in rank order
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
                            "reason": "au-delà des %d idées affichées (score %s)"
                                      % (max_shown, cand["score"])})
            beyond.append(cand)
            continue
        retained.append(cand)
        for exp in cand["exposures"]:
            held.setdefault(exp, []).append(cand["symbol"])
    last_score = retained[-1]["score"] if retained else None
    ties = sum(1 for c in beyond if c["score"] == last_score)
    return retained, skipped, ties


def build_trade_ideas(analyses, config):
    """The `trade_ideas` object of briefing.json (spec 4.5)."""
    capital = config["account"]["capital"]
    per_trade_pct = config["risk"]["per_trade_pct"]
    max_total_pct = config["risk"]["max_total_pct"]
    max_shown = config["ideas"]["max_shown"]
    max_per_exposure = config["ideas"]["max_per_exposure"]
    budget = capital * per_trade_pct / 100.0

    prices = {a["symbol"]: a["last"] for a in analyses
              if strength.pair_currencies(a.get("symbol")) is not None
              and _number(a.get("last")) and a["last"] > 0}

    dropped = []
    candidates = []
    for a in analyses:
        side, triggers, reason = classify(a)
        if reason is not None:
            dropped.append({"symbol": a["symbol"], "reason": reason})
            continue
        if side is None:
            continue
        try:    # one symbol's arithmetic never kills the briefing
            p = make_plan(a, side, config)
            if p is None:
                dropped.append({"symbol": a["symbol"], "reason": REASON_NO_ATR})
                continue
            if not _sides_ok(side, p):
                dropped.append({"symbol": a["symbol"], "reason": REASON_IMPOSSIBLE})
                continue
            dist = abs(p["reference_price"] - p["stop"])
            if dist / p["reference_price"] * 100.0 < MIN_STOP_PCT:
                dropped.append({"symbol": a["symbol"], "reason": REASON_NOISE})
                continue
            points, why = score(a, side, triggers)
            size = sizing.size_idea(a["symbol"], p["reference_price"], p["stop"],
                                    prices, config)
        except ArithmeticError as e:
            dropped.append({"symbol": a["symbol"],
                            "reason": "calcul impossible (%s)" % type(e).__name__})
            continue
        candidates.append({"analysis": a, "symbol": a["symbol"], "side": side,
                           "triggers": triggers, "score": points, "why": why,
                           "plan": p, "size": size,
                           "exposures": exposures(a["symbol"], side)})

    candidates.sort(key=lambda c: (-c["score"], -len(c["triggers"]), c["symbol"]))
    retained, skipped, ties = _diversify(candidates, max_shown, max_per_exposure)

    ideas = []
    counted = []        # risk of each idea that counts toward the cap
    leverages = []
    for rank, c in enumerate(retained, start=1):
        a, p, size = c["analysis"], c["plan"], c["size"]
        if size["status"] == "ok":
            counted.append(size["risk_usd"])
            leverages.append(size["leverage"])
        elif size["status"] == "to_confirm":
            counted.append(budget)
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
            "decimals": p["decimals"],
            "size": size,
            "why": c["why"],
            "last_bar_date": a.get("last_bar_date"),
            "since_close": None,
        })

    total = math.fsum(counted)
    cap_cents = round(capital * max_total_pct / 100.0, 2)
    # largest k such that the k LARGEST counted risks fit in the cap (in cents);
    # fsum is order-independent, so k == len(counted) exactly when not over_cap
    within = 0
    ordered = sorted(counted, reverse=True)
    for k in range(1, len(ordered) + 1):
        if round(math.fsum(ordered[:k]), 2) <= cap_cents:
            within = k
        else:
            break
    total_pct = total / capital * 100.0
    return {
        "reference": "last_close",
        "account": {"currency": config["account"]["currency"], "capital": capital,
                    "risk_per_trade_usd": sizing.usd_cents(budget),
                    "leverage_max": config["leverage_max"]},
        "ideas": ideas,
        "skipped": dropped + skipped,
        "total_risk_usd": sizing.usd_cents(total),
        "total_risk_pct": round(total_pct, 2),
        "max_total_pct": max_total_pct,
        "over_cap": round(total, 2) > cap_cents,
        "max_ideas_within_cap": within,
        "ties_at_cutoff": ties,
        "total_leverage": round(math.fsum(leverages), 2),
    }
