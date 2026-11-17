import bisect, math, statistics as st
exec(open("an5.py", encoding="utf-8").read().split("# 1) accord")[0])
q = lambda v, a: sorted(v)[int(a * (len(v) - 1))]
E = [p for p in rng]
print("grappes d'entrée :", len(E))
# 1) rythme des entrées : minute modulo 5 / 15 / 30 et seconde
tmin = [R.server_to_utc(p["t_in"]) for p in E]
for m in (5, 15, 30, 60):
    c_ = Counter(t.minute % m for t in tmin)
    print("minute mod %2d : part des entrées dans les 2 premières minutes de la barre : %.0f %% (hasard %.0f %%)" % (m, 100 * sum(v for k, v in c_.items() if k <= 1) / len(E), 200 / m))
print("seconde d'entrée <= 3 s : %.0f %%" % (100 * sum(1 for t in tmin if t.second <= 3) / len(E)))
# 2) bougies : la dernière bougie clôturée de chaque unité de temps va-t-elle dans le sens ? et casse-t-elle le plus haut/bas de la précédente ?
def bars_tf(sec):
    out, cur = [], None
    for i in range(len(ts)):
        b = ts[i] // sec * sec
        if cur is None or cur[0] != b:
            if cur: out.append(tuple(cur))
            cur = [b, o[i], h[i], l[i], c[i]]
        else: cur[2] = max(cur[2], h[i]); cur[3] = min(cur[3], l[i]); cur[4] = c[i]
    if cur: out.append(tuple(cur))
    return out
print("\nunité | dernière bougie clôturée dans le sens | clôture au-delà du plus haut/bas de la précédente | prix actuel au-delà de l'extrême de la bougie précédente")
for name, sec in (("M5", 300), ("M15", 900), ("M30", 1800), ("H1", 3600), ("H4", 14400)):
    B = bars_tf(sec); bt = [b[0] for b in B]
    a = b_ = c_ = n = 0
    for p in E:
        k, T = kk(p["t_in"])
        if k is None: continue
        i = bisect.bisect_right(bt, T - sec) - 1          # dernière bougie entièrement clôturée
        if i < 2: continue
        n += 1; s = sg(p); last, prev = B[i], B[i-1]
        a += (last[4] - last[1]) * s > 0
        b_ += (last[4] > prev[2]) if s > 0 else (last[4] < prev[3])
        c_ += (o[k] > prev[2]) if s > 0 else (o[k] < prev[3])
    print("  %-4s %4.0f %%  %4.0f %%  %4.0f %%   (n=%d)" % (name, 100 * a / n, 100 * b_ / n, 100 * c_ / n, n))
# 3) distance à l'extrême de 4 h en ATR M5 et temps écoulé depuis cet extrême
B5 = bars_tf(300); b5 = [b[0] for b in B5]
dist, since = [], []
for p in E:
    k, T = kk(p["t_in"])
    if k is None: continue
    j = bisect.bisect_left(ts, T - 240 * 60)
    if j >= k - 10: continue
    s = sg(p); win_h = h[j:k]; win_l = l[j:k]
    ext = max(win_h) if s > 0 else min(win_l); idx = (win_h.index(ext) if s > 0 else win_l.index(ext))
    i5 = bisect.bisect_right(b5, T - 300) - 1
    atr = st.mean(max(B5[x][2] - B5[x][3], abs(B5[x][2] - B5[x-1][4]), abs(B5[x][3] - B5[x-1][4])) for x in range(i5 - 13, i5 + 1)) if i5 > 14 else None
    if atr: dist.append(abs(ext - o[k]) / atr); since.append((k - (j + idx)))
print("\nécart entre le prix d'entrée et l'extrême des 4 h (en ATR M5) : P10 %.1f, médiane %.1f, P90 %.1f ; minutes écoulées depuis cet extrême : P10 %d, médiane %d, P90 %d" % (
    q(dist, .1), st.median(dist), q(dist, .9), q(since, .1), st.median(since), q(since, .9)))

# ---- comparaison avec le hasard : même test à des instants tirés au hasard (heures ouvrées) ----
import random
random.seed(7)
def frac_beyond(times_sides, sec):
    B = bars_tf(sec); bt = [b[0] for b in B]; n = ok = 0
    for T, s in times_sides:
        k = bisect.bisect_left(ts, T)
        if k >= len(ts) or ts[k] - T > 90: continue
        i = bisect.bisect_right(bt, T - sec) - 1
        if i < 2: continue
        prev = B[i-1]; n += 1; ok += (o[k] > prev[2]) if s > 0 else (o[k] < prev[3])
    return 100 * ok / n
real = [(int(R.server_to_utc(p["t_in"]).timestamp()), sg(p)) for p in E]
t0, t1 = int(datetime(2024, 11, 1, tzinfo=UTC).timestamp()), int(datetime(2026, 9, 28, tzinfo=UTC).timestamp())
rnd = []
while len(rnd) < 4000:
    T = random.randrange(t0, t1); d = datetime.fromtimestamp(T, UTC)
    if d.weekday() < 5 and 1 <= d.hour <= 21: rnd.append((T, random.choice((1, -1))))
# hasard avec le sens du mouvement des 60 dernières minutes (pour ne pas comparer à un sens aléatoire)
def with_move(lst):
    out = []
    for T, _ in lst:
        k = bisect.bisect_left(ts, T)
        j = bisect.bisect_left(ts, T - 3600)
        if k < len(ts) and j < k and o[k] != o[j]: out.append((T, 1 if o[k] > o[j] else -1))
    return out
rm = with_move(rnd)
print("\nprix au-delà de l'extrême de la bougie précédente (achat > plus haut ; vente < plus bas) :")
print("  unité | trader | hasard, sens aléatoire | hasard, sens du mouvement 60 min")
for name, sec in (("M15", 900), ("H1", 3600), ("H4", 14400), ("D1", 86400)):
    print("  %-4s  %4.0f %%   %4.0f %%   %4.0f %%" % (name, frac_beyond(real, sec), frac_beyond(rnd, sec), frac_beyond(rm, sec)))
