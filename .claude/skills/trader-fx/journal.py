"""Trading journal: the trades the user really took. Standard library only.

The functions of this module work on the journal dictionary (`{"v": 1, "trades": [...]}`) and
never touch the disk except `load_journal` and `save_journal`. A function that raises leaves the
journal exactly as it was: every check runs before the first change. Messages of `JournalError`
are one French line, ready to print. Times are stored in UTC (ISO 8601); the callers pass aware
datetimes.
"""
import copy
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone

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
    folder = os.path.dirname(os.path.abspath(path))
    tmp = None
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
        fd, tmp = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=folder)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(journal, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    except (OSError, TypeError, ValueError):
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
