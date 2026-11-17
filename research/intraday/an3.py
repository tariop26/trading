import csv, sys, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta
P = r"C:\Users\m.poirat\trading\2265877.positions.csv"
rows = list(csv.reader(open(P, encoding="utf-8-sig"), delimiter=";"))[1:]
f = lambda x: float(x) if x else 0.0
pos = []
for r in rows:
    if len(r) < 11 or r[1] == "Balance": continue
    pos.append(dict(t_in=datetime.strptime(r[0], "%Y.%m.%d %H:%M:%S"), side=r[1], vol=f(r[2]), pin=f(r[4]),
                    t_out=datetime.strptime(r[6], "%Y.%m.%d %H:%M:%S"), pout=f(r[7]), net=f(r[10]) + f(r[8]) + f(r[9])))
pos.sort(key=lambda x: x["t_in"])
for p in pos:
    p["pts"] = (p["pout"] - p["pin"]) * (1 if p["side"] == "Buy" else -1)
pts = [p["pts"] for p in pos]
q = lambda v, a: sorted(v)[int(a * (len(v) - 1))]
print("points par position : min %.1f  P5 %.1f  P25 %.1f  médiane %.1f  P75 %.1f  P95 %.1f  max %.1f" % (min(pts), q(pts, .05), q(pts, .25), st.median(pts), q(pts, .75), q(pts, .95), max(pts)))
print("gagnantes : points moyens %.2f ; perdantes : %.2f" % (st.mean([x for x in pts if x > 0]), st.mean([x for x in pts if x <= 0])))
print("valeurs de points les plus fréquentes (arrondi 0,5) :", Counter(round(x * 2) / 2 for x in pts).most_common(12))
# paniers : même sens, sorties à <= 5 s
ps = sorted(pos, key=lambda x: (x["side"], x["t_out"]))
B, cur = [], []
for p in ps:
    if cur and cur[-1]["side"] == p["side"] and abs((p["t_out"] - cur[-1]["t_out"]).total_seconds()) <= 5: cur.append(p)
    else:
        if cur: B.append(cur)
        cur = [p]
if cur: B.append(cur)
B.sort(key=lambda b: min(x["t_in"] for x in b))
sz = Counter(len(b) for b in B)
print("\npaniers :", len(B), "| taille (nb de positions) :", dict(sorted(sz.items())))
bn = [sum(x["net"] for x in b) for b in B]
print("paniers gagnants %.0f%% ; net moyen %.2f ; pire %.2f ; meilleur %.2f" % (100 * sum(1 for x in bn if x > 0) / len(bn), st.mean(bn), min(bn), max(bn)))
multi = [b for b in B if len(b) >= 2]
print("paniers à >= 2 positions :", len(multi), "; net moyen %.2f ; gagnants %.0f%%" % (st.mean(sum(x["net"] for x in b) for b in multi), 100 * sum(1 for b in multi if sum(x["net"] for x in b) > 0) / len(multi)))
single = [b for b in B if len(b) == 1]
print("paniers à 1 position :", len(single), "; net moyen %.2f ; gagnants %.0f%%" % (st.mean(sum(x["net"] for x in b) for b in single), 100 * sum(1 for b in single if sum(x["net"] for x in b) > 0) / len(single)))
# espacement des renforts dans les paniers multiples
gaps_t, gaps_p = [], []
for b in multi:
    b2 = sorted(b, key=lambda x: x["t_in"])
    for a, c in zip(b2, b2[1:]):
        gaps_t.append((c["t_in"] - a["t_in"]).total_seconds() / 60)
        gaps_p.append((c["pin"] - a["pin"]) * (-1 if a["side"] == "Buy" else 1))   # >0 = renfort à un prix pire (contre la position)
print("renforts : délai médian %.1f min (P25 %.1f, P75 %.1f) ; écart de prix médian %.2f pts, part à prix PIRE %.0f%%" % (st.median(gaps_t), q(gaps_t, .25), q(gaps_t, .75), st.median(gaps_p), 100 * sum(1 for g in gaps_p if g > 0) / len(gaps_p)))
print("écart de prix des renforts (arrondi 1) :", Counter(round(x) for x in gaps_p).most_common(10))
long_b = sorted(B, key=lambda b: -(max(x["t_out"] for x in b) - min(x["t_in"] for x in b)).total_seconds())[:6]
print("\n6 paniers les plus longs :")
for b in long_b:
    t0 = min(x["t_in"] for x in b); t1 = max(x["t_out"] for x in b)
    print("  %s %-4s %2d pos, %6.0f h, net %8.2f" % (t0, b[0]["side"], len(b), (t1 - t0).total_seconds() / 3600, sum(x["net"] for x in b)))
print("\n10 pires positions :")
for p in sorted(pos, key=lambda x: x["net"])[:10]:
    print("  %s %-4s %.2f lot  entrée %.2f sortie %.2f  %.1f pts  net %.2f  durée %.0f min" % (p["t_in"], p["side"], p["vol"], p["pin"], p["pout"], p["pts"], p["net"], (p["t_out"] - p["t_in"]).total_seconds() / 60))
