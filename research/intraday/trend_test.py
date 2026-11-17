"""SPIKE JETABLE : tendance H1/H4/D1, croisement de moyennes, règles fixées d'avance."""
import math, os, sys
from collections import defaultdict
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R

BASE = os.path.dirname(os.path.abspath(__file__))
SYMS = ["EURUSD", "GBPUSD", "USDJPY"]
RULES = [(10, 50), (20, 100)]
TFS = {"H1": 3600, "H4": 14400, "D1": 86400}

def bars_tf(m1, sec):
    ts, o, h, l, c, sp = m1
    out, cur = [], None
    for i in range(len(ts)):
        k = ts[i] // sec * sec
        if cur is None or cur[0] != k:
            if cur is not None: out.append(tuple(cur))
            cur = [k, c[i], sp[i]]
        else:
            cur[1], cur[2] = c[i], sp[i]
    if cur: out.append(tuple(cur))
    return out          # (ts, close, spread à la clôture)

def sma_cross_pnl(bars, fast, slow):
    """-> {date: pnl} ; pnl en fraction du notionnel, coût = demi-spread par unité échangée."""
    closes = [b[1] for b in bars]
    n = len(closes)
    daily = defaultdict(float)
    cs = [0.0]
    for x in closes: cs.append(cs[-1] + x)
    pos_prev, trades = 0, 0
    for t in range(slow - 1, n - 1):
        f = (cs[t + 1] - cs[t + 1 - fast]) / fast
        s = (cs[t + 1] - cs[t + 1 - slow]) / slow
        pos = 1 if f > s else (-1 if f < s else pos_prev)
        cost = abs(pos - pos_prev) * (bars[t][2] / 2) / closes[t]
        if pos != pos_prev: trades += 1
        pnl = pos * (closes[t + 1] - closes[t]) / closes[t] - cost
        d = datetime.fromtimestamp(bars[t + 1][0], timezone.utc).date()
        daily[d] += pnl
        pos_prev = pos
    return daily, trades

def stats(series):
    v = list(series)
    if len(v) < 50: return None
    m = sum(v) / len(v); sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    sr = m / sd * math.sqrt(260) if sd else 0.0
    yrs = len(v) / 260.0
    se = math.sqrt((1 + sr * sr / 2) / yrs)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in v:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return sr, se, m * 260 * 100, sd * math.sqrt(260) * 100, mdd * 100

def line(label, d, lo=None, hi=None):
    s = stats([x for k, x in sorted(d.items()) if (lo is None or k.year >= lo) and (hi is None or k.year <= hi)])
    if s is None: return "%-30s n/a" % label
    sr, se, ar, vol, mdd = s
    return "%-30s Sharpe %5.2f ±%.2f  rend %5.1f%%/an  vol %4.1f%%  DD %6.1f%%" % (label, sr, 1.96 * se, ar, vol, mdd)

data = {}
for s in SYMS:
    m1, _ = R.load_1m(os.path.join(BASE, "fx_data", s))
    data[s] = {tf: bars_tf(m1, sec) for tf, sec in TFS.items()}
    print("chargé", s, flush=True)
for tf in TFS:
    for fast, slow in RULES:
        res, tr = {}, {}
        for s in SYMS:
            res[s], tr[s] = sma_cross_pnl(data[s][tf], fast, slow)
        port = defaultdict(float)
        for s in SYMS:
            for k, x in res[s].items(): port[k] += x / len(SYMS)
        print("\n=== %s  SMA %d/%d  (trades/an/symbole : %s)" % (
            tf, fast, slow, ", ".join("%s %.0f" % (s, tr[s] / 10.8) for s in SYMS)))
        print(line("portefeuille 3 paires 2016-2022", port, 2016, 2022))
        print(line("portefeuille 3 paires 2023-2026", port, 2023, 2026))
        print(line("portefeuille 3 paires TOUT", port))
        for s in SYMS: print(line("  " + s + " TOUT", res[s]))
