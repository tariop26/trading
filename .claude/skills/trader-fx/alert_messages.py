"""The Telegram messages of the alert server. Standard library only, pure functions.

French, factual, Paris time, plain text (no markup: a title with "<" or "&" goes out as is).
Never a result, a capital figure or an account id: the server does not know them. Never the words
achat, acheter, vente, vendre, buy, sell, nor any advice: an idea is a mechanical plan to check.
"""
from datetime import datetime, timezone

import plan
import sessions
import strength

TELEGRAM_LIMIT = 4096
CLIP = 300                      # free text (names, titles, rules) is cut here, far under the limit
DISCLAIMER = "Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé."


def _clip(text, limit=CLIP):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def pair_label(symbol):
    pair = strength.pair_currencies(symbol)
    return "%s/%s" % pair if pair else str(symbol)


def _price(symbol, decimals, value):
    if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
        decimals = plan.price_decimals(symbol, value)
    return "%.*f" % (decimals, value)


def _size_line(idea, account):
    size = idea.get("size") if isinstance(idea.get("size"), dict) else {}
    status = size.get("status")
    if status == "too_wide":
        return "Stop trop large pour le risque fixé."
    lots, contract = size.get("lots"), size.get("size")
    has_size = isinstance(lots, (int, float)) or isinstance(contract, (int, float))
    if status != "ok" or not has_size or not isinstance(size.get("risk_usd"), (int, float)):
        return "Taille à confirmer chez le courtier."     # never a figure we do not have
    taille = "%g %s" % (lots, "lots" if lots >= 2 else "lot") if isinstance(lots, (int, float)) \
        else "%g" % contract
    capital, risk = account.get("capital"), account.get("risk_per_trade_usd")
    pct = " (%g %% du capital)" % (risk / capital * 100) if capital and risk else ""
    return "Taille %s, risque %.2f USD%s." % (taille, size["risk_usd"], pct)


def idea_message(idea, account, waiting=0):
    sym = idea["symbol"]
    dec = idea.get("decimals")
    name = _clip(idea.get("name") or pair_label(sym))
    lines = [
        "Idée de trade, en formation, non confirmée à la clôture : %s %s." % (name, idea["side"]),
        "Entrée %s, stop %s, cible %s (1:%g)." % (
            _price(sym, dec, idea["reference_price"]), _price(sym, dec, idea["stop"]),
            _price(sym, dec, idea["target"]), idea["rr"]),
        _size_line(idea, account),
        "Règles : %s." % (_clip(", ".join(idea.get("setups") or []) or "aucune")),
    ]
    if account.get("source") == "default":
        lines.append("Taille calculée sur le capital par défaut.")
    lines.append(DISCLAIMER)
    if waiting > 0:
        lines.append("1 autre idée en attente." if waiting == 1 else "%d autres idées en attente." % waiting)
    return "\n".join(lines)


def _paris_time(iso):
    """HH:MM in Paris of an ISO string (naive = UTC), or None when it is missing or unreadable."""
    try:
        moment = datetime.fromisoformat(iso)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(sessions.PARIS).strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return None


def signal_message(candidate, account, previous=None):
    """An intraday signal: a mechanical plan on a 15 min bar, not confirmed by the broker."""
    sym = candidate["symbol"]
    plan_ = candidate["plan"]
    dec = plan_.get("decimals")
    name = _clip(candidate.get("display_name") or pair_label(sym))
    detail = candidate.get("detail")
    families = []
    for family in candidate.get("families") or []:
        families.append("%s (%s)" % (family, _clip(detail)) if family == candidate.get("primary") and detail
                        else str(family))
    bar = datetime.fromtimestamp(candidate["bar_ts"], sessions.PARIS).strftime("%H:%M")
    lines = [
        "Signal en séance%s, non confirmé par le courtier : %s %s." % (
            " renforcé" if previous else "", name, candidate["side"]),
        "Signaux : %s. Barre 15 min de %s Paris." % (", ".join(families) or "aucun", bar),
        "Entrée %s (zone valable jusqu'à %s), stop %s, cible %s (1:%g)." % (
            _price(sym, dec, plan_["reference_price"]), _price(sym, dec, plan_["limit_price"]),
            _price(sym, dec, plan_["stop"]), _price(sym, dec, plan_["target"]), plan_["rr"]),
        _size_line({"size": candidate.get("size")}, account),
    ]
    if account.get("source") == "default":
        lines.append("Taille calculée sur le capital par défaut.")
    if previous:
        sent = _paris_time(previous.get("sent_iso"))
        lines.append("Déjà alerté%s : %s." % (
            " à %s Paris" % sent if sent else "",
            _clip(", ".join(previous.get("families") or []) or "aucun")))
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def cap_message(max_per_day):
    return ("Plafond de %d alertes de signal atteint pour aujourd'hui : "
            "les suivantes ne sont pas envoyées." % int(max_per_day))


def touch_message(hit):
    rule = hit["rule"]
    sym = rule["symbol"]
    when = datetime.fromisoformat(hit["bar_time"]).astimezone(sessions.PARIS).strftime("%H:%M")
    dec = rule.get("decimals")
    return "\n".join([
        "%s touché%s : %s %s, trade %s." % (
            "Stop" if rule["type"] == "stop" else "Cible", "" if rule["type"] == "stop" else "e",
            pair_label(sym), rule["side"], rule["trade_id"]),
        "Niveau %s franchi à %s (%s de la barre 5 min : %s)." % (
            _price(sym, dec, rule["level"]), when, hit["extreme_kind"],
            _price(sym, dec, hit["extreme"])),
        "Vérifiez la position chez le courtier."])


def event_message(item):
    event = item["event"]
    return "\n".join([
        "Annonce à fort impact dans %d min : %s Paris, %s, %s." % (
            item["minutes"], event["time_paris"], event["currency"], _clip(event["title"])),
        "Vos trades concernés : %s." % ", ".join(pair_label(s) for s in item["symbols"])])


def down_message():
    return "Impossible de vérifier vos stops : données Yahoo indisponibles."
