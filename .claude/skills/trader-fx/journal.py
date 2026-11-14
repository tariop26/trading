"""Trading journal: the trades the user really took. Standard library only.

The functions of this module work on the journal dictionary (`{"v": 1, "trades": [...]}`) and
never touch the disk except `load_journal` and `save_journal`. A function that raises leaves the
journal exactly as it was: every check runs before the first change. Messages of `JournalError`
are one French line, ready to print. Times are stored in UTC (ISO 8601); the callers pass aware
datetimes.
"""
import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import config as fxconfig
import jstats
import page
import plan
import sessions
import sizing
import strength

VERSION = 1
SIDES = ("haussier", "baissier")
REASONS = ("stop", "cible", "manuel")


class JournalError(Exception):
    """A one-line French message explaining why the journal was not changed."""


def empty_journal():
    return {"v": VERSION, "trades": []}


# ---------------------------------------------------------------- storage

def load_journal(path):
    """The journal stored at `path`; an empty one when the file does not exist."""
    if not os.path.exists(path):
        return empty_journal()
    try:
        with open(path, encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, UnicodeDecodeError, RecursionError):
        raise JournalError("Journal illisible : %s." % path)
    except ValueError:
        raise JournalError("Journal illisible : %s (JSON invalide)." % path)
    if not isinstance(doc, dict):
        raise JournalError("Journal illisible : %s (objet JSON attendu)." % path)
    if doc.get("v") != VERSION:
        raise JournalError("Journal d'une autre version : %s (version %s attendue)."
                           % (path, VERSION))
    if not isinstance(doc.get("trades"), list):
        raise JournalError("Journal illisible : %s (liste trades absente)." % path)
    return doc


def save_journal(path, journal):
    """Write the journal atomically: the old file is copied to `path + ".bak"`, the new content
    goes to a temporary file in the same folder and replaces the old one in one step. A failure
    leaves the old file untouched and no temporary file behind."""
    write_json_atomic(path, journal, backup=True)


def write_json_atomic(path, doc, backup=False):
    """`doc` as JSON at `path`, written to a temporary file then moved over the old one;
    with `backup` the previous file is first copied to `path + ".bak"`."""
    try:
        content = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    except (TypeError, ValueError):
        raise JournalError("Écriture impossible : %s." % path)
    write_text_atomic(path, content, backup=backup)


def write_text_atomic(path, content, backup=False):
    """`content` (text) at `path`, written to a temporary file in the same folder then moved
    over the old one: a failure leaves the old file untouched and no temporary file behind."""
    folder = os.path.dirname(os.path.abspath(path))
    tmp = None
    try:
        os.makedirs(folder, exist_ok=True)
        if backup and os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
        fd, tmp = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=folder)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    except OSError:
        raise JournalError("Écriture impossible : %s." % path)
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------- helpers

def _iso(when_utc):
    if not isinstance(when_utc, datetime) or when_utc.tzinfo is None \
            or when_utc.utcoffset() is None:
        raise ValueError("when_utc must be a timezone-aware datetime")
    return when_utc.astimezone(timezone.utc).isoformat()


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _positive(x):
    return _is_number(x) and x > 0


def _need_positive(value, what):
    if not _positive(value):
        raise JournalError("%s doit être un nombre positif." % what)
    return float(value)


def find_trade(journal, trade_id):
    for trade in journal["trades"]:
        if trade.get("id") == trade_id:
            return trade
    raise JournalError("Trade inconnu : %s." % trade_id)


def _require_open(trade):
    if trade["status"] != "open":
        raise JournalError("Trade déjà clôturé : %s." % trade["id"])


def new_trade_id(journal, symbol, when_utc):
    """`<UTC date>-<symbol without "=X">-<n>`, n counting the trades with the same prefix."""
    day = when_utc.astimezone(timezone.utc).date().isoformat()
    name = re.sub(r"[^A-Za-z0-9.\-]", "_", symbol[:-2] if symbol.endswith("=X") else symbol)
    prefix = "%s-%s-" % (day, name)
    taken = sum(1 for t in journal["trades"] if str(t.get("id", "")).startswith(prefix))
    return "%s%d" % (prefix, taken + 1)


# ---------------------------------------------------------------- operations

def open_trade(journal, *, symbol, name, side, price, when_utc, lots=None, size=None,
               stop=None, target=None, idea=None, risk_usd=None, prices=None, contracts=None):
    """Add an open trade to the journal and return it.

    A forex pair is entered in `lots` (1 lot = 100 000 units), any other instrument in `size`.
    With an `idea` (a copy of a briefing idea) the stop and the target default to the idea's,
    otherwise `stop` is required. The planned risk at the stop is `risk_usd` when given, else
    computed with `sizing.risk_at` (None when a conversion rate is missing).
    """
    when = _iso(when_utc)
    if side not in SIDES:
        raise JournalError("Sens inconnu : %s (haussier ou baissier)." % side)
    if not isinstance(symbol, str) or not symbol.strip():
        raise JournalError("Symbole manquant.")
    symbol = symbol.strip()
    price = _need_positive(price, "Le prix d'entrée")

    if strength.pair_currencies(symbol) is not None:
        if size is not None:
            raise JournalError("Une paire forex se saisit en lots, pas en taille.")
        lots = _need_positive(lots, "Les lots")
        units = int(round(lots * sizing.LOT_UNITS))
        if units < 1:
            raise JournalError("Les lots doivent faire au moins une unité.")
        entry_qty = {"lots": lots, "units": units, "size": None}
        qty = units
    else:
        if lots is not None:
            raise JournalError("Cet instrument se saisit en taille de contrat (--size), pas en lots.")
        size = _need_positive(size, "La taille")
        entry_qty = {"lots": None, "units": None, "size": size}
        qty = size

    if idea is not None:
        stop = idea.get("stop") if stop is None else stop
        target = idea.get("target") if target is None else target
    if stop is None:
        raise JournalError("Stop obligatoire pour un trade hors plan (--stop).")
    stop = _need_positive(stop, "Le stop")
    if target is not None:
        target = _need_positive(target, "La cible")
    wrong = (stop >= price or (target is not None and target <= price)) if side == "haussier" \
        else (stop <= price or (target is not None and target >= price))
    if wrong:
        raise JournalError("Stop ou cible du mauvais côté du prix d'entrée pour un trade %s." % side)

    if risk_usd is not None:
        risk_usd = sizing.usd_cents(_need_positive(risk_usd, "Le risque prévu"))
    else:
        risk_usd = sizing.risk_at(symbol, price, stop, qty, prices or {}, contracts or {})

    trade = {
        "id": new_trade_id(journal, symbol, when_utc),
        "symbol": symbol,
        "name": name or symbol,
        "side": side,
        "status": "open",
        "source": "idee" if idea is not None else "hors_plan",
        "idea": copy.deepcopy(idea) if idea is not None else None,
        "entry": dict({"time": when, "price": price}, **entry_qty),
        "initial_stop": stop,
        "initial_target": target,
        "stop": stop,
        "target": target,
        "risk_usd": risk_usd,
        "exit": None,
        "result": None,
        "tags": [],
        "note": "",
        "history": [{"time": when, "event": "ouverture",
                     "detail": "%s à %s, stop %s" % (side, price, stop)}],
    }
    journal["trades"].append(trade)
    return trade


def amend_trade(journal, trade_id, *, when_utc, stop=None, target=None):
    """Move the stop and/or the target of an open trade. The initial stop and `risk_usd` never
    change, so the R keeps its unit. Moving the stop away from the profit side adds the tag
    `stop_deplace`."""
    when = _iso(when_utc)
    trade = find_trade(journal, trade_id)
    _require_open(trade)
    if stop is None and target is None:
        raise JournalError("Rien à modifier : donne --stop ou --target.")
    side, entry = trade["side"], trade["entry"]["price"]
    new_stop = trade["stop"] if stop is None else _need_positive(stop, "Le stop")
    new_target = trade["target"] if target is None else _need_positive(target, "La cible")
    if target is not None and (new_target <= entry if side == "haussier" else new_target >= entry):
        raise JournalError("La cible doit être du côté du gain par rapport à l'entrée.")
    if new_target is not None and (new_stop >= new_target if side == "haussier"
                                   else new_stop <= new_target):
        raise JournalError("Le stop doit rester du côté de la perte par rapport à la cible.")

    events, add_tag = [], False
    if new_stop != trade["stop"]:
        farther = new_stop < trade["stop"] if side == "haussier" else new_stop > trade["stop"]
        events.append({"time": when, "event": "stop_deplace",
                       "detail": "stop %s → %s" % (trade["stop"], new_stop)})
        add_tag = farther
    if new_target != trade["target"]:
        events.append({"time": when, "event": "cible_deplacee",
                       "detail": "cible %s → %s" % (trade["target"], new_target)})
    if not events:
        raise JournalError("Rien à modifier : mêmes niveaux.")
    trade["stop"], trade["target"] = new_stop, new_target
    trade["history"].extend(events)
    if add_tag and "stop_deplace" not in trade["tags"]:
        trade["tags"].append("stop_deplace")
    return trade


def close_trade(journal, trade_id, *, price, when_utc, reason="manuel", pnl_usd=None,
                prices=None, contracts=None, tags=(), note=""):
    """Close an open trade. The result is the broker's `pnl_usd` when given ("courtier"), else
    estimated with `sizing.pnl_at` ("estime", before fees, swap and slippage). R is the result
    divided by the planned risk of the opening, None when that risk is unknown."""
    when = _iso(when_utc)
    trade = find_trade(journal, trade_id)
    _require_open(trade)
    price = _need_positive(price, "Le prix de sortie")
    if reason not in REASONS:
        raise JournalError("Raison inconnue : %s (stop, cible ou manuel)." % reason)
    if datetime.fromisoformat(when) < datetime.fromisoformat(trade["entry"]["time"]):
        raise JournalError("La sortie ne peut pas précéder l'entrée.")

    if pnl_usd is not None:
        if not _is_number(pnl_usd):
            raise JournalError("Le résultat du courtier doit être un nombre en USD.")
        value, source = sizing.usd_cents(pnl_usd) + 0.0, "courtier"
    else:
        entry = trade["entry"]
        qty = entry["units"] if entry["units"] is not None else entry["size"]
        estimate = sizing.pnl_at(trade["symbol"], trade["side"], entry["price"], price, qty,
                                 prices or {}, contracts or {})
        if estimate is None:
            raise JournalError("Résultat inestimable : donne --pnl ou --quote-usd-rate.")
        value, source = estimate + 0.0, "estime"
    risk = trade["risk_usd"]
    r = round(value / risk, 2) + 0.0 if risk else None

    trade["status"] = "closed"
    trade["exit"] = {"time": when, "price": price, "reason": reason}
    trade["result"] = {"pnl_usd": value, "r": r, "source": source}
    for tag in tags:
        tag = str(tag).strip()
        if tag and tag not in trade["tags"]:
            trade["tags"].append(tag)
    if note:
        trade["note"] = str(note)
    trade["history"].append({"time": when, "event": "cloture",
                             "detail": "à %s (%s)" % (price, reason)})
    return trade


# ---------------------------------------------------------------- alerts file

def build_alerts(journal, now_utc):
    """The stop and target rules of the open trades, for the alert server. Levels only: no
    result, capital, size or risk ever goes into this file."""
    rules = []
    for t in journal["trades"]:
        if t.get("status") != "open":
            continue
        for kind, level in (("stop", t["stop"]), ("cible", t.get("target"))):
            if level is None:
                continue
            rules.append({"id": "%s-%s" % (t["id"], kind), "trade_id": t["id"],
                          "symbol": t["symbol"], "type": kind, "side": t["side"],
                          "level": level, "decimals": plan.price_decimals(t["symbol"], level)})
    return {"v": 1, "updated": _iso(now_utc), "rules": rules}


# ---------------------------------------------------------------- command line

DEFAULT_JOURNAL = "trader/fx/journal.json"
DEFAULT_CONFIG = "trader/fx/config.json"
DEFAULT_BRIEFING = "trader/fx/briefing.json"
DEFAULT_ALERTS = "trader/fx/alerts.json"
DEFAULT_PAGE = "trader/fx/journal.html"
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal_template.html")


class _Parser(argparse.ArgumentParser):
    """An argument error is one line in French, like every other error of the journal."""

    def error(self, message):
        raise JournalError("Arguments invalides : %s." % " ".join(message.split()))


def build_parser():
    common = _Parser(add_help=False)
    common.add_argument("--journal", default=DEFAULT_JOURNAL, help="fichier journal.json")
    common.add_argument("--config", default=DEFAULT_CONFIG, help="fichier config.json")
    p = _Parser(prog="journal.py", description="journal de trading de trader-fx")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

    o = sub.add_parser("open", parents=[common], help="ouvre un trade")
    o.add_argument("--symbol", required=True)
    o.add_argument("--side", required=True, choices=SIDES)
    o.add_argument("--price", required=True, type=float, help="prix d'entrée réel")
    o.add_argument("--lots", type=float, help="paire forex : lots de 100 000 unités")
    o.add_argument("--size", type=float, help="autre instrument : taille de contrat")
    o.add_argument("--stop", type=float)
    o.add_argument("--target", type=float)
    o.add_argument("--time", help='heure de Paris "AAAA-MM-JJ HH:MM" (défaut : maintenant)')
    o.add_argument("--risk-usd", type=float, help="risque prévu au stop, s'il est connu")
    o.add_argument("--quote-usd-rate", type=float,
                   help="valeur en USD d'une unité de la devise de cotation (paire croisée)")
    o.add_argument("--briefing", default=DEFAULT_BRIEFING, help="briefing.json des idées")

    a = sub.add_parser("amend", parents=[common], help="déplace le stop ou la cible")
    a.add_argument("id")
    a.add_argument("--stop", type=float)
    a.add_argument("--target", type=float)
    a.add_argument("--time")

    c = sub.add_parser("close", parents=[common], help="clôture un trade")
    c.add_argument("id")
    c.add_argument("--price", required=True, type=float, help="prix de sortie réel")
    c.add_argument("--reason", default="manuel", choices=REASONS)
    c.add_argument("--pnl", type=float, help="résultat du courtier en USD (recommandé)")
    c.add_argument("--tags", help="étiquettes d'erreur séparées par des virgules")
    c.add_argument("--note")
    c.add_argument("--time")
    c.add_argument("--quote-usd-rate", type=float)

    ls = sub.add_parser("list", parents=[common], help="liste les trades")
    ls.add_argument("--open", action="store_true", dest="only_open")
    ls.add_argument("--closed", action="store_true", dest="only_closed")

    st = sub.add_parser("stats", parents=[common], help="statistiques des trades clôturés")
    st.add_argument("--json", action="store_true", help="l'objet stats en JSON")

    al = sub.add_parser("alerts", parents=[common], help="écrit les règles de stop et de cible")
    al.add_argument("--out", default=DEFAULT_ALERTS)

    pg = sub.add_parser("page", parents=[common], help="écrit la page « Journal de trading »")
    pg.add_argument("--out", default=DEFAULT_PAGE)
    return p


def _parse_time(text, default):
    if text is None:
        return default
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(
            tzinfo=sessions.PARIS).astimezone(timezone.utc)
    except ValueError:
        raise JournalError('--time doit être au format "AAAA-MM-JJ HH:MM" (heure de Paris).')


def _load_config(args):
    if args.config != DEFAULT_CONFIG and not os.path.exists(args.config):
        raise JournalError("Fichier de configuration introuvable : %s." % args.config)
    return fxconfig.load_config(args.config)


def _default_fetch_rate(yahoo_symbol):
    """Latest daily close of a Yahoo symbol, or None (any failure)."""
    try:
        import data
        series, _ = data.fetch_bars([yahoo_symbol], "1d", "5d", cache_dir=None, ttl_s=0,
                                    use_cache=False)
        s = series.get(yahoo_symbol)
        return s.bars[-1][4] if s is not None and s.bars else None
    except Exception:  # noqa: BLE001 - a missing rate only leaves the risk unknown
        return None


def _conversion_prices(symbol, quote_usd_rate, fetch_rate):
    """The `prices` dict for risk_at / pnl_at. Only a cross pair needs a rate (the value in USD
    of its quote currency): the given `quote_usd_rate`, else one request through `fetch_rate`;
    when neither gives one the dict stays empty and the amount comes out unknown."""
    pair = strength.pair_currencies(symbol)
    if pair is None or pair[0] == "USD" or pair[1] == "USD":
        return {}
    quote = pair[1]
    if quote_usd_rate is not None:
        _need_positive(quote_usd_rate, "--quote-usd-rate")
        return {"%sUSD=X" % quote: float(quote_usd_rate)}
    rate = fetch_rate("USD%s=X" % quote)
    return {"USD%s=X" % quote: float(rate)} if _positive(rate) else {}


def _idea_from_briefing(path, symbol, side):
    """(snapshot of the briefing idea with the same symbol and side, its name) or (None, None)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, None
    ideas = ((doc.get("trade_ideas") or {}).get("ideas")) if isinstance(doc, dict) else None
    for idea in ideas if isinstance(ideas, list) else []:
        if isinstance(idea, dict) and idea.get("symbol") == symbol and idea.get("side") == side:
            snap = {k: idea.get(k) for k in ("rank", "score", "setups", "reference_price", "stop",
                                             "target", "rr", "last_bar_date", "decimals", "size")}
            snap["as_of"] = (doc.get("as_of") or {}).get("iso")
            return snap, idea.get("name")
    return None, None


def _level(symbol, x):
    """A price with the decimals of its grid; "n/a" when it is missing."""
    if not _is_number(x):
        return "n/a"
    return "%.*f" % (plan.price_decimals(symbol, x), x)


def _result_text(trade):
    res = trade["result"]
    r = "R %+.2f" % res["r"] if res["r"] is not None else "R non calculable"
    source = "courtier" if res["source"] == "courtier" else "estimé, hors frais"
    return "résultat %+.2f USD (%s), %s" % (res["pnl_usd"], source, r)


def cmd_open(args, deps):
    when = _parse_time(args.time, deps["now"]())
    symbol = (args.symbol or "").strip().upper()
    doc = load_journal(args.journal)
    cfg = _load_config(args)
    idea, idea_name = _idea_from_briefing(args.briefing, symbol, args.side)
    pair = strength.pair_currencies(symbol)
    name = idea_name or ("%s/%s" % pair if pair else symbol)
    prices = {} if args.risk_usd is not None else _conversion_prices(
        symbol, args.quote_usd_rate, deps["fetch_rate"])
    trade = open_trade(doc, symbol=symbol, name=name, side=args.side, price=args.price,
                       when_utc=when, lots=args.lots, size=args.size, stop=args.stop,
                       target=args.target, idea=idea, risk_usd=args.risk_usd, prices=prices,
                       contracts=cfg["contracts"])
    save_journal(args.journal, doc)
    risk = ("risque prévu %.2f USD" % trade["risk_usd"] if trade["risk_usd"] is not None
            else "risque prévu inconnu (donne --quote-usd-rate ou --risk-usd)")
    target = _level(symbol, trade["target"]) if trade["target"] is not None else "aucune"
    print("Trade ouvert : %s, %s %s à %s, stop %s, cible %s, %s (%s)."
          % (trade["id"], symbol, args.side, _level(symbol, args.price), _level(symbol, trade["stop"]),
             target, risk, "idée du briefing" if idea else "hors plan"))
    return 0


def cmd_amend(args, deps):
    when = _parse_time(args.time, deps["now"]())
    doc = load_journal(args.journal)
    trade = find_trade(doc, args.id)
    tagged = "stop_deplace" in trade["tags"]
    amend_trade(doc, args.id, when_utc=when, stop=args.stop, target=args.target)
    save_journal(args.journal, doc)
    sym = trade["symbol"]
    extra = " Étiquette stop_deplace ajoutée." if "stop_deplace" in trade["tags"] and not tagged else ""
    target = _level(sym, trade["target"]) if trade["target"] is not None else "aucune"
    print("Trade modifié : %s, stop %s, cible %s.%s" % (trade["id"], _level(sym, trade["stop"]),
                                                        target, extra))
    return 0


def cmd_close(args, deps):
    when = _parse_time(args.time, deps["now"]())
    doc = load_journal(args.journal)
    cfg = _load_config(args)
    trade = find_trade(doc, args.id)
    prices = {} if args.pnl is not None else _conversion_prices(
        trade["symbol"], args.quote_usd_rate, deps["fetch_rate"])
    tags = [x.strip() for x in (args.tags or "").split(",") if x.strip()]
    close_trade(doc, args.id, price=args.price, when_utc=when, reason=args.reason,
                pnl_usd=args.pnl, prices=prices, contracts=cfg["contracts"], tags=tags,
                note=args.note or "")
    save_journal(args.journal, doc)
    print("Trade clôturé : %s, %s." % (trade["id"], _result_text(trade)))
    return 0


def cmd_list(args, deps):
    doc = load_journal(args.journal)
    only_open, only_closed = args.only_open, args.only_closed
    for t in doc["trades"]:
        if only_open != only_closed and (t["status"] == "open") != only_open:
            continue
        sym = t["symbol"]
        target = _level(sym, t.get("target")) if t.get("target") is not None else "aucune"
        line = "%s  %s  %s %s  entrée %s  stop %s  cible %s" % (
            t["id"], "ouvert" if t["status"] == "open" else "clôturé", sym, t["side"],
            _level(sym, (t.get("entry") or {}).get("price")), _level(sym, t.get("stop")), target)
        if t.get("result") is not None:
            line += "  " + _result_text(t)
        print(line)
    return 0


def _fmt(x, spec="%.2f"):
    return "n/a" if x is None else spec % x


def _group_line(g):
    rate = "n/a" if g["win_rate"] is None else "%.1f %%" % (g["win_rate"] * 100)
    return "  %s : n=%d, taux positif %s, R moyen %s, R total %+.2f, résultat %+.2f USD%s" % (
        g["key"], g["n"], rate, _fmt(g["avg_r"]), g["total_r"], g["pnl_usd"],
        ", peu de trades" if g["few"] else "")


def render_stats(stats):
    lines = ["Journal : %d trades clôturés, %d ouverts" % (stats["n_closed"], stats["n_open"])]
    if stats["sample_warning"]:
        lines.append("Attention : %s (moins de %d trades clôturés)."
                     % (stats["sample_warning"], jstats.MIN_TRADES))
    if stats["n_closed"] == 0:
        lines.append("Aucun trade clôturé pour l'instant.")
        return "\n".join(lines)
    o = stats["overall"]
    lines.append("Global : n=%d, positifs %d, négatifs %d, à l'équilibre %d, taux positif %s, "
                 "R moyen %s, R total %+.2f, résultat %+.2f USD%s" % (
                     o["n"], o["positive"], o["negative"], o["flat"],
                     "n/a" if o["win_rate"] is None else "%.1f %%" % (o["win_rate"] * 100),
                     _fmt(o["expectancy_r"]), o["total_r"], o["pnl_usd"],
                     " (dont %d estimé(s), hors frais)" % o["n_estimated"] if o["n_estimated"] else ""))
    for title, key in (("Par règle (un trade compte dans chacune de ses règles)", "by_rule"),
                       ("Par sens", "by_side"), ("Par paire", "by_symbol"),
                       ("Par session d'entrée", "by_session"), ("Par jour de la semaine (Paris)", "by_weekday")):
        lines.append(title + " :")
        lines.extend(_group_line(g) for g in stats[key])
    if stats["errors"]:
        lines.append("Erreurs :")
        lines.extend("  %s : n=%d, R moyen %s, R total %+.2f" % (e["tag"], e["n"], _fmt(e["avg_r"]),
                                                              e["total_r"]) for e in stats["errors"])
    q = stats["equity"]
    lines.append("Capital : départ %.2f USD, fin %.2f USD, pire drawdown %.2f USD (%.2f %%), "
                 "plafond de risque cumulé %s %%" % (q["start"], q["end"], q["max_drawdown_usd"],
                                                    q["max_drawdown_pct"], q["cap_pct"]))
    if q["worst_streak"]["n"]:
        lines.append("Pire série négative : %d trade(s), R %+.2f" % (q["worst_streak"]["n"],
                                                                     q["worst_streak"]["r"]))
    return "\n".join(lines)


def cmd_stats(args, deps):
    doc = load_journal(args.journal)
    cfg = _load_config(args)
    stats = jstats.compute_stats(doc, capital=float(cfg["account"]["capital"]),
                                 cap_pct=float(cfg["risk"]["max_total_pct"]))
    print(json.dumps(stats, ensure_ascii=False, indent=2) if args.json else render_stats(stats))
    return 0


def cmd_alerts(args, deps):
    doc = load_journal(args.journal)
    alerts = build_alerts(doc, deps["now"]())
    write_json_atomic(args.out, alerts)
    trades = len({r["trade_id"] for r in alerts["rules"]})
    print("Alertes écrites : %d règle(s) pour %d trade(s) ouvert(s) → %s."
          % (len(alerts["rules"]), trades, args.out))
    return 0


def cmd_page(args, deps):
    doc = load_journal(args.journal)
    cfg = _load_config(args)
    now = deps["now"]()
    stats = jstats.compute_stats(doc, capital=float(cfg["account"]["capital"]),
                                 cap_pct=float(cfg["risk"]["max_total_pct"]))
    data = {"as_of": {"iso": _iso(now),
                      "paris": now.astimezone(sessions.PARIS).strftime("%Y-%m-%d %H:%M")},
            "journal": doc, "stats": stats}
    try:
        html = page.render_page(data, TEMPLATE, script_id="journal")
    except (OSError, ValueError):
        raise JournalError("Gabarit de la page introuvable ou invalide : %s." % TEMPLATE)
    write_text_atomic(args.out, html)
    print("Page écrite : %s (%d trade(s) clôturé(s), %d ouvert(s))."
          % (args.out, stats["n_closed"], stats["n_open"]))
    return 0


def _utf8_streams():
    """Piped output on Windows defaults to the ANSI code page: force UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


COMMANDS = {"open": cmd_open, "amend": cmd_amend, "close": cmd_close, "list": cmd_list,
            "stats": cmd_stats, "alerts": cmd_alerts, "page": cmd_page}


def main(argv=None, deps=None):
    _utf8_streams()
    deps = dict(deps or {})
    deps.setdefault("now", lambda: datetime.now(timezone.utc))
    deps.setdefault("fetch_rate", _default_fetch_rate)
    try:
        args = build_parser().parse_args(argv)
        return COMMANDS[args.cmd](args, deps)
    except (JournalError, fxconfig.ConfigError) as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
