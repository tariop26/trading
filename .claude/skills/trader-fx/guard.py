"""Risk guard of the FundedNext challenge: the day's estimated loss and the account floor.

Standard library only, pure functions. The alert server calls `evaluate` every run with the open
positions of the sheet, their Yahoo prices and the account figures, and sends what is new.

Thresholds (all read from the sheet, tab "Positions ouvertes", column M):
- day loss (closed today + floating) at or below -warn_loss       -> "alerte"
- day loss at or below -internal_stop                             -> "stop interne"
- day loss at or below -70 % of the FundedNext daily limit        -> "danger FundedNext (jour)"
- closed balance + floating at or below floor + 20 % of the room  -> "danger FundedNext (plancher)"
- open risk (loss at the stops) above open_risk_max               -> "risque ouvert"

Each threshold is sent once per UTC day (key "guard|<kind>|<day>" in the state). When one run
crosses several day-loss thresholds at once, only the most severe message is sent and the lower
ones are marked as sent. Never the words of an order, never advice: the plan's own rule is quoted.
"""
import positions as pos

FN_DAILY_SHARE = 0.7        # warn at 70 % of the FundedNext daily limit
FLOOR_ROOM_SHARE = 0.2      # warn when 20 % of the room above the floor is left

# day-loss thresholds, least to most severe
DAY_KINDS = ("alerte", "stop", "fn_jour")
NOTE = "Estimation sur prix Yahoo retardés, écart CFD corrigé à l'ouverture. L'équité exacte est dans MT5."


def key(kind, day):
    return "guard|%s|%s" % (kind, day)


def _usd(x):
    """-1234.5 -> '-1 235 $' (sign kept, thin layout readable on a phone)."""
    return ("%s%s $" % ("-" if x < 0 else "", "{:,.0f}".format(abs(x)).replace(",", " ")))


def measure(positions, prices, offsets):
    """-> {"floating", "lines", "missing", "open_risk"} for the open positions.

    `prices` maps a Yahoo symbol to its last price (None when unknown). A position without price
    is counted in `missing` and left out of the floating total."""
    floating, lines, missing, risk = 0.0, [], [], 0.0
    for p in positions:
        risk += pos.risk_usd(p)
        price = prices.get(p["symbol"])
        if price is None:
            missing.append(p["asset"])
            continue
        value = pos.floating_usd(p, price, offsets.get(p["id"]))
        floating += value
        lines.append("%s %s %s" % (p["asset"], p["side"], _usd(value)))
    return {"floating": floating, "lines": lines, "missing": missing, "open_risk": risk}


def _day_thresholds(params):
    out = []
    if params.get("warn_loss"):
        out.append(("alerte", params["warn_loss"]))
    if params.get("internal_stop"):
        out.append(("stop", params["internal_stop"]))
    if params.get("fn_daily"):
        out.append(("fn_jour", FN_DAILY_SHARE * params["fn_daily"]))
    return out


def _headline(kind, limit, params):
    if kind == "alerte":
        return ("Seuil d'alerte franchi (%s). Stop interne à %s : à ce niveau, ton plan dit de "
                "tout fermer et d'arrêter la journée." % (
                    _usd(-limit), _usd(-params.get("internal_stop", 0))))
    if kind == "stop":
        return ("STOP INTERNE ATTEINT (%s). Ton plan : tout fermer, plus aucun trade "
                "aujourd'hui." % _usd(-limit))
    return ("DANGER FUNDEDNEXT : %s, soit 70 %% de la perte journalière autorisée (%s). "
            "Au-delà de %s, le compte est perdu." % (
                _usd(-limit), _usd(-params["fn_daily"]), _usd(-params["fn_daily"])))


def evaluate(positions, params, prices, offsets, state, day):
    """-> (messages, summary). `messages` is a list of (text, [keys to mark once sent]) in
    sending order; `state["guard_sent"]` holds the keys already sent. `summary` is a log line."""
    sent = set(state.get("guard_sent", []))
    m = measure(positions, prices, offsets)
    realized = params.get("realized_today", 0.0)
    day_result = realized + m["floating"]
    partial = (" Estimation partielle : pas de prix pour %s." % ", ".join(m["missing"])
               if m["missing"] else "")
    detail = ("Résultat du jour estimé %s (clos %s, latent %s)." % (
        _usd(day_result), _usd(realized), _usd(m["floating"])))
    body = ([detail] + (["Positions : " + " · ".join(m["lines"])] if m["lines"] else [])
            + ([partial.strip()] if partial else []) + [NOTE])
    messages = []

    crossed = [(k, lim) for k, lim in _day_thresholds(params) if day_result <= -lim]
    fresh = [(k, lim) for k, lim in crossed if key(k, day) not in sent]
    if fresh:
        worst = max(crossed, key=lambda c: DAY_KINDS.index(c[0]))
        if key(worst[0], day) not in sent:
            text = "\n".join(["Garde-fou FundedNext. " + _headline(worst[0], worst[1], params)]
                             + body)
            messages.append((text, [key(k, day) for k, _ in crossed]))

    if params.get("floor") and params.get("closed_balance") and params.get("capital"):
        equity = params["closed_balance"] + m["floating"]
        room = params["capital"] - params["floor"]
        trigger = params["floor"] + FLOOR_ROOM_SHARE * room
        if equity <= trigger and key("plancher", day) not in sent:
            text = "\n".join([
                "Garde-fou FundedNext. DANGER PLANCHER : équité estimée %s, plancher de perte "
                "max à %s (marge %s). Le plancher touché, latent compris, le compte est perdu." % (
                    _usd(equity), _usd(params["floor"]), _usd(equity - params["floor"]))] + body)
            messages.append((text, [key("plancher", day)]))

    limit = params.get("open_risk_max")
    if limit and m["open_risk"] > limit and key("risque", day) not in sent:
        messages.append(("\n".join([
            "Garde-fou FundedNext. Risque ouvert %s aux stops, au-dessus du plafond de %s du "
            "plan. Aucun nouveau trade tant qu'il n'est pas revenu sous le plafond." % (
                _usd(m["open_risk"]), _usd(limit)),
            "Positions ouvertes : %d." % len(positions)]), [key("risque", day)]))

    summary = "garde-fou : %d position(s), jour %s, latent %s, risque ouvert %s%s" % (
        len(positions), _usd(day_result), _usd(m["floating"]), _usd(m["open_risk"]),
        " (sans prix : %s)" % ", ".join(m["missing"]) if m["missing"] else "")
    return messages, summary


def csv_down_message():
    return ("Garde-fou FundedNext inactif : l'onglet Positions ouvertes du classeur est illisible. "
            "Les stops suivis sont ceux de alerts.json. Vérifie la publication de l'onglet.")
