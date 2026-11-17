"""SPIKE JETABLE : retour à la moyenne 1-5 jours (D1) sur 25 marchés + force relative des devises.
Règles fixées avant les résultats. Données Yahoo (adjclose), cache JSON local.
Usage : python -I mr_d1.py [cache.json]
"""
import json, math, os, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

UNIV = ["SPY", "QQQ", "EFA", "EEM", "EWJ", "TLT", "IEF", "GLD", "SLV", "USO", "DBA", "CPER",
        "^GDAXI", "^NDX", "^DJI", "^FTSE", "^N225", "^FCHI",
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; trader-fx/1.0)"}
CACHE = sys.argv[1] if len(sys.argv) > 1 else "mr_cache.json"


def fetch(sym):
    err = None
    for host in ("query2", "query1"):
        try:
            u = "https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=1167609600&period2=%d&interval=1d" % (
                host, sym.replace("=", "%3D").replace("^", "%5E"), time.time())
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())["chart"]["result"][0]
            q = d["indicators"]
            px = (q.get("adjclose") or [{}])[0].get("adjclose") or q["quote"][0]["close"]
            return {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): p for t, p in zip(d["timestamp"], px) if p}
        except Exception as e:
            err = e
    raise err


def load():
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    data = {}
    for s in UNIV:
        try:
            data[s] = fetch(s)
        except Exception as e:
            print("échec", s, type(e).__name__)
        time.sleep(0.3)
    json.dump(data, open(CACHE, "w"))
    return data


COST_BP = {"fx": 1.0, "other": 2.0}        # coût par côté et par jambe, en points de base
TARGET = 0.10


def cost(sym):
    return (COST_BP["fx"] if sym.endswith("=X") else COST_BP["other"]) / 1e4


def sma(c, t, n):
    return sum(c[t - n + 1:t + 1]) / n


def rsi2_series(c):
    out = [None] * len(c)
    ag = al = None
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if ag is None:
            ag, al = g, l
        else:
            ag, al = (ag + g) / 2.0, (al + l) / 2.0      # lissage de Wilder, période 2
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def decide(c, rule, flip):
    """Position décidée à la clôture de chaque jour : liste de -1/0/+1 (machine à états).

    Miroir : mêmes entrées (mêmes jours), sens inverse, même durée maximale ; sortie sur la même règle
    de retour de prix vers la SMA5 (dans le sens opposé)."""
    n = len(c)
    rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, n)]
    rsi = rsi2_series(c)
    dec = [0] * n
    pos, e = 0, 0
    for t in range(200, n):
        if pos == 0:
            s = 0
            if rule in ("A", "A_long"):
                if rsi[t] < 10 and c[t] > sma(c, t, 200):
                    s = 1
                elif rule == "A" and rsi[t] > 90 and c[t] < sma(c, t, 200):
                    s = -1
            elif rule == "B":
                win = rets[t - 59:t + 1]
                m = sum(win) / 60
                sd = math.sqrt(sum((x - m) ** 2 for x in win) / 59)
                r3 = c[t] / c[t - 3] - 1
                z = r3 / (sd * math.sqrt(3)) if sd > 0 else 0.0
                s = 1 if z < -1.5 else (-1 if z > 1.5 else 0)
            if flip:
                s = -s
            if s:
                pos, e = s, t
        else:
            held = t - e
            if rule in ("A", "A_long"):
                if not flip:
                    done = (pos > 0 and c[t] > sma(c, t, 5)) or (pos < 0 and c[t] < sma(c, t, 5)) or held >= 5
                else:
                    done = (pos < 0 and c[t] > sma(c, t, 5)) or (pos > 0 and c[t] < sma(c, t, 5)) or held >= 5
            else:
                done = held >= 3
            if done:
                pos = 0
        dec[t] = pos
    return dec, rets


def run_asset(sym, px, rule, flip, lag):
    ds = sorted(px)
    c = [px[d] for d in ds]
    dec, rets = decide(c, rule, flip)
    n = len(c)
    cst = cost(sym)
    daily, trades = {}, []
    prev, entry = 0, None
    for i in range(201, n):
        j = i - 1 - lag
        w = dec[j] if j >= 0 else 0
        win = rets[max(1, i - 60):i]
        m = sum(win) / len(win)
        vol = math.sqrt(sum((x - m) ** 2 for x in win) / max(1, len(win) - 1)) * math.sqrt(252)
        sc = min(TARGET / vol, 3.0) if vol > 0 else 0.0
        daily[ds[i]] = w * sc * rets[i] - cst * sc * abs(w - prev)
        if w != prev:
            if prev != 0 and entry is not None:
                g = prev * (c[i - 1] / entry[1] - 1)
                trades.append((entry[0], prev, g - 2 * cst, g, i - entry[2]))
                entry = None
            if w != 0:
                entry = (ds[i - 1], c[i - 1], i)
        prev = w
    return daily, trades


def sharpe(v):
    if len(v) < 100:
        return None
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    sr = m / sd * math.sqrt(252) if sd else 0.0
    se = math.sqrt((1 + sr * sr / 2) / (len(v) / 252.0))
    return sr, 1.96 * se, m * 252 * 100


PER = [("2007-15", 2007, 2015), ("2016-22", 2016, 2022), ("2023-26", 2023, 2026), ("TOUT", 2000, 2100)]


def report(label, daily_by_asset, trades_all):
    port = defaultdict(list)
    for s, dd in daily_by_asset.items():
        for d, x in dd.items():
            port[d].append(x)
    port = {d: sum(v) / len(daily_by_asset) for d, v in port.items()}
    line = []
    for _, lo, hi in PER:
        v = [x for d, x in sorted(port.items()) if lo <= int(d[:4]) <= hi]
        s = sharpe(v)
        line.append("n/a" if s is None else "%5.2f±%.2f" % (s[0], s[1]))
    nt = len(trades_all)
    years = (len(port) / 252.0) or 1
    net = [t[2] * 1e4 for t in trades_all]
    gross = [t[3] * 1e4 for t in trades_all]
    sh = sum(1 for t in trades_all if t[1] < 0)
    print("%-24s Sharpe %s | trades %5d (%.1f/sem) net %6.1f pb brut %6.1f pb courts %d%% duree %.1f j" % (
        label, " ".join(line), nt, nt / (years * 52), sum(net) / max(nt, 1), sum(gross) / max(nt, 1),
        100 * sh // max(nt, 1), sum(t[4] for t in trades_all) / max(nt, 1)))


def mean_reversion(data):
    for rule, title in (("A", "A  RSI(2)<10 / >90 + filtre SMA200, sortie SMA5 ou 5 j (long+court)"),
                        ("A_long", "A' idem, long seulement"),
                        ("B", "B  rendement 3 j z<-1.5 / >+1.5, tenue 3 j, sans filtre (long+court)")):
        print("\n=== %s" % title)
        for lag, ln in ((0, "entree cloture signal"), (1, "entree cloture J+1")):
            for flip in (False, True):
                da, ta = {}, []
                for s in data:
                    d, t = run_asset(s, data[s], rule, flip, lag)
                    da[s] = d
                    ta += t
                report(("miroir " if flip else "signal ") + ln, da, ta)
    print("\n--- sensibilite aux couts (regle A, lag 0, signal) : couts x3")
    save = dict(COST_BP)
    COST_BP["fx"], COST_BP["other"] = 3.0, 6.0
    da, ta = {}, []
    for s in data:
        d, t = run_asset(s, data[s], "A", False, 0)
        da[s] = d
        ta += t
    report("signal cout x3", da, ta)
    COST_BP.update(save)


# ----------------------------------------------------------------- force relative des devises

CCY = {"EUR": ("EURUSD=X", 1), "GBP": ("GBPUSD=X", 1), "AUD": ("AUDUSD=X", 1), "NZD": ("NZDUSD=X", 1),
       "JPY": ("USDJPY=X", -1), "CAD": ("USDCAD=X", -1), "CHF": ("USDCHF=X", -1)}


def fx_strength(data):
    ds = sorted(set.intersection(*[set(data[v[0]]) for v in CCY.values()]))
    lv = {k: [math.log(data[v[0]][d]) * v[1] for d in ds] for k, v in CCY.items()}    # log valeur de la devise en USD
    n = len(ds)
    ks = list(CCY)
    fxc = COST_BP["fx"] / 1e4
    print("\n=== Force relative des devises : %d devises vs USD, %d jours (%s -> %s)" % (len(ks), n, ds[0], ds[-1]))
    print("signal : long la plus forte / court la plus faible sur L jours ; tenue H jours ; 1 nouveau trade par jour (~5/sem)")
    for L in (1, 5, 20):
        for H in (1, 3, 5):
            for flip in (False, True):
                trades, daily = [], defaultdict(float)
                for t in range(L, n - H - 1):
                    r = {k: lv[k][t] - lv[k][t - L] for k in ks}
                    top = max(r, key=r.get)
                    bot = min(r, key=r.get)
                    a, b = (bot, top) if flip else (top, bot)
                    g = (lv[a][t + H] - lv[a][t]) - (lv[b][t + H] - lv[b][t])
                    trades.append((ds[t], 1, g - 4 * fxc, g, H))
                    for k in range(1, H + 1):
                        d = ds[t + k]
                        daily[d] += ((lv[a][t + k] - lv[a][t + k - 1]) - (lv[b][t + k] - lv[b][t + k - 1])) / H
                    daily[ds[t + 1]] -= 4 * fxc / H
                per = []
                for _, lo, hi in PER:
                    vv = [x for d, x in sorted(daily.items()) if lo <= int(d[:4]) <= hi]
                    s = sharpe(vv)
                    per.append("n/a" if s is None else "%5.2f±%.2f" % (s[0], s[1]))
                nt = len(trades)
                print("L=%2d H=%d %-7s Sharpe %s | net %5.1f pb brut %5.1f pb" % (
                    L, H, "miroir" if flip else "signal", " ".join(per),
                    sum(t[2] for t in trades) / nt * 1e4, sum(t[3] for t in trades) / nt * 1e4))


if __name__ == "__main__":
    data = load()
    print("series :", len(data), "; SPY barres :", len(data.get("SPY", {})))
    print("colonnes Sharpe : 2007-15 | 2016-22 | 2023-26 | tout ; couts %s pb par cote et par jambe (fx / autres)" % COST_BP)
    mean_reversion(data)
    fx_strength(data)
