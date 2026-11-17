import json, math, statistics as st, sys
from collections import defaultdict
syms = ["EURUSD","GBPUSD","USDJPY","XAUUSD","DAX","NAS100","US30"]
T = []
for s in syms:
    for t in json.load(open("setups_%s.json" % s))["trades"]:
        t["s"] = s; T.append(t)
def ci(v):
    m = st.mean(v); se = st.stdev(v) / math.sqrt(len(v)); return m, m - 1.96 * se, m + 1.96 * se
for var in sorted({t["v"] for t in T}):
    V = [t for t in T if t["v"] == var and t["mirror"] is not None]
    print("\n== " + var)
    for lab, lo, hi in (("exploration 2016/18-2022", 0, 2022), ("confirmation 2023-2026", 2023, 9999), ("TOUT", 0, 9999)):
        X = [t for t in V if lo <= int(t["at"][:4]) <= hi]
        r = [t["r"] for t in X]; m = [t["mirror"] for t in X]
        d = [a - b for a, b in zip(r, m)]
        w = sum(1 for t in X if t["k"] == "target") / len(X)
        a, b, c = ci(r); dm, dl, dh = ci(d)
        print("  %-26s n=%5d cible %4.1f%%  R moyen %6.3f [%6.3f ; %6.3f]  miroir %6.3f  signal-miroir %6.3f [%6.3f ; %6.3f]" % (
            lab, len(X), 100*w, a, b, c, st.mean(m), dm, dl, dh))
    print("  par symbole (R moyen, tout) : " + ", ".join(
        "%s %.3f" % (s, st.mean([t["r"] for t in V if t["s"] == s])) for s in syms))
