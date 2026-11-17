import json, math, statistics as st
def ci(v):
    m = st.mean(v); se = st.stdev(v) / math.sqrt(len(v)); return m, m - 1.96 * se, m + 1.96 * se
print("=== SETUPS (mêmes entrées ; BE à 30 % de la distance au TP) ===")
S = ["EURUSD","GBPUSD","USDJPY","XAUUSD","DAX","NAS100","US30"]
T = []
for s in S:
    for t in json.load(open("setups_%s.json" % s))["trades"]:
        if t.get("rbe") is not None and t.get("mirror") is not None: t["s"] = s; T.append(t)
for var in sorted({t["v"] for t in T}):
    V = [t for t in T if t["v"] == var]
    out = []
    for lab, lo, hi in (("2016/18-2022", 0, 2022), ("2023-2026", 2023, 9999), ("TOUT", 0, 9999)):
        X = [t for t in V if lo <= int(t["at"][:4]) <= hi]
        a = ci([t["r"] for t in X]); b = ci([t["rbe"] for t in X])
        out.append("%s sans BE %+.3f / BE %+.3f" % (lab, a[0], b[0]))
    X = V; b = ci([t["rbe"] for t in X]); d = ci([t["rbe"] - t["r"] for t in X])
    print("%s (n=%d) : %s | BE tout [%+.3f ; %+.3f] ; BE moins sans BE %+.3f [%+.3f ; %+.3f] ; sorties BE %.0f%% ; cible %.1f%% -> %.1f%%" % (
        var, len(V), " ; ".join(out), b[1], b[2], d[0], d[1], d[2],
        100 * sum(1 for t in V if t["kbe"] == "be") / len(V),
        100 * sum(1 for t in V if t["k"] == "target") / len(V), 100 * sum(1 for t in V if t["kbe"] == "target") / len(V)))
print("\n=== ALERTES 15 MIN (3 paires, 2016-2026) ===")
A = []
for s in ("EURUSD", "GBPUSD", "USDJPY"):
    A += [t for t in json.load(open("%s_be.json" % s))["trades"] if t["res"].get("filled") and t["resbe"].get("filled")]
for lab, lo, hi in (("2016-2022", 0, 2022), ("2023-2026", 2023, 9999), ("TOUT", 0, 9999)):
    X = [t for t in A if lo <= int(t["at"][:4]) <= hi]
    a = ci([t["res"]["r"] for t in X]); b = ci([t["resbe"]["r"] for t in X]); d = ci([t["resbe"]["r"] - t["res"]["r"] for t in X])
    print("%-10s n=%6d  sans BE %+.3f [%+.3f ; %+.3f]   BE 30%% %+.3f [%+.3f ; %+.3f]   BE-sans %+.3f [%+.3f ; %+.3f]" % (
        lab, len(X), a[0], a[1], a[2], b[0], b[1], b[2], d[0], d[1], d[2]))
print("sorties BE : %.0f%% ; cible : %.1f%% -> %.1f%%" % (100 * sum(1 for t in A if t["resbe"]["exit"] == "be") / len(A),
      100 * sum(1 for t in A if t["res"]["exit"] == "target") / len(A), 100 * sum(1 for t in A if t["resbe"]["exit"] == "target") / len(A)))
