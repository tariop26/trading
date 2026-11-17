"""SPIKE JETABLE : rejeu des signaux en séance sur des barres 1 min (CSV MT5).

Utilise les VRAIES fonctions du dépôt (scan_symbol, select, mark_signal) : seul le
chargement des données, l'horloge (cron :07/:22/:37/:52) et la simulation du trade sont
écrits ici. Usage : python3 replay_spike.py <dossier_csv> <symbole> [fichier_sortie_json]
"""
import bisect
import csv
import glob
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SKILL = r"C:\Users\m.poirat\trading\.claude\skills\trader-fx"
sys.path.insert(0, SKILL)
import alert_state  # noqa: E402
import config as fxconfig  # noqa: E402
import intraday_plan  # noqa: E402
import intraday_signals  # noqa: E402
import plan as plan_mod  # noqa: E402
import signals  # noqa: E402

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
SERVER_MINUS_NY = timedelta(hours=7)     # heure serveur MT5 = heure de New York + 7 h


def server_to_utc(naive):
    return (naive - SERVER_MINUS_NY).replace(tzinfo=NY).astimezone(UTC)


def load_1m(folder):
    """-> (ts, o, h, l, c, sp) en array compacts, daily [(date,o,h,l,c)]. Fichiers lus dans l'ordre du nom."""
    from array import array
    ts, o, h, l, c, sp = (array("q"), array("d"), array("d"), array("d"), array("d"), array("d"))
    days = {}
    spf = float(os.environ.get("SPREAD_F", "1"))
    last = -1
    def first_row(p):
        with open(p, encoding="utf-8") as f:
            f.readline()
            return f.readline()[:16]
    for path in sorted(glob.glob(os.path.join(folder, "*.csv")), key=first_row):
        batch = []
        with open(path, newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd)
            for r in rd:
                if len(r) < 9:
                    continue
                try:
                    d, t = r[0], r[1]
                    naive = datetime(int(d[0:4]), int(d[5:7]), int(d[8:10]), int(t[0:2]), int(t[3:5]))
                    row = (naive, float(r[2]), float(r[3]), float(r[4]), float(r[5]),
                           float(r[7]) * spf)
                except (ValueError, IndexError):
                    continue
                batch.append(row)
        batch.sort(key=lambda x: x[0])
        for naive, oo, hh, ll, cc, ss in batch:
            t_utc = int(server_to_utc(naive).timestamp())
            if t_utc <= last:
                continue                       # doublon ou retour en arrière : ignoré
            last = t_utc
            ts.append(t_utc); o.append(oo); h.append(hh); l.append(ll); c.append(cc); sp.append(ss)
            dd = naive.date()
            b = days.get(dd)
            if b is None:
                days[dd] = [dd, oo, hh, ll, cc]
            else:
                if hh > b[2]:
                    b[2] = hh
                if ll < b[3]:
                    b[3] = ll
                b[4] = cc
    return (ts, o, h, l, c, sp), [tuple(days[d]) for d in sorted(days)]


def to_15m(m1):
    ts, o, h, l, c, _sp = m1
    out, cur = [], None
    for i in range(len(ts)):
        k = ts[i] // 900 * 900
        if cur is None or cur[0] != k:
            if cur is not None:
                out.append(tuple(cur))
            cur = [k, o[i], h[i], l[i], c[i]]
        else:
            if h[i] > cur[2]:
                cur[2] = h[i]
            if l[i] < cur[3]:
                cur[3] = l[i]
            cur[4] = c[i]
    if cur is not None:
        out.append(tuple(cur))
    return out


def server_date(now_utc):
    return (now_utc.astimezone(NY).replace(tzinfo=None) + SERVER_MINUS_NY).date()


def daily_ctx(daily, now_utc):
    today = server_date(now_utc)
    done = [b for b in daily if b[0] < today]
    if len(done) < 50:
        return None
    closes = [b[4] for b in done]
    last = closes[-1]
    a = signals.atr(done)
    return {"last": last, "atr_pct": (a / last * 100.0) if a else None,
            "trend": signals.trend(closes), "name": "X"}


# --------------------------------------------------------------------- simulation

def simulate(m1, cand, now, horizon_ts, mirror=False, be=None):
    """-> dict(r, exit, filled) ; entrée au marché à la première minute >= now."""
    ts, o, h, l, c, sp = m1
    p = cand["plan"]
    long_ = cand["side"] == plan_mod.LONG
    if mirror:
        long_ = not long_
    entry, stop, target = p["reference_price"], p["stop"], p["target"]
    dist = abs(entry - stop)
    if mirror:   # même géométrie, sens opposé
        stop = entry - dist if long_ else entry + dist
        reward = abs(target - entry)
        target = entry + reward if long_ else entry - reward
    k = bisect.bisect_left(ts, int(now.timestamp()))
    n = len(ts)
    if k >= n or ts[k] > now.timestamp() + 900:
        return {"filled": False, "why": "no_data"}
    fill = o[k] + sp[k] if long_ else o[k]           # achat à l'ask, vente au bid
    if not mirror:
        lim = p["limit_price"]
        if (long_ and fill > lim) or ((not long_) and fill < lim):
            return {"filled": False, "why": "outside_zone"}
    if (long_ and fill <= stop) or ((not long_) and fill >= stop):
        return {"filled": False, "why": "beyond_stop"}
    risk = abs(fill - stop)
    trig = None if be is None else fill + be * (target - fill)
    cur, armed = stop, False
    for j in range(k, n):
        if ts[j] > horizon_ts:
            px = c[j - 1] if long_ else c[j - 1] + sp[j - 1]
            r = ((px - fill) if long_ else (fill - px)) / risk
            return {"filled": True, "exit": "time", "r": r}
        if long_:
            hit_stop, hit_tgt = l[j] <= cur, h[j] >= target
        else:
            hit_stop, hit_tgt = h[j] + sp[j] >= cur, l[j] + sp[j] <= target
        if hit_stop:                                  # stop avant cible si les deux dans la barre
            rr = ((cur - fill) if long_ else (fill - cur)) / risk
            return {"filled": True, "exit": "be" if armed else "stop", "r": rr}
        if hit_tgt:
            return {"filled": True, "exit": "target", "r": abs(target - fill) / risk}
        if trig is not None and not armed:
            if (long_ and h[j] >= trig) or ((not long_) and l[j] + sp[j] <= trig):
                armed, cur = True, fill
    return {"filled": False, "why": "end_of_data"}


# --------------------------------------------------------------------- boucle

def run(folder, symbol):
    cfg = fxconfig.defaults()
    cfg["intraday"]["max_per_day"] = 10
    m1, daily = load_1m(folder)
    bars15 = to_15m(m1)
    b15_ts = [b[0] for b in bars15]
    first = datetime.fromtimestamp(m1[0][0], UTC)
    last = datetime.fromtimestamp(m1[0][-1], UTC)
    print("barres 1 min : %d, 15 min : %d, jours : %d, de %s à %s" % (
        len(m1[0]), len(bars15), len(daily), first.date(), last.date()), flush=True)

    params = intraday_signals.signal_params(cfg)
    trades, diag = [], defaultdict(int)
    day = first.date()
    state, state_day = None, None
    while day <= last.date():
        if day.weekday() < 5:
            iso = day.isoformat()
            if state_day != iso:
                state, state_day = alert_state.empty_state(iso), iso
            for hour in range(7, 22):
                for minute in (7, 22, 37, 52):
                    now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
                    ctx = daily_ctx(daily, now)
                    if ctx is None:
                        diag["warmup"] += 1
                        continue
                    hi = bisect.bisect_right(b15_ts, int(now.timestamp()) - 900)
                    window = bars15[max(0, hi - 200):hi]
                    if len(window) < 20:
                        diag["no_bars"] += 1
                        continue
                    if now.timestamp() - (window[-1][0] + 900) > 3600:
                        diag["market_closed"] += 1
                        continue
                    ranges = intraday_signals.session_ranges(
                        intraday_signals.closed_bars(window, now), now, params)
                    cand, reason = intraday_plan.scan_symbol(
                        symbol, symbol, window, ranges, ctx, cfg, {}, now)
                    if cand is None:
                        diag[reason] += 1
                        continue
                    diag["candidat"] += 1
                    chosen, _cap = intraday_plan.select([cand], state, cfg, now)
                    if not chosen:
                        diag["écarté (repos/doublon/plafond)"] += 1
                        continue
                    c = chosen[0]
                    alert_state.mark_signal(state, c, now)
                    horizon = int(datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC).timestamp())
                    res = simulate(m1, c, now, horizon)
                    mir = simulate(m1, c, now, horizon, mirror=True)
                    resbe = simulate(m1, c, now, horizon, be=0.3)
                    trades.append({"at": now.isoformat(), "side": c["side"], "primary": c["primary"],
                                   "families": c["families"], "score": c["score"],
                                   "session": c["detail"], "rr": c["plan"]["rr"],
                                   "res": res, "mirror": mir, "resbe": resbe})
                    diag["alerte"] += 1
        day += timedelta(days=1)
    return trades, dict(diag)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def summarize(trades, key=lambda t: "tous", field="res"):
    groups = defaultdict(list)
    for t in trades:
        for k in (key(t) if isinstance(key(t), list) else [key(t)]):
            groups[k].append(t)
    rows = []
    for k, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        filled = [t[field] for t in ts if t[field].get("filled")]
        n = len(filled)
        if n == 0:
            rows.append((k, len(ts), 0, None, None, None, None, None))
            continue
        rs = [x["r"] for x in filled]
        wins = sum(1 for x in filled if x["exit"] == "target")
        lo, hi = wilson(wins, n)
        rows.append((k, len(ts), n, wins / n, statistics.mean(rs), sum(rs), (lo, hi),
                     sum(1 for x in filled if x["exit"] == "time") / n))
    return rows


def show(title, rows):
    print("\n== %s" % title)
    print("%-22s %6s %6s %7s %9s %8s %16s %6s" % (
        "groupe", "alertes", "pris", "cible%", "R moyen", "R total", "IC95 cible%", "temps%"))
    for k, na, n, w, mr, tot, ci, tm in rows:
        if n == 0:
            print("%-22s %6d %6d" % (k, na, n))
            continue
        print("%-22s %6d %6d %6.1f%% %9.3f %8.1f %7.0f-%.0f%% %6.0f%%" % (
            k, na, n, w * 100, mr, tot, ci[0] * 100, ci[1] * 100, tm * 100))


if __name__ == "__main__":
    folder, symbol, out = sys.argv[1], sys.argv[2], sys.argv[3]
    trades, diag = run(folder, symbol)
    print("Diagnostic :", json.dumps(diag, ensure_ascii=False), flush=True)
    print("alertes :", len(trades))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"symbol": symbol, "diag": diag, "trades": trades}, fh)
