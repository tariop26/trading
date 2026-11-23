"""Reversal levels ("niveaux de reverse") of the FundedNext assets: three families, fixed rules.

1. Bascule de tendance (D1). The trend is the one of the sheet: close under the 20-day mean and
   20-day mean under the 50-day mean is "baissière", the mirror is "haussière", else "neutre".
   The flip level is the latest confirmed daily swing (Williams fractal: a high above the 2 bars
   on each side, the mirror for a low): the latest swing high in a "baissière" trend, the latest
   swing low in a "haussière" trend, both in a "neutre" one. Price beyond it puts the trend in
   question; only a daily close confirms.
2. Zones de retournement (D1). Highs and lows of 20 and 5 sessions, and the two extensions
   20-day mean +/- 3 average daily ranges (14 sessions, high minus low, as in the sheet): beyond
   them the market is stretched and a sharp move against the trend is more likely.
3. Parabolic SAR (Stop And Reverse), Wilder's rule, step 0.02, maximum 0.2, on daily bars and on
   4-hour bars built from hourly bars (UTC buckets 0, 4, 8, 12, 16, 20 h, complete buckets only).

Standard library only, pure functions: bars are `(ts_utc_seconds, open, high, low, close)`. The
prices are Yahoo reference prices, not the broker's CFD quotes. A level is a level to watch, not
a forecast and not advice.
"""
from datetime import datetime, timezone

import sessions

SAR_STEP, SAR_MAX = 0.02, 0.2
FRACTAL = 2
ZONE_NEAR_ATR = 0.25          # "approche" = within a quarter of the average daily range
EXT_ATR = 3.0
H4 = 4 * 3600
DAY_S = 86400


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def clean(bars):
    """Bars sorted by time with numeric high, low and close."""
    return sorted((b for b in bars or [] if all(_num(b[i]) for i in (0, 2, 3, 4))),
                  key=lambda b: b[0])


def completed(bars, now_ts, length):
    """The bars whose period is over at `now_ts` (a bar of `length` seconds)."""
    return [b for b in bars if b[0] + length <= now_ts]


def to_h4(hourly):
    """Hourly bars -> 4-hour bars on UTC buckets (open of the first hour, close of the last)."""
    out, cur = [], None
    for b in clean(hourly):
        k = int(b[0]) // H4 * H4
        if cur is None or cur[0] != k:
            if cur:
                out.append(tuple(cur))
            cur = [k, b[1], b[2], b[3], b[4]]
        else:
            cur[2], cur[3], cur[4] = max(cur[2], b[2]), min(cur[3], b[3]), b[4]
    if cur:
        out.append(tuple(cur))
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def trend(daily):
    """'baissière', 'haussière' or 'neutre' (None with fewer than 50 sessions)."""
    closes = [b[4] for b in daily]
    if len(closes) < 50:
        return None
    m20, m50, last = _mean(closes[-20:]), _mean(closes[-50:]), closes[-1]
    if last < m20 < m50:
        return "baissière"
    if last > m20 > m50:
        return "haussière"
    return "neutre"


def swings(bars, k=FRACTAL):
    """Confirmed fractal swings -> [(ts, 'haut' | 'bas', price)] in time order."""
    out = []
    for i in range(k, len(bars) - k):
        window = bars[i - k:i + k + 1]
        if bars[i][2] == max(b[2] for b in window) and \
                all(bars[i][2] > b[2] for j, b in enumerate(window) if j != k):
            out.append((bars[i][0], "haut", bars[i][2]))
        if bars[i][3] == min(b[3] for b in window) and \
                all(bars[i][3] < b[3] for j, b in enumerate(window) if j != k):
            out.append((bars[i][0], "bas", bars[i][3]))
    return out


def bascule(daily, tr):
    """{'haut': price or None, 'bas': price or None}: the flip levels that matter for the trend."""
    last = {"haut": None, "bas": None}
    for _ts, kind, price in swings(daily):
        last[kind] = price
    if tr == "baissière":
        return {"haut": last["haut"], "bas": None}
    if tr == "haussière":
        return {"haut": None, "bas": last["bas"]}
    return last


def avg_range(daily, n=14):
    rows = daily[-n:]
    return _mean([b[2] - b[3] for b in rows]) if len(rows) == n else None


def zones(daily):
    """Resistances and supports of the day, or None with fewer than 20 sessions."""
    if len(daily) < 20:
        return None
    atr = avg_range(daily)
    m20 = _mean([b[4] for b in daily[-20:]])
    out = {"haut_20j": max(b[2] for b in daily[-20:]), "bas_20j": min(b[3] for b in daily[-20:]),
           "haut_5j": max(b[2] for b in daily[-5:]), "bas_5j": min(b[3] for b in daily[-5:]),
           "atr": atr, "ext_haute": None, "ext_basse": None}
    if atr:
        out["ext_haute"], out["ext_basse"] = m20 + EXT_ATR * atr, m20 - EXT_ATR * atr
    return out


ZONE_NAMES = {"haut_20j": "plus haut 20 jours", "bas_20j": "plus bas 20 jours",
              "haut_5j": "plus haut 5 jours", "bas_5j": "plus bas 5 jours",
              "ext_haute": "extension haute (moyenne 20 j + 3 amplitudes)",
              "ext_basse": "extension basse (moyenne 20 j - 3 amplitudes)"}


def psar(bars, step=SAR_STEP, maximum=SAR_MAX):
    """Parabolic SAR -> [(ts, sar, 'haussier' | 'baissier')], one per bar from the second."""
    if len(bars) < 2:
        return []
    up = bars[1][4] >= bars[0][4]
    ep = max(bars[0][2], bars[1][2]) if up else min(bars[0][3], bars[1][3])
    sar = min(bars[0][3], bars[1][3]) if up else max(bars[0][2], bars[1][2])
    af = step
    out = [(bars[1][0], sar, "haussier" if up else "baissier")]
    for i in range(2, len(bars)):
        prev, prev2 = bars[i - 1], bars[i - 2]
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, prev[3], prev2[3])
            if bars[i][3] < sar:                     # reverse to down
                up, sar, ep, af = False, ep, bars[i][3], step
            elif bars[i][2] > ep:
                ep, af = bars[i][2], min(af + step, maximum)
        else:
            sar = max(sar, prev[2], prev2[2])
            if bars[i][2] > sar:                     # reverse to up
                up, sar, ep, af = True, ep, bars[i][2], step
            elif bars[i][3] < ep:
                ep, af = bars[i][3], min(af + step, maximum)
        out.append((bars[i][0], sar, "haussier" if up else "baissier"))
    return out


def sar_state(bars):
    """{'level', 'side', 'flipped', 'bar_ts'} of the last bar, or None."""
    s = psar(bars)
    if not s:
        return None
    flipped = len(s) >= 2 and s[-1][2] != s[-2][2]
    return {"level": s[-1][1], "side": s[-1][2], "flipped": flipped, "bar_ts": s[-1][0]}


def levels(daily, hourly, now_ts):
    """Everything for one asset from its daily and hourly bars, completed bars only."""
    d = completed(clean(daily), now_ts, DAY_S)
    h4 = completed(to_h4(hourly), now_ts, H4)
    tr = trend(d)
    return {"trend": tr, "close": d[-1][4] if d else None, "bascule": bascule(d, tr) if d else
            {"haut": None, "bas": None}, "zones": zones(d), "sar_d1": sar_state(d),
            "sar_h4": sar_state(h4)}


# ---------------------------------------------------------------- messages

def fmt(x):
    if x is None:
        return "n.d."
    digits = 0 if abs(x) >= 1000 else 2
    return "{:,.{d}f}".format(x, d=digits).replace(",", " ").replace(".", ",")


def _paris(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(sessions.PARIS).strftime("%d/%m %H:%M")


def summary_line(name, lv):
    """One line of the morning message for one asset."""
    if lv is None or lv.get("close") is None:
        return "%s : données indisponibles." % name
    b, z = lv["bascule"], lv["zones"] or {}
    parts = ["%s : tendance D1 %s, clôture %s" % (name, lv["trend"] or "n.d.", fmt(lv["close"]))]
    flips = [("au-dessus de %s" % fmt(b["haut"])) if b.get("haut") else None,
             ("sous %s" % fmt(b["bas"])) if b.get("bas") else None]
    flips = [f for f in flips if f]
    if flips:
        parts.append("bascule " + " ou ".join(flips))
    if z:
        parts.append("résistances %s / %s / ext. %s" % (fmt(z["haut_5j"]), fmt(z["haut_20j"]),
                                                      fmt(z["ext_haute"])))
        parts.append("supports %s / %s / ext. %s" % (fmt(z["bas_5j"]), fmt(z["bas_20j"]),
                                                   fmt(z["ext_basse"])))
    for label, key in (("SAR D1", "sar_d1"), ("SAR H4", "sar_h4")):
        s = lv.get(key)
        if s:
            parts.append("%s %s (%s%s)" % (label, fmt(s["level"]), s["side"],
                                           ", vient de se retourner" if s["flipped"] else ""))
    return " · ".join(parts) + "."


def morning_message(rows):
    """rows: [(name, levels)] -> the once-a-day message."""
    lines = ["Niveaux de reverse du jour (prix Yahoo de référence, séance précédente ; pour l'or, "
             "les futures cotent quelques dollars au-dessus de ton XAUUSD)."]
    lines += [summary_line(name, lv) for name, lv in rows]
    lines.append("Bascule : un prix au-delà remet la tendance D1 en question, seule une clôture "
                 "journalière la confirme. Niveaux à surveiller, pas des prévisions.")
    return "\n".join(lines)


def live_alerts(symbol, name, lv, price, day):
    """-> [(key, text)] for one asset at the latest price: flip level crossed, zone approached,
    SAR just turned on the last completed H4 or daily bar. The caller drops keys already sent."""
    out = []
    if lv is None:
        return out
    b, z = lv["bascule"], lv["zones"]
    if price is not None:
        if b.get("haut") and price > b["haut"]:
            out.append(("reverse|%s|bascule-haut|%s" % (symbol, day),
                        "Bascule de tendance en cours sur %s : prix %s au-dessus du dernier swing "
                        "haut D1 (%s). Tendance D1 %s remise en question, à confirmer par la "
                        "clôture du jour." % (name, fmt(price), fmt(b["haut"]), lv["trend"])))
        if b.get("bas") and price < b["bas"]:
            out.append(("reverse|%s|bascule-bas|%s" % (symbol, day),
                        "Bascule de tendance en cours sur %s : prix %s sous le dernier swing bas "
                        "D1 (%s). Tendance D1 %s remise en question, à confirmer par la clôture du "
                        "jour." % (name, fmt(price), fmt(b["bas"]), lv["trend"])))
        if z and z.get("atr"):
            near = ZONE_NEAR_ATR * z["atr"]
            for key in ("haut_20j", "bas_20j", "ext_haute", "ext_basse"):
                level = z.get(key)
                if level is not None and abs(price - level) <= near:
                    out.append(("reverse|%s|zone-%s|%s" % (symbol, key, day),
                                "%s approche une zone de retournement : %s à %s (prix %s, écart %s)."
                                % (name, ZONE_NAMES[key], fmt(level), fmt(price),
                                   fmt(abs(price - level)))))
    for label, key in (("H4", "sar_h4"), ("D1", "sar_d1")):
        s = lv.get(key)
        if s and s["flipped"]:
            out.append(("reverse|%s|sar-%s|%d" % (symbol, label, s["bar_ts"]),
                        "SAR %s retourné en %s sur %s : niveau %s (bougie de %s Paris). Un "
                        "retournement de SAR n'est pas un setup de ton plan." % (
                            label, s["side"], name, fmt(s["level"]), _paris(s["bar_ts"]))))
    return out
