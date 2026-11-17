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
    rows = {}
    for path in glob.glob(os.path.join(folder, "*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd)
            for r in rd:
                if len(r) < 9:
                    continue
                try:
                    naive = datetime.strptime(r[0] + " " + r[1], "%Y.%m.%d %H:%M")
                    o, h, l, c, sp = float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[7]) * float(os.environ.get("SPREAD_F", "1"))
                except ValueError:
                    continue
                rows[naive] = (o, h, l, c, sp)        # un doublon : la dernière valeur gagne
    out = []
    for naive in sorted(rows):
        o, h, l, c, sp = rows[naive]
        out.append((int(server_to_utc(naive).timestamp()), o, h, l, c, sp, naive.date()))
    return out


def to_15m(m1):
    buckets = {}
    for ts, o, h, l, c, _sp, _d in m1:
        k = ts // 900 * 900
        b = buckets.get(k)
        if b is None:
            buckets[k] = [k, o, h, l, c]
        else:
            b[2] = max(b[2], h)
            b[3] = min(b[3], l)
            b[4] = c
    return [tuple(buckets[k]) for k in sorted(buckets)]


def daily_bars(m1):
    days = {}
    for ts, o, h, l, c, _sp, d in m1:
        b = days.get(d)
        if b is None:
            days[d] = [d, o, h, l, c]
        else:
            b[2] = max(b[2], h)
            b[3] = min(b[3], l)
            b[4] = c
    return [tuple(days[d]) for d in sorted(days)]


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
            "trend": signals.trend(closes), "name": "XAUUSD"}


# --------------------------------------------------------------------- simulation

def simulate(m1_ts, m1, cand, now, horizon_ts, mirror=False):
    """-> dict(r, exit, filled) pour un plan de candidat, entrée au marché juste après `now`."""
    p = cand["plan"]
    long_ = cand["side"] == plan_mod.LONG
    if mirror:
        long_ = not long_
    entry, stop, target = p["reference_price"], p["stop"], p["target"]
    dist = abs(entry - stop)
    if mirror:   # même géométrie, sens opposé
        stop = entry + dist if not long_ else entry - dist
        target = entry - abs(target - entry) if not long_ else entry + abs(target - entry)
        limit = entry
    k = bisect.bisect_left(m1_ts, int(now.timestamp()))
    if k >= len(m1) or m1_ts[k] > now.timestamp() + 900:
        return {"filled": False, "why": "no_data"}
    ts0, o0, _, _, _, sp0, _ = m1[k]
    fill = o0 + sp0 if long_ else o0                 # achat à l'ask, vente au bid
    if not mirror:
        lim = p["limit_price"]
        if (long_ and fill > lim) or ((not long_) and fill < lim):
            return {"filled": False, "why": "outside_zone"}
    if (long_ and fill <= stop) or ((not long_) and fill >= stop):
        return {"filled": False, "why": "beyond_stop"}
    risk = abs(fill - stop)
    for j in range(k, len(m1)):
        ts, o, h, l, c, sp, _ = m1[j]
        if ts > horizon_ts:
            ex = m1[j - 1]
            px = ex[4] if long_ else ex[4] + ex[5]
            r = ((px - fill) if long_ else (fill - px)) / risk
            return {"filled": True, "exit": "time", "r": r, "bars": j - k}
        if long_:
            hit_stop, hit_tgt = l <= stop, h >= target
        else:
            hit_stop, hit_tgt = h + sp >= stop, l + sp <= target
        if hit_stop:                                  # stop avant cible si les deux dans la barre
            return {"filled": True, "exit": "stop", "r": -1.0, "bars": j - k}
        if hit_tgt:
            reward = abs(target - fill)
            return {"filled": True, "exit": "target", "r": reward / risk, "bars": j - k}
    return {"filled": False, "why": "end_of_data"}


# --------------------------------------------------------------------- boucle

def run(folder, symbol):
    cfg = fxconfig.defaults()
    cfg["intraday"]["max_per_day"] = 10
    m1 = load_1m(folder)
    m1_ts = [r[0] for r in m1]
    bars15 = to_15m(m1)
    b15_ts = [b[0] for b in bars15]
    daily = daily_bars(m1)
    first = datetime.fromtimestamp(m1[0][0], UTC)
    last = datetime.fromtimestamp(m1[-1][0], UTC)
    print("barres 1 min : %d, 15 min : %d, jours : %d, de %s à %s" % (
        len(m1), len(bars15), len(daily), first.date(), last.date()), flush=True)

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
                        symbol, "XAUUSD", window, ranges, ctx, cfg, {}, now)
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
                    res = simulate(m1_ts, m1, c, now, horizon)
                    mir = simulate(m1_ts, m1, c, now, horizon, mirror=True)
                    trades.append({"at": now.isoformat(), "side": c["side"], "primary": c["primary"],
                                   "families": c["families"], "score": c["score"],
                                   "session": c["detail"], "rr": c["plan"]["rr"],
                                   "res": res, "mirror": mir})
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
    folder, symbol = sys.argv[1], sys.argv[2]
    trades, diag = run(folder, symbol)
    print("\nDiagnostic des lancements :", json.dumps(diag, ensure_ascii=False, indent=1))
    print("alertes :", len(trades))
    show("GLOBAL (signal)", summarize(trades))
    show("GLOBAL (miroir, sens inversé : témoin)", summarize(trades, field="mirror"))
    show("par famille principale", summarize(trades, key=lambda t: t["primary"]))
    show("par famille présente (peut compter une alerte deux fois)",
         summarize(trades, key=lambda t: t["families"]))
    show("par sens", summarize(trades, key=lambda t: t["side"]))
    show("par score", summarize(trades, key=lambda t: "score %s" % t["score"]))
    show("par mois", summarize(trades, key=lambda t: t["at"][:7]))
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(trades, fh)
