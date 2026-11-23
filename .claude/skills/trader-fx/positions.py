"""Open positions read from the Google Sheets tab "Positions ouvertes", published as CSV.

The sheet is the single source of truth for the FundedNext challenge: Manu writes each trade in
its Journal tab, and the "Positions ouvertes" tab keeps the rows with no closing date, plus a few
account figures (closed balance, today's closed result, the plan's loss limits).

    columns A to J : Id, Actif, Symbole Yahoo, Sens, Entrée, SL, TP, Lots,
                     Valeur 1,00 pour 1 lot ($), Ouverture (Paris, "AAAA-MM-JJ HH:MM")
    columns L and M: Paramètre, Valeur

Standard library only. Pure functions except `fetch_csv` (network). A bad row is skipped with a
reason, never fatal, so one typo in the journal cannot silence the other positions.

Prices: the guard and the 15-minute server watch Yahoo prices (futures or cash index), which are
not the CFD prices of the broker. `entry_offset` measures the gap at the opening time (Yahoo price
of the opening 5-minute bar minus the CFD entry) and the levels and the floating result are
corrected by it, so the gap between the two quotes cancels out.
"""
import csv
import io
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
SIDES = ("haussier", "baissier")
MAX_OFFSET_PCT = 0.03      # a gap above 3 % of the price is a wrong time or symbol: not used
BAR_SECONDS = 300          # the 5-minute bars of the alert server
UA = "Mozilla/5.0 (compatible; trader-fx/1.0)"

PARAMS = {
    "Solde clos ($)": "closed_balance",
    "P&L clos aujourd'hui ($)": "realized_today",
    "Capital initial ($)": "capital",
    "Alerte perte du jour ($)": "warn_loss",
    "Stop journalier interne ($)": "internal_stop",
    "Perte journalière max FundedNext ($)": "fn_daily",
    "Plancher perte max ($)": "floor",
    "Risque ouvert max ($)": "open_risk_max",
    "Risque autorisé par trade ($)": "risk_per_trade",
}


class PositionsError(Exception):
    """The published tab could not be read (network, empty, not the expected header)."""


def parse_number(text):
    """'24888,66', '99 302 $', '-382 $', '1 500,00' -> float, else None (empty, text, n/a)."""
    if text is None:
        return None
    t = str(text).strip()
    for ch in ("$", "€", " ", " ", " "):
        t = t.replace(ch, "")
    t = t.replace("−", "-").replace(",", ".")
    if not t:
        return None
    try:
        value = float(t)
    except ValueError:
        return None
    return value if value == value else None


def paris_to_utc(text):
    """'2026-11-20 17:35' (Paris) -> aware UTC datetime, else None."""
    try:
        local = datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return local.replace(tzinfo=PARIS).astimezone(timezone.utc)


def _position(row, n):
    """One CSV row (columns A to J) -> (position or None, problem or None)."""
    cells = (list(row) + [""] * 10)[:10]
    pid, asset, symbol, side = (c.strip() for c in cells[:4])
    if not asset:
        return None, None                                  # an empty row of the FILTER
    label = pid or "ligne %d" % n
    if side not in SIDES:
        return None, "%s %s : sens illisible" % (asset, label)
    if not symbol:
        return None, "%s %s : pas de symbole Yahoo dans Specs actifs" % (asset, label)
    entry, stop, target, lots, ppt = (parse_number(c) for c in cells[4:9])
    for name, value in (("entrée", entry), ("SL", stop), ("lots", lots),
                        ("valeur du point", ppt)):
        if value is None or value <= 0:
            return None, "%s %s : %s manquant ou invalide" % (asset, label, name)
    long_side = side == "haussier"
    if (stop >= entry) if long_side else (stop <= entry):
        return None, "%s %s : SL du mauvais côté de l'entrée" % (asset, label)
    problem = None
    if target is not None and ((target <= entry) if long_side else (target >= entry)):
        problem = "%s %s : TP du mauvais côté, ignoré" % (asset, label)
        target = None
    opened = paris_to_utc(cells[9])
    if opened is None:
        return None, "%s %s : heure d'ouverture illisible" % (asset, label)
    return {"id": label, "asset": asset, "symbol": symbol, "side": side, "entry": entry,
            "stop": stop, "target": target, "lots": lots, "usd_per_point": ppt,
            "opened_utc": opened.isoformat()}, problem


def parse_csv(text):
    """CSV text of the published tab -> (positions, params, problems).

    Raises PositionsError when the header is not the expected one (wrong tab published)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 10 or rows[0][1].strip() != "Actif" \
            or rows[0][3].strip() != "Sens":
        raise PositionsError("onglet publié inattendu (en-tête Actif / Sens absent)")
    positions, params, problems = [], {}, []
    for n, row in enumerate(rows[1:], start=2):
        pos, problem = _position(row, n)
        if pos is not None:
            positions.append(pos)
        if problem:
            problems.append(problem)
        if len(row) >= 13 and row[11].strip() in PARAMS:
            value = parse_number(row[12])
            if value is not None:
                params[PARAMS[row[11].strip()]] = value
    return positions, params, problems


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_csv(url, http_get=_http_get):
    """The published CSV text. Raises PositionsError with the error type only (the URL is a
    private link: it is never printed)."""
    try:
        text = http_get(url)
    except Exception as e:  # noqa: BLE001 - the type only: the message would contain the URL
        raise PositionsError("réseau (%s)" % type(e).__name__)
    if not text or not text.strip():
        raise PositionsError("CSV vide")
    return text


# ---------------------------------------------------------------- prices and levels

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def entry_offset(position, bars):
    """Yahoo price minus CFD entry at the opening time, or None.

    Uses the close of the 5-minute bar that contains the opening minute (or the last bar that
    closed before it, within 15 minutes: an opening on a quiet bar). None when no bar is close
    enough, or when the gap exceeds MAX_OFFSET_PCT of the entry (wrong time or wrong symbol)."""
    opened = datetime.fromisoformat(position["opened_utc"]).timestamp()
    best = None
    for b in bars or []:
        if not (_num(b[0]) and _num(b[4])):
            continue
        if b[0] <= opened < b[0] + BAR_SECONDS:
            best = b
            break
        if b[0] <= opened and opened - b[0] <= 3 * BAR_SECONDS:
            best = b
    if best is None:
        return None
    gap = best[4] - position["entry"]
    if abs(gap) > MAX_OFFSET_PCT * position["entry"]:
        return None
    return gap


def last_price(bars):
    """(close, bar start ts) of the latest bar with a close, or (None, None)."""
    for b in sorted((b for b in bars or [] if _num(b[0]) and _num(b[4])),
                    key=lambda b: b[0], reverse=True):
        return b[4], b[0]
    return None, None


def floating_usd(position, price, offset):
    """Floating result in USD of one position at a Yahoo price, corrected by the opening gap."""
    sign = 1 if position["side"] == "haussier" else -1
    move = price - (offset or 0.0) - position["entry"]
    return sign * move * position["lots"] * position["usd_per_point"]


def risk_usd(position):
    """Loss in USD if the stop is hit (the CFD levels: no price gap involved)."""
    return abs(position["entry"] - position["stop"]) * position["lots"] * position["usd_per_point"]


def trade_label(position):
    opened = datetime.fromisoformat(position["opened_utc"]).astimezone(PARIS)
    return "%s ouvert le %s" % (position["asset"], opened.strftime("%d/%m %H:%M"))


def to_rules(positions, offsets):
    """Stop and target rules in the format of alerts.json, levels moved by each position's gap
    (`offsets` maps a position id to the gap; a missing gap means 0, the CFD level as is)."""
    rules = []
    for p in positions:
        gap = offsets.get(p["id"]) or 0.0
        for kind, level in (("stop", p["stop"]), ("cible", p["target"])):
            if level is None:
                continue
            rules.append({"id": "%s-%s" % (p["id"], kind), "trade_id": trade_label(p),
                          "symbol": p["symbol"], "type": kind, "side": p["side"],
                          "level": round(level + gap, 2), "decimals": 2,
                          "since": p["opened_utc"]})
    return rules
