import json, statistics as st, math, sys
t = json.load(open(sys.argv[1]))
f = [x for x in t if x["res"].get("filled") and x["mirror"].get("filled")]
r = [x["res"]["r"] for x in f]; m = [x["mirror"]["r"] for x in f]
d = [a-b for a,b in zip(r,m)]
def ci(v): s = st.stdev(v)/math.sqrt(len(v)); return st.mean(v), st.mean(v)-1.96*s, st.mean(v)+1.96*s
print("n apparies", len(f))
print("R signal  moy %.3f  IC95 [%.3f ; %.3f]" % ci(r))
print("R miroir  moy %.3f  IC95 [%.3f ; %.3f]" % ci(m))
print("signal - miroir moy %.3f  IC95 [%.3f ; %.3f]" % ci(d))
days = {}
for x in f: days.setdefault(x["at"][:10], []).append(x["res"]["r"])
dm = [sum(v) for v in days.values()]
print("jours avec alerte", len(days), " R/jour moy %.2f  IC95 [%.2f ; %.2f]" % ci(dm))
