import bisect, math, statistics as st, sys
exec(open("an4.py", encoding="utf-8").read().split("print(\"données")[0])      # réutilise le chargement
def kk(naive):
    T = int(R.server_to_utc(naive).timestamp()); k = bisect.bisect_left(ts, T)
    return (k, T) if k < len(ts) and ts[k] - T <= 90 else (None, T)
# 1ère entrée de chaque grappe (même sens, <= 120 s)
cl, last = [], {}
for p in pos:
    s = p["side"]
    if s in last and (p["t_in"] - last[s]["t_in"]).total_seconds() <= 120: last[s] = p; continue
    cl.append(p); last[s] = p
rng = [p for p in cl if datetime(2024, 11, 1) <= p["t_in"] <= datetime(2026, 9, 28)]
print("grappes d'entrée : %d au total, %d dans la période couverte par nos données" % (len(cl), len(rng)))
sg = lambda p: 1 if p["side"] == "Buy" else -1
# 1) accord entre le sens et le mouvement précédent
print("\n1) accord sens / mouvement précédent (>50 % = momentum, <50 % = contre-tendance)")
for mins in (5, 15, 30, 60, 120, 240, 1440):
    ok = tot = 0
    for p in rng:
        k, T = kk(p["t_in"]); 
        if k is None: continue
        j = bisect.bisect_left(ts, T - mins * 60)
        if j >= k or ts[j] < T - mins * 60 - 300: continue
        d = o[k] - o[j]
        if d == 0: continue
        tot += 1; ok += ((d > 0) == (sg(p) > 0))
    z = (ok - tot / 2) / math.sqrt(tot / 4)
    print("   %5d min : %4d/%4d = %.0f %%  (z=%+.1f)" % (mins, ok, tot, 100 * ok / tot, z))
# 2) rendement futur signé (pts) depuis le prix 1 min à l'entrée
print("\n2) variation signée du prix après l'entrée (points d'or, spread non déduit ; spread moyen ~ %.2f pt)" % st.mean(sp[-200000:]))
for mins in (1, 5, 15, 30, 60, 240):
    v = []
    for p in rng:
        k, T = kk(p["t_in"])
        if k is None: continue
        j = bisect.bisect_left(ts, T + mins * 60)
        if j < len(ts) and ts[j] - (T + mins * 60) <= 120: v.append(sg(p) * (o[j] - o[k]))
    m, se = st.mean(v), st.stdev(v) / math.sqrt(len(v))
    print("   +%3d min : moyenne %+.2f pts  (t=%+.1f, n=%d) ; part positive %.0f %%" % (mins, m, m / se, len(v), 100 * sum(1 for x in v if x > 0) / len(v)))
# 3) heures d'entrée en UTC
hrs = Counter(R.server_to_utc(p["t_in"]).hour for p in cl)
print("\n3) heure UTC des grappes :", dict(sorted(hrs.items())))
# 4) z de Bollinger 5 min (160)
bts, bc, cb = [], [], None
for i in range(len(ts)):
    b = ts[i] // 300 * 300
    if cb != b: bts.append(b); bc.append(c[i]); cb = b
    else: bc[-1] = c[i]
ps_, pq_ = [0.0], [0.0]
for x in bc: ps_.append(ps_[-1] + x); pq_.append(pq_[-1] + x * x)
zb = {1: [], -1: []}
for p in rng:
    k, T = kk(p["t_in"])
    if k is None: continue
    i = bisect.bisect_left(bts, T // 300 * 300) - 1
    if i < 160: continue
    s_, q_ = ps_[i+1] - ps_[i-159], pq_[i+1] - pq_[i-159]; m_ = s_ / 160; v_ = q_ / 160 - m_ * m_
    if v_ > 0: zb[sg(p)].append((o[k] - m_) / math.sqrt(v_))
print("\n4) z de Bollinger 5 min (160) à l'entrée : achats moyenne %+.2f (n=%d), ventes %+.2f (n=%d) ; |z|>=2,8 : %.0f %%" % (
    st.mean(zb[1]), len(zb[1]), st.mean(zb[-1]), len(zb[-1]), 100 * sum(1 for x in zb[1] + zb[-1] if abs(x) >= 2.8) / len(zb[1] + zb[-1])))
# 5) position dans la fourchette des 4 dernières heures et nouveaux extrêmes
print("\n5) position du prix dans la fourchette des N dernières minutes (0 = plus bas, 1 = plus haut)")
for mins in (60, 240, 1440):
    pr = {1: [], -1: []}; ext = {1: [0, 0], -1: [0, 0]}
    for p in rng:
        k, T = kk(p["t_in"])
        if k is None: continue
        j = bisect.bisect_left(ts, T - mins * 60)
        if j >= k - 10: continue
        hi, lo = max(h[j:k]), min(l[j:k])
        if hi > lo: pr[sg(p)].append((o[k] - lo) / (hi - lo))
        ext[sg(p)][0] += 1; ext[sg(p)][1] += (o[k] >= hi if sg(p) > 0 else o[k] <= lo)
    print("   %5d min : achats %.2f (n=%d, au plus haut %.0f %%) ; ventes %.2f (n=%d, au plus bas %.0f %%)" % (
        mins, st.mean(pr[1]), len(pr[1]), 100 * ext[1][1] / max(1, ext[1][0]), st.mean(pr[-1]), len(pr[-1]), 100 * ext[-1][1] / max(1, ext[-1][0])))
