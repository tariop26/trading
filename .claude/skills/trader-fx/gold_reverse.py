"""Setup D: reversal on a well-identified H4 level of gold, entered with a limit order at the level.

Manu's rules (23 November 2026), not backtested, alerts only:
- Levels, on XAU/USD spot (Twelve Data, the same scale as the broker's XAUUSD):
  * H4 swing zones touched at least twice: Williams fractals (2 bars each side) of the last
    H4 bars, grouped when they lie within ZONE_ATR x ATR(14) H4 of each other; the zone price is
    the mean of its swings, its strength the number of touches;
  * previous day and previous week highs and lows, on the broker's day (New York + 7 h, the
    MT5 server time of FundedNext);
  * round numbers, multiples of ROUND_STEP dollars.
  Levels closer than MERGE_ATR x ATR H4 are merged into one, with all their reasons (confluence).
- Side: a level under the price is a support (haussier), above it a resistance (baissier).
- Plan: limit order at the level, stop SL_ATR x ATR(14) H4 beyond it, target 2R. Size from the
  risk allowed per trade and 100 USD per 1.00 for 1 lot, rounded down to 0.01 lot.
- Alert when the price comes within NEAR_ATR x ATR H4 of a level, once per level and per day,
  never in the 30 minutes before a high-impact USD announcement. At most MAX_PER_RUN per run.

Standard library only, pure functions except the Twelve Data call. Bars are
(ts_utc_seconds, open, high, low, close). A level is a plan to check, not advice: the message
reminds that the setup is not validated.
"""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import reversal
import sessions

NEW_YORK = ZoneInfo("America/New_York")
SERVER_SHIFT = timedelta(hours=7)        # MT5 server time = New York + 7 h
ROUND_STEP = 50.0
ZONE_ATR = 0.3
MERGE_ATR = 0.25
NEAR_ATR = 0.5
SL_ATR = 0.6
TARGET_R = 2.0
USD_PER_POINT = 100.0
LOT_STEP = 0.01
MAX_PER_RUN = 2
H4_LOOKBACK = 120                        # about 20 trading days of H4 bars
SYMBOL = "XAU/USD"
TD_URL = "https://api.twelvedata.com/time_series"


def server_day(ts):
    """The broker's trading day (a date) of a UTC timestamp."""
    when = datetime.fromtimestamp(ts, timezone.utc).astimezone(NEW_YORK) + SERVER_SHIFT
    return when.date()


def daily_from_hourly(hourly):
    """Hourly bars -> {server day: (high, low)}."""
    out = {}
    for b in reversal.clean(hourly):
        d = server_day(b[0])
        hi, lo = out.get(d, (b[2], b[3]))
        out[d] = (max(hi, b[2]), min(lo, b[3]))
    return out


def atr(bars, n=14):
    """Average true range of the last n bars, or None."""
    bars = reversal.clean(bars)
    if len(bars) < n + 1:
        return None
    trs = [max(b[2] - b[3], abs(b[2] - p[4]), abs(b[3] - p[4])) for p, b in zip(bars, bars[1:])]
    return sum(trs[-n:]) / n


def swing_zones(h4, atr_h4):
    """H4 swing zones touched at least twice -> [(price, touches)]."""
    swings = [p for _ts, _kind, p in reversal.swings(h4[-H4_LOOKBACK:])]
    tol = ZONE_ATR * atr_h4
    clusters = []
    for p in sorted(swings):
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [(sum(c) / len(c), len(c)) for c in clusters if len(c) >= 2]


def candidate_levels(hourly, now_ts):
    """-> (levels, atr_h4, last_price). levels: [{"price", "reasons"}], merged confluences."""
    bars = [b for b in reversal.clean(hourly) if b[0] + 3600 <= now_ts]
    h4 = reversal.completed(reversal.to_h4(bars), now_ts, reversal.H4)
    a = atr(h4)
    if not bars or a is None:
        return [], a, None
    price = bars[-1][4]
    raw = [(p, "swing H4 touché %d fois" % n) for p, n in swing_zones(h4, a)]
    days = daily_from_hourly(bars)
    today = server_day(now_ts)
    past = sorted(d for d in days if d < today)
    if past:
        hi, lo = days[past[-1]]
        raw += [(hi, "plus haut de la veille"), (lo, "plus bas de la veille")]
    monday = today - timedelta(days=today.weekday())
    week = [days[d] for d in past if monday - timedelta(days=7) <= d < monday]
    if week:
        raw += [(max(w[0] for w in week), "plus haut de la semaine dernière"),
                (min(w[1] for w in week), "plus bas de la semaine dernière")]
    base = math.floor(price / ROUND_STEP) * ROUND_STEP
    raw += [(base + k * ROUND_STEP, "chiffre rond") for k in (-1, 0, 1, 2)]
    merged = []
    for p, why in sorted(raw):
        if merged and p - merged[-1]["last"] <= MERGE_ATR * a:
            m = merged[-1]
            m["prices"].append(p)
            m["last"] = p
            if why not in m["reasons"]:
                m["reasons"].append(why)
        else:
            merged.append({"prices": [p], "last": p, "reasons": [why]})
    levels = []
    for m in merged:
        rounds = [p for p, w in raw if w == "chiffre rond" and p in m["prices"]]
        # a round number in the cluster is the natural limit price; else the mean
        level = rounds[0] if rounds else sum(m["prices"]) / len(m["prices"])
        levels.append({"price": level, "reasons": m["reasons"]})
    return levels, a, price


def plan(level, price, atr_h4, risk_usd):
    """The limit-order plan for one level, or None when the price sits on it."""
    if level == price:
        return None
    side = "haussier" if level < price else "baissier"
    dist = SL_ATR * atr_h4
    stop = level - dist if side == "haussier" else level + dist
    target = level + TARGET_R * dist if side == "haussier" else level - TARGET_R * dist
    lots = math.floor(risk_usd / (dist * USD_PER_POINT) / LOT_STEP + 1e-9) * LOT_STEP if risk_usd else 0
    return {"side": side, "entry": round(level, 2), "stop": round(stop, 2),
            "target": round(target, 2), "lots": round(lots, 2),
            "risk": round(lots * dist * USD_PER_POINT, 2)}


def _fmt(x):
    return reversal.fmt(x)


def message(lv, p, price, trend, now_ts):
    when = datetime.fromtimestamp(now_ts, timezone.utc).astimezone(sessions.PARIS).strftime("%H:%M")
    kind = "support" if p["side"] == "haussier" else "résistance"
    lines = [
        "Setup D, or H4 (retournement, non validé par backtest) : %s à %s en approche." % (
            kind, _fmt(p["entry"])),
        "Niveau : %s. Prix XAU/USD %s à %s Paris (écart %s)." % (
            ", ".join(lv["reasons"]), _fmt(price), when, _fmt(abs(price - p["entry"]))),
        "Ordre limite %s à %s, stop %s, cible %s (2R)." % (
            p["side"], _fmt(p["entry"]), _fmt(p["stop"]), _fmt(p["target"])),
        ("Taille %.2f lot, risque %s $." % (p["lots"], _fmt(p["risk"]))) if p["lots"] > 0 else
        "Taille sous 0,01 lot : stop trop large pour le risque autorisé, pas de setup.",
    ]
    if trend and ((trend == "baissière" and p["side"] == "haussier")
                  or (trend == "haussière" and p["side"] == "baissier")):
        lines.append("Contre la tendance D1 %s : le risque de traverser le niveau est réel." % trend)
    lines.append("Avant l'ordre : statut du jour, risque ouvert et groupe Or libre dans le classeur. "
                 "Plan à valider, pas un conseil.")
    return "\n".join(lines)


def alerts(hourly, now_ts, risk_usd, trend, sent, day, news_block=False):
    """-> ([(key, text)], log lines) for the levels the price is approaching now."""
    levels, a, price = candidate_levels(hourly, now_ts)
    if a is None or price is None:
        return [], ["setup D : pas assez de barres H4 pour l'or"]
    if news_block:
        return [], ["setup D : annonce forte USD dans les 30 min, alertes suspendues"]
    out = []
    near = NEAR_ATR * a
    for lv in sorted(levels, key=lambda l: abs(l["price"] - price)):
        if abs(lv["price"] - price) > near:
            continue
        key = "setupD|%d|%s" % (round(lv["price"]), day)
        if key in sent:
            continue
        p = plan(lv["price"], price, a, risk_usd)
        if p is None:
            continue
        out.append((key, message(lv, p, price, trend, now_ts)))
        if len(out) >= MAX_PER_RUN:
            break
    return out, ["setup D : %d niveau(x) or, ATR H4 %s, prix %s" % (len(levels), _fmt(a), _fmt(price))]


def fetch_hourly(key, http_get):
    """XAU/USD hourly bars from Twelve Data (one credit). Raises live_gold.FeedError."""
    import urllib.parse
    import live_gold
    q = urllib.parse.urlencode({"symbol": SYMBOL, "interval": "1h", "outputsize": 600,
                                "timezone": "UTC", "apikey": key})
    try:
        text = http_get(TD_URL + "?" + q)
    except Exception as e:  # noqa: BLE001 - the type only: the URL contains the key
        raise live_gold.FeedError("réseau (%s)" % type(e).__name__)
    return [tuple(b) for b in live_gold.parse_bars(text)]
