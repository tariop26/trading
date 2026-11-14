"""Assembles briefing.json and the short terminal summary. Standard library only.

build_briefing() is pure: bars, a calendar and a clock go in, a plain dict comes
out. Nothing here reads the network, the disk or the real clock.
"""
from datetime import timezone
from decimal import Decimal

import config as fxconfig
import economic_calendar
import plan
import sessions
import signals
import strength

DISCLAIMER = ("Liste de graphiques qui ont matché une règle. Pas un conseil. "
              "Données Yahoo, retardées.")

MAJORS = ("EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X",
          "USDCAD=X", "NZDUSD=X")

MAX_LINES = 40
LIST_LIMIT = 10          # symbols named in one warning
CAL_LINES = 5            # events shown in the summary
WARN_LINES = 4           # warnings shown in the summary
LINE_CHARS = 150
IDEA_LINES = 8           # lines reserved for the trade ideas block
IDEA_ROWS = IDEA_LINES - 2   # idea lines that fit besides the header and the risk line

FAMILIES = (("forex", "Forex"), ("commodities", "Matières premières"),
            ("indices", "Indices"))


# ---------------------------------------------------------------- input

def read_list(path):
    """Lines 'SYMBOL|name' -> [(symbol, name)]. '#' comments and blank lines are
    skipped; the name is optional (the symbol is used when it is missing)."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            sym, _, name = line.partition("|")
            sym, name = sym.strip(), name.strip()
            if sym:
                out.append((sym, name or sym))
    return out


def alert_symbols(hits):
    """Symbols of the hits, then the 7 majors, without duplicates."""
    out = []
    for s in [h["symbol"] for h in hits] + list(MAJORS):
        if s not in out:
            out.append(s)
    return out


def analyze_universe(universe, daily, now_utc, errors=None):
    """[analysis] for every symbol of `universe` that has at least 30 complete
    sessions, in universe order. A symbol whose maths fail (a zero close, say) is
    skipped; when `errors` is a list, (symbol, error type name) is appended to it."""
    out = []
    for sym, name in universe:
        if sym in daily:
            try:
                a = signals.analyze(sym, name, daily[sym], now_utc)
            except ArithmeticError as e:
                if errors is not None:
                    errors.append((sym, type(e).__name__))
                continue
            if a is not None:
                out.append(a)
    return out


def family(symbol):
    if strength.pair_currencies(symbol) is not None:
        return "forex"
    if symbol.endswith("=F"):
        return "commodities"
    return "indices"


# ---------------------------------------------------------------- build

def has_setup(a):
    """True when the analysis matched a rule on either side (long or short)."""
    return bool(a["setups"] or a.get("setups_short"))


def _hit(a):
    out = {k: a[k] for k in ("symbol", "name", "last", "rsi", "atr_pct", "trend",
                             "setups", "last_bar_date")}
    out["setups_short"] = list(a.get("setups_short") or [])
    return out


def join_names(symbols):
    shown = ", ".join(symbols[:LIST_LIMIT])
    if len(symbols) > LIST_LIMIT:
        shown += " et %d autres" % (len(symbols) - LIST_LIMIT)
    return shown


def _hours(seconds):
    return "%.1f" % (seconds / 3600.0)


def build_briefing(universe, daily, failed, hourly, calendar, now_utc, extra_warnings=(),
                   config=None):
    """`config` is a validated configuration dict (see config.load_config); None
    means the defaults."""
    cfg = fxconfig.defaults() if config is None else config
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    now_utc = now_utc.astimezone(timezone.utc)
    state = sessions.market_state(now_utc)
    errors = []
    analyses = analyze_universe(universe, daily, now_utc, errors)
    by_symbol = {a["symbol"]: a for a in analyses}
    hits = [_hit(a) for a in analyses if has_setup(a)]
    last_bar = max((a["last_bar_date"] for a in analyses), default=None)
    warnings = []

    if state == "closed_weekend":
        last = last_bar
        warnings.append(
            "Marché fermé (week-end) : les données sont les dernières clôtures%s."
            % (" (dernière barre : %s)" % last if last else ""))
    if failed:
        warnings.append("Sans données : %d symbole(s) en échec (%s)."
                        % (len(failed), join_names([f["symbol"] for f in failed])))
    broken = {sym for sym, _ in errors}
    short = [s for s, _ in universe if s in daily and s not in by_symbol and s not in broken]
    if short:
        warnings.append("Moins de 30 séances complètes, non analysés : %s." % join_names(short))
    for sym, kind in errors:
        warnings.append("%s : analyse impossible (%s)" % (sym, kind))

    # data age: the oldest cache that was used after a network failure
    ages = [s.age_s for s in list(daily.values()) + list(hourly.values())
            if getattr(s, "age_s", None) is not None]
    data_age = int(round(max(ages))) if ages else None
    if ages:
        warnings.append(
            "Cache périmé utilisé après un échec réseau pour %d série(s) ; "
            "la plus ancienne a %s h." % (len(ages), _hours(max(ages))))

    status = calendar.get("status", "unavailable")
    reason = calendar.get("reason")
    if status != "ok":
        label = "indisponible" if status == "unavailable" else "partiel"
        warnings.append("Calendrier économique %s : %s." % (label, reason or "raison inconnue"))
    warnings.extend(extra_warnings)

    # calendar: high impact, currencies of the analysed symbols
    focus = economic_calendar.focus_currencies([a["symbol"] for a in analyses])
    events = economic_calendar.filter_events(calendar.get("events") or [], focus)
    events_24h = economic_calendar.within_hours(events, start_utc=now_utc, hours=24)

    # strength: complete daily closes of the forex pairs only
    closes = {}
    for sym, s in daily.items():
        if strength.pair_currencies(sym) is not None:
            closes[sym] = [bar[4] for bar in signals.complete_daily(s, now_utc)]
    windows = strength.currency_strength(closes)

    # day plan
    table = sessions.session_table(now_utc)
    if state == "closed_weekend":
        for row in table:
            row["active"] = False
    levels = []
    for sym in alert_symbols(hits):
        a = by_symbol.get(sym)
        if a is None:
            continue
        row = {"symbol": sym, "name": a["name"]}
        row.update(a["levels"])
        asia = signals.asia_range(hourly[sym], now_utc) if sym in hourly else None
        for k in ("asia_high", "asia_low", "day_high", "day_low"):
            row[k] = asia[k] if asia else None
        row["asia_complete"] = asia["asia_complete"] if asia else None
        levels.append(row)

    paris = now_utc.astimezone(sessions.PARIS)
    ny = now_utc.astimezone(sessions.NEW_YORK)
    return {
        "as_of": {"iso": now_utc.isoformat(),
                  "paris": paris.strftime("%Y-%m-%d %H:%M"),
                  "new_york": ny.strftime("%Y-%m-%d %H:%M")},
        "market_state": state,
        "counts": {"requested": len(universe), "fetched": len(daily),
                   "scanned": len(analyses), "failed": list(failed),
                   "last_bar_date": last_bar},
        "data_age": data_age,
        "calendar": {"status": status, "events": events, "reason": reason or None},
        "strength": {"windows": windows},
        "swing": {"hits": hits, "clusters": strength.clusters(hits)},
        "day_plan": {"sessions": table, "levels": levels, "events_24h": events_24h},
        "trade_ideas": plan.build_trade_ideas(analyses, cfg),
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- summary

def _cut(text, n=LINE_CHARS):
    return text if len(text) <= n else text[:n - 3] + "..."


def _num(v, fmt):
    return "n/a" if v is None else fmt % v


def _strength_line(b):
    rows = b["strength"]["windows"].get("5d") or []
    if not rows:
        return "Force des devises (5 séances) : n/a"
    best, worst = rows[0], rows[-1]
    return "Force des devises (5 séances) : meilleure %s %+.2f %%, pire %s %+.2f %%" % (
        best["ccy"], best["score"], worst["ccy"], worst["score"])


def _calendar_lines(b):
    cal = b["calendar"]
    if cal["status"] == "unavailable":
        return ["Annonces à fort impact (24 h) : calendrier indisponible, non vérifié"]
    evs = b["day_plan"]["events_24h"]
    if not evs:
        return ["Annonces à fort impact (24 h) : aucune"]
    out = ["Annonces à fort impact (24 h) : %d" % len(evs)]
    for e in evs[:CAL_LINES]:
        out.append(_cut("  %s %s Paris (%s NY)  %s  %s" % (
            e["date_paris"][5:], e["time_paris"], e["time_ny"], e["currency"], e["title"])))
    if len(evs) > CAL_LINES:
        out.append("  ... et %d autres (voir briefing.json)" % (len(evs) - CAL_LINES))
    return out


def _price(v):
    """A price with the precision of its JSON value, never in scientific notation."""
    text = repr(float(v))
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def _size_text(size):
    """(size words, whether the risk is shown) for one idea line."""
    if size["status"] == "too_wide":
        return "stop trop large", False
    if size["status"] != "ok":
        return "taille à confirmer", False
    if size.get("lots") is not None:
        return "%.2f lot" % size["lots"], True
    return "taille %s" % _price(size["size"]), True


def _idea_line(idea):
    words, with_risk = _size_text(idea["size"])
    text = "  %d. %s %s  entrée %s  stop %s  cible %s  %s" % (
        idea["rank"], idea["symbol"], idea["side"], _price(idea["reference_price"]),
        _price(idea["stop"]), _price(idea["target"]), words)
    if with_risk:
        text += "  risque %.2f USD" % idea["size"]["risk_usd"]
    return _cut(text)


def _idea_lines(b):
    """The trade ideas block: IDEA_LINES lines at most, risk line always kept."""
    ti = b["trade_ideas"]
    ideas = ti["ideas"]
    if not ideas:
        return ["Idées de trade : aucune"]
    out = ["Idées de trade (%d), plan mécanique à valider :" % len(ideas)]
    shown = ideas if len(ideas) <= IDEA_ROWS else ideas[:IDEA_ROWS - 1]
    out += [_idea_line(i) for i in shown]
    if len(shown) < len(ideas):
        out.append("  ... et %d autres (voir briefing.json)" % (len(ideas) - len(shown)))
    out.append(_cut("  Risque cumulé : %.2f USD (%.2f %%) sur %s %% autorisés%s" % (
        ti["total_risk_usd"], ti["total_risk_pct"], str(float(ti["max_total_pct"])),
        " : dépassé" if ti["over_cap"] else "")))
    return out


def _warning_lines(b):
    w = b["warnings"]
    if not w:
        return []
    out = ["Avertissements :"]
    out += [_cut("  - " + t) for t in w[:WARN_LINES]]
    if len(w) > WARN_LINES:
        out.append("  - ... et %d autres (voir briefing.json)" % (len(w) - WARN_LINES))
    return out


def _cluster_lines(b):
    out = []
    for c in b["swing"]["clusters"][:2]:
        who = "le dollar (USD)" if c["ccy"] == "USD" else c["ccy"]
        out.append("  %d des %d signaux forex concernent %s : signaux corrélés, "
                   "pas indépendants" % (c["count"], c["of"], who))
    return out


def _hit_line(h):
    return _cut("  %s%s  RSI %s  ATR %s  tendance %s : %s" % (
        h["symbol"], "" if h["name"] == h["symbol"] else " " + h["name"],
        _num(h["rsi"], "%.0f"), _num(h["atr_pct"], "%.2f %%"),
        h["trend"] if h["trend"] else "n/a",
        ", ".join(h["setups"] + h.get("setups_short", []))))


def _hit_lines(b, budget):
    """Header, correlation message and the hits grouped by family, in `budget` lines."""
    hits = b["swing"]["hits"]
    n, scanned = len(hits), b["counts"]["scanned"]
    out = ["Setups : %d sur %d analysés ont matché une règle" % (n, scanned)]
    out += _cluster_lines(b)
    groups = [(label, [h for h in hits if family(h["symbol"]) == key])
              for key, label in FAMILIES]
    groups = [(label, items) for label, items in groups if items]
    room = budget - len(out) - len(groups)  # lines left for hits and "... et N autres"
    # share the room round-robin, so every family shows something
    quota = [0] * len(groups)
    left = room
    while left > 0 and any(q < len(g[1]) for q, g in zip(quota, groups)):
        for i, (_, items) in enumerate(groups):
            if left > 0 and quota[i] < len(items):
                quota[i] += 1
                left -= 1
    for (label, items), q in zip(groups, quota):
        out.append("%s (%d) :" % (label, len(items)))
        if q >= len(items):
            out += [_hit_line(h) for h in items]
        elif q >= 2:
            out += [_hit_line(h) for h in items[:q - 1]]
            out.append("  ... et %d autres (voir briefing.json)" % (len(items) - q + 1))
        else:
            out.append("  ... %d (voir briefing.json)" % len(items))
    return out[:max(budget, 1)]


def render_summary(b):
    c = b["counts"]
    closed = b["market_state"] == "closed_weekend"
    head = [
        "Briefing FX : %s New York (%s Paris)" % (b["as_of"]["new_york"], b["as_of"]["paris"]),
        "Marché : " + ("fermé (week-end), dernières clôtures" if closed else "ouvert"),
        "Reçus : %d sur %d (%d en échec)" % (c["fetched"], c["requested"], len(c["failed"])),
        "Analysés : %d (moins de 30 séances : %d)" % (c["scanned"], c["fetched"] - c["scanned"]),
        "Dernière barre : %s" % (c.get("last_bar_date") or "n/a"),
    ]
    if c["failed"]:
        head.append(_cut("Échecs : " + join_names([f["symbol"] for f in c["failed"]])))
    head.append(_strength_line(b))
    head += _calendar_lines(b)
    head += _idea_lines(b)
    tail = _warning_lines(b) + [b["disclaimer"]]
    lines = head + _hit_lines(b, MAX_LINES - len(head) - len(tail)) + tail
    return "\n".join(lines[:MAX_LINES])
