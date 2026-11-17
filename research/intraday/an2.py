import csv, sys, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta
P = sys.argv[1]
rows = list(csv.reader(open(P, encoding="utf-8-sig"), delimiter=";"))
print("en-tête :", rows[0]); rows = rows[1:]
f = lambda x: float(x.replace(" ", "")) if x not in ("", None) else 0.0
pos, bal = [], []
for r in rows:
    if len(r) < 11: continue
    if r[1] == "Balance": bal.append((r[0], f(r[10]))); continue
    try:
        pos.append(dict(t_in=datetime.strptime(r[0], "%Y.%m.%d %H:%M:%S"), side=r[1], vol=f(r[2]), sym=r[3], pin=f(r[4]),
                        t_out=datetime.strptime(r[6], "%Y.%m.%d %H:%M:%S"), pout=f(r[7]), comm=f(r[8]), swap=f(r[9]), pnl=f(r[10])))
    except ValueError as e: print("ligne ignorée", r[:3])
net = lambda p: p["pnl"] + p["comm"] + p["swap"]
print("opérations de solde :", bal)
print("positions :", len(pos), "; du", min(p["t_in"] for p in pos), "au", max(p["t_out"] for p in pos))
print("symboles :", Counter(p["sym"] for p in pos).most_common(12))
print("sens :", dict(Counter(p["side"] for p in pos)))
print("NET %.2f (brut %.2f, comm %.2f, swap %.2f)" % (sum(net(p) for p in pos), sum(p["pnl"] for p in pos), sum(p["comm"] for p in pos), sum(p["swap"] for p in pos)))
w = [net(p) for p in pos if net(p) > 0]; l = [net(p) for p in pos if net(p) <= 0]
print("gagnantes %d (%.0f%%) gain moyen %.2f ; perdantes %d perte moyenne %.2f ; pire %.2f ; meilleur %.2f ; PF %.2f" % (len(w), 100*len(w)/len(pos), st.mean(w), len(l), st.mean(l) if l else 0, min(net(p) for p in pos), max(net(p) for p in pos), sum(w)/-sum(l) if l and sum(l) else 0))
print("lots :", dict(sorted(Counter(p["vol"] for p in pos).items())[:15]))
print("durée médiane (min) %.0f ; max %.0f" % (st.median((p["t_out"] - p["t_in"]).total_seconds()/60 for p in pos), max((p["t_out"] - p["t_in"]).total_seconds()/60 for p in pos)))
m = defaultdict(float)
for p in pos: m[p["t_out"].strftime("%Y-%m")] += net(p)
print("net par mois :", {k: round(v, 1) for k, v in sorted(m.items())})
print("heure d'entrée (serveur) :", dict(sorted(Counter(p["t_in"].strftime("%H") for p in pos).items())))
print("jour de semaine d'entrée :", dict(sorted(Counter(p["t_in"].weekday() for p in pos).items())))
print("minute d'entrée :", dict(Counter(p["t_in"].minute for p in pos).most_common(8)))
print("seconde d'entrée :", dict(Counter(p["t_in"].second for p in pos).most_common(5)))
