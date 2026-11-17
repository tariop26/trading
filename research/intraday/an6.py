import bisect, math, statistics as st
exec(open("an5.py", encoding="utf-8").read().split("# 1) accord")[0])
# sigma de la bande (en points) et ATR 5 min au moment de l'entrée ; sorties exprimées en sigma
bts, bc, bh, bl, cb = [], [], [], [], None
for i in range(len(ts)):
    b = ts[i] // 300 * 300
    if cb != b: bts.append(b); bc.append(c[i]); bh.append(h[i]); bl.append(l[i]); cb = b
    else: bc[-1] = c[i]; bh[-1] = max(bh[-1], h[i]); bl[-1] = min(bl[-1], l[i])
ps_, pq_ = [0.0], [0.0]
for x in bc: ps_.append(ps_[-1] + x); pq_.append(pq_[-1] + x * x)
def sigma_at(T):
    i = bisect.bisect_left(bts, T // 300 * 300) - 1
    if i < 160: return None
    s_, q_ = ps_[i+1] - ps_[i-159], pq_[i+1] - pq_[i-159]; m_ = s_ / 160; v_ = q_ / 160 - m_ * m_
    return math.sqrt(v_) if v_ > 0 else None
def atr_at(T, n=14):
    i = bisect.bisect_left(bts, T // 300 * 300) - 1
    if i < n + 1: return None
    return st.mean(max(bh[j] - bl[j], abs(bh[j] - bc[j-1]), abs(bl[j] - bc[j-1])) for j in range(i - n + 1, i + 1))
rows = []
for p in pos:
    if not (datetime(2024, 11, 1) <= p["t_in"] <= datetime(2026, 9, 28)): continue
    k, T = kk(p["t_in"])
    if k is None: continue
    s_, a_ = sigma_at(T), atr_at(T)
    if not s_ or not a_: continue
    pts = (p["pout"] - p["pin"]) * sg(p)
    rows.append((pts, pts / s_, pts / a_, (p["t_out"] - p["t_in"]).total_seconds() / 60, s_, a_))
print("n positions avec contexte :", len(rows), "| sigma de bande médian %.1f pts ; ATR 5 min médian %.2f pts" % (st.median(r[4] for r in rows), st.median(r[5] for r in rows)))
def hist(vals, w, lo, hi):
    return sorted(Counter(max(lo, min(hi, math.floor(v / w) * w)) for v in vals).items())
print("\nsortie en unités de sigma (pas 0,25) :", [(round(a, 2), n) for a, n in hist([r[1] for r in rows], 0.25, -3, 3)])
print("sortie en unités d'ATR 5 min (pas 1) :", [(a, n) for a, n in hist([r[2] for r in rows], 1, -10, 12)])
print("durée (min) quantiles 10/25/50/75/90 :", [round(q([r[3] for r in rows], a), 1) for a in (.1, .25, .5, .75, .9)])
w_ = [r for r in rows if r[0] > 1.5]; l_ = [r for r in rows if r[0] < -1.5]
print("gains > 1,5 pt : n=%d, médian %.1f pts = %.2f sigma = %.1f ATR ; pertes < -1,5 pt : n=%d, médian %.1f pts = %.2f sigma = %.1f ATR" % (
    len(w_), st.median(r[0] for r in w_), st.median(r[1] for r in w_), st.median(r[2] for r in w_),
    len(l_), st.median(r[0] for r in l_), st.median(r[1] for r in l_), st.median(r[2] for r in l_)))
small = [r for r in rows if abs(r[0]) <= 1.5]
print("sorties 'scratch' |pts|<=1,5 : %d (%.0f %%), durée médiane %.0f min" % (len(small), 100 * len(small) / len(rows), st.median(r[3] for r in small)))
