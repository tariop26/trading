"""SPIKE JETABLE : tendance D1 sur 18 marchés diversifiés (Yahoo, adjclose). Règles fixées d'avance."""
import json, math, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

UNIV = {"actions": ["SPY", "QQQ", "EFA", "EEM", "EWJ"], "taux": ["TLT", "IEF"],
        "matieres": ["GLD", "SLV", "USO", "DBA", "CPER"],
        "devises": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X"]}
UA = {"User-Agent": "Mozilla/5.0 (compatible; trader-fx/1.0)"}

def fetch(sym):
    for host in ("query2", "query1"):
        try:
            u = "https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=1167609600&period2=%d&interval=1d" % (host, sym.replace("=", "%3D"), time.time())
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())["chart"]["result"][0]
            ts = d["timestamp"]; q = d["indicators"]
            px = (q.get("adjclose") or [{}])[0].get("adjclose") or q["quote"][0]["close"]
            return {datetime.fromtimestamp(t, timezone.utc).date(): p for t, p in zip(ts, px) if p}
        except Exception as e:
            err = e
    raise err

data, cls = {}, {}
for c, syms in UNIV.items():
    for s in syms:
        try:
            data[s] = fetch(s); cls[s] = c
        except Exception as e:
            print("échec", s, type(e).__name__)
        time.sleep(0.3)
print("charges :", len(data), "; barres SPY :", len(data["SPY"]), "; ecart median jours :", sorted((b-a).days for a, b in zip(sorted(data["SPY"]), sorted(data["SPY"])[1:]))[len(data["SPY"])//2])

COST = 0.0002          # 2 pb par unité de poids échangée
TARGET = 0.10          # volatilité cible par actif (annualisée)

def rules():
    yield "SMA 10/50", lambda c, t: (sum(c[t-9:t+1])/10 - sum(c[t-49:t+1])/50), 50
    yield "SMA 20/100", lambda c, t: (sum(c[t-19:t+1])/20 - sum(c[t-99:t+1])/100), 100
    yield "momentum 252 j", lambda c, t: c[t] - c[t-252], 253
    yield "toujours long (témoin)", lambda c, t: 1.0, 61

def asset_pnl(px, fn, need):
    ds = sorted(px); c = [px[d] for d in ds]
    out, w_prev = {}, 0.0
    rets = [0.0] + [c[i]/c[i-1] - 1 for i in range(1, len(c))]
    for t in range(max(need, 61), len(c) - 1):
        win = rets[t-59:t+1]; m = sum(win)/60
        vol = math.sqrt(sum((x-m)**2 for x in win)/59) * math.sqrt(252)
        sig = fn(c, t)
        w = (1 if sig > 0 else -1 if sig < 0 else 0) * min(TARGET / vol, 3.0) if vol > 0 else 0.0
        out[ds[t+1]] = w * rets[t+1] - COST * abs(w - w_prev)
        w_prev = w
    return out

def stats(v):
    if len(v) < 100: return None
    m = sum(v)/len(v); sd = math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))
    sr = m/sd*math.sqrt(252) if sd else 0.0
    se = math.sqrt((1 + sr*sr/2) / (len(v)/252.0))
    eq = pk = dd = 0.0
    for x in v:
        eq += x; pk = max(pk, eq); dd = min(dd, eq - pk)
    return sr, 1.96*se, m*252*100, sd*math.sqrt(252)*100, dd*100

def fmt(label, series, lo, hi):
    v = [x for d, x in sorted(series.items()) if lo <= d.year <= hi]
    s = stats(v)
    return "  %-22s " % label + ("n/a" if s is None else "Sharpe %5.2f ±%.2f  rend %5.1f%%/an  vol %4.1f%%  DD %6.1f%%" % s)

PER = [("2007-2015", 2007, 2015), ("2016-2022 (exploration)", 2016, 2022), ("2023-2026 (confirmation)", 2023, 2026), ("TOUT", 2000, 2100)]
for name, fn, need in rules():
    per = {s: asset_pnl(data[s], fn, need) for s in data}
    port = defaultdict(list)
    for s in per:
        for d, x in per[s].items(): port[d].append(x)
    port = {d: sum(v)/len(v) for d, v in port.items()}
    print("\n=== %s  (%d marchés)" % (name, len(per)))
    for lab, lo, hi in PER: print(fmt(lab, port, lo, hi))
    if name == "SMA 20/100":
        print("  par marché (Sharpe tout) :", ", ".join("%s %.2f" % (s, (stats(list(per[s].values())) or [float('nan')])[0]) for s in per))
        for c in UNIV:
            sub = defaultdict(list)
            for s in per:
                if cls[s] == c:
                    for d, x in per[s].items(): sub[d].append(x)
            sub = {d: sum(v)/len(v) for d, v in sub.items()}
            print(fmt("classe " + c, sub, 2000, 2100))
