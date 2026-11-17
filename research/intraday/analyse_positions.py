import csv, sys, os, bisect, statistics as st
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
P = r"C:\Users\m.poirat\trading\2381033.positions.csv"
rows = list(csv.reader(open(P, encoding="utf-8-sig"), delimiter=";"))[1:]
pos, bal = [], []
f = lambda x: float(x) if x not in ("", None) else 0.0
for r in rows:
    if len(r) < 11: continue
    if r[1] == "Balance": bal.append((r[0], f(r[10]))); continue
    pos.append(dict(t_in=datetime.strptime(r[0], "%Y.%m.%d %H:%M:%S"), side=r[1], vol=f(r[2]), pin=f(r[4]),
                    t_out=datetime.strptime(r[6], "%Y.%m.%d %H:%M:%S"), pout=f(r[7]), comm=f(r[8]), swap=f(r[9]), pnl=f(r[10])))
pos.sort(key=lambda x: x["t_in"])
net = lambda p: p["pnl"] + p["comm"] + p["swap"]
print("opérations de solde :", bal)
print("positions : %d ; du %s au %s" % (len(pos), pos[0]["t_in"], pos[-1]["t_out"]))
print("profit brut %.2f ; commissions %.2f ; swaps %.2f ; NET %.2f" % (sum(p["pnl"] for p in pos), sum(p["comm"] for p in pos), sum(p["swap"] for p in pos), sum(net(p) for p in pos)))
w = [net(p) for p in pos if net(p) > 0]; l = [net(p) for p in pos if net(p) <= 0]
print("positions gagnantes %d (%.0f%%), gain moyen %.2f ; perdantes %d, perte moyenne %.2f ; plus grosse perte %.2f ; facteur de profit %.2f" % (
    len(w), 100*len(w)/len(pos), st.mean(w), len(l), st.mean(l), min(l), sum(w)/-sum(l)))
print("lots :", dict(sorted(Counter(p["vol"] for p in pos).items())), "| sens :", dict(Counter(p["side"] for p in pos)))
# paniers = même sens, même heure de sortie (à 3 s près)
pos.sort(key=lambda x: (x["side"], x["t_out"]))
baskets, cur = [], []
for p in pos:
    if cur and cur[-1]["side"] == p["side"] and abs((p["t_out"] - cur[-1]["t_out"]).total_seconds()) <= 3: cur.append(p)
    else:
        if cur: baskets.append(cur)
        cur = [p]
if cur: baskets.append(cur)
baskets.sort(key=lambda b: min(x["t_in"] for x in b))
print("\npaniers :", len(baskets))
print("%-19s %-5s %3s %6s %7s %8s %8s %7s %9s" % ("1ère entrée (serveur)", "sens", "nb", "lots", "durée", "entrée m.", "sortie", "écart", "net $"))
for b in baskets:
    n = sum(x["vol"] for x in b); avg = sum(x["pin"] * x["vol"] for x in b) / n
    t0 = min(x["t_in"] for x in b); t1 = max(x["t_out"] for x in b)
    print("%-19s %-5s %3d %6.2f %6.0fm %8.2f %8.2f %7.2f %9.2f" % (t0, b[0]["side"], len(b), n, (t1 - t0).total_seconds()/60, avg, b[0]["pout"], (b[0]["pout"] - avg) * (1 if b[0]["side"] == "Buy" else -1), sum(net(x) for x in b)))
bn = [sum(net(x) for x in b) for b in baskets]
print("\npaniers gagnants %d/%d (%.0f%%) ; net moyen %.2f ; pire panier %.2f ; meilleur %.2f" % (sum(1 for x in bn if x > 0), len(bn), 100*sum(1 for x in bn if x > 0)/len(bn), st.mean(bn), min(bn), max(bn)))
# horaires d'entrée
first = [min(b, key=lambda x: x["t_in"]) for b in baskets]
print("\nheure serveur de la 1ère entrée :", dict(sorted(Counter(p["t_in"].strftime("%H:%M") for p in first).items())))
print("minute d'entrée (toutes positions) mod 30 :", dict(sorted(Counter((p["t_in"].minute % 30) for p in pos).items())))
print("heure serveur des entrées suivantes :", dict(sorted(Counter(p["t_in"].strftime("%H") for p in pos if p not in first).items())))

# ---------------- contexte de marché (données 1 min de l'or jusqu'au 2026-09-30) ----------------
import math
(ts, o, h, l, c, sp), daily = R.load_1m(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx_data", "XAUUSD"))
bts, bc, cur_b = [], [], None
for i in range(len(ts)):
    b = ts[i] // 300 * 300
    if cur_b != b: bts.append(b); bc.append(c[i]); cur_b = b
    else: bc[-1] = c[i]
ps, pq = [0.0], [0.0]
for x in bc: ps.append(ps[-1] + x); pq.append(pq[-1] + x * x)
def zscore(t_server, price=None):
    T = int(R.server_to_utc(t_server).timestamp())
    k = bisect.bisect_left(ts, T)
    if k >= len(ts) or ts[k] - T > 120: return None
    i = bisect.bisect_left(bts, T // 300 * 300) - 1
    if i < 159: return None
    s, q = ps[i+1] - ps[i-159], pq[i+1] - pq[i-159]
    m = s / 160; v = q / 160 - m * m
    if v <= 0: return None
    px = price if price is not None else o[k]
    return (px - m) / math.sqrt(v), o[k]
print("\n=== contrôle du flux de prix et position vs bande de Bollinger 5 min (160 ; écart en écarts-types) ===")
print("%-19s %-5s %9s %9s %7s %7s" % ("entrée (serveur)", "sens", "prix réel", "prix données", "z entrée", "z sortie"))
zs_in, diffs, zs_out = [], [], []
ordered = sorted(pos, key=lambda x: x["t_in"])
for p in ordered:
    a = zscore(p["t_in"], p["pin"]); b = zscore(p["t_out"], p["pout"])
    if a is None: continue
    zs_in.append((p, a[0])); diffs.append(abs(a[1] - p["pin"]))
    if b: zs_out.append((p, b[0]))
firsts = {id(min(b, key=lambda x: x["t_in"])) for b in baskets}
for p, z in zs_in:
    if id(p) in firsts:
        zo = [zz for q, zz in zs_out if q is p]
        print("%-19s %-5s %9.2f %9s %+7.2f %7s" % (p["t_in"], p["side"], p["pin"], "", z, "%+.2f" % zo[0] if zo else ""))
print("\nécart médian prix réel / prix données à l'entrée : %.2f pts (n=%d)" % (st.median(diffs), len(diffs)))
for lab, sel in (("1ères entrées", lambda p: id(p) in firsts), ("renforts", lambda p: id(p) not in firsts)):
    zi = [(p["side"], z) for p, z in zs_in if sel(p)]
    if zi:
        sz = [z for s, z in zi if s == "Sell"]; bz = [z for s, z in zi if s == "Buy"]
        print("%-14s n=%d | Sell: z moyen %+.2f (n=%d) | Buy: z moyen %+.2f (n=%d) | |z|>=2.8 : %.0f%% | |z|>=2 : %.0f%%" % (
            lab, len(zi), st.mean(sz) if sz else float('nan'), len(sz), st.mean(bz) if bz else float('nan'), len(bz),
            100 * sum(1 for s, z in zi if abs(z) >= 2.8) / len(zi), 100 * sum(1 for s, z in zi if abs(z) >= 2) / len(zi)))
zo_all = [z for p, z in zs_out]
print("z à la sortie : médiane %+.2f ; |z|<0.5 : %.0f%% (n=%d)" % (st.median(zo_all), 100 * sum(1 for z in zo_all if abs(z) < 0.5) / len(zo_all), len(zo_all)))

# ---------------- référence qui explique le sens de la 1ère entrée ----------------
print("\n=== accord entre le sens du panier et le signe (prix - référence) ; 1ères entrées avec données (n varie) ===")
fe = [min(b, key=lambda x: x["t_in"]) for b in baskets]
fe = [p for p in fe if p["t_in"] >= datetime(2026, 7, 7, 12) and p["t_in"] < datetime(2026, 10, 1)]
def px_at(naive_server, back_min=0):
    T = int(R.server_to_utc(naive_server).timestamp()) - back_min * 60
    k = bisect.bisect_left(ts, T)
    return o[k] if k < len(ts) and abs(ts[k] - T) <= 600 else None
def day_open(naive_server):             # ouverture de la journée serveur (00:00)
    return px_at(naive_server.replace(hour=0, minute=0, second=0) + timedelta(minutes=1))
def prev_close(naive_server):
    d = naive_server.replace(hour=0, minute=0, second=0)
    for back in (1, 2, 3, 4):
        v = px_at(d - timedelta(days=back) + timedelta(hours=23, minutes=58))
        if v: return v
anchors = {}
for hrs in (0.5, 1, 2, 3, 4, 6, 8, 12, 24):
    anchors["il y a %sh" % hrs] = lambda t, hrs=hrs: px_at(t, int(hrs * 60))
anchors["ouverture jour serveur"] = day_open
anchors["clôture veille serveur"] = prev_close
anchors["ouverture 14:00 serveur"] = lambda t: px_at(t.replace(hour=14, minute=0, second=0))
anchors["ouverture 19:00 serveur"] = lambda t: px_at(t.replace(hour=19, minute=0, second=0))
res = []
for name, fn in anchors.items():
    ok = tot = 0
    for p in fe:
        a = fn(p["t_in"]); now = px_at(p["t_in"])
        if a is None or now is None or now == a: continue
        tot += 1; ok += ((now > a) == (p["side"] == "Buy"))
    if tot: res.append((ok / tot, name, ok, tot))
for r_ in sorted(res, reverse=True): print("  %-26s accord %d/%d = %.0f%%  (momentum ; 0 %% = contre-tendance)" % (r_[1], r_[2], r_[3], 100 * r_[0]))
print("\n=== sens des paniers vs. même sens que la tendance des 20 derniers jours (SMA20 > SMA50 journalière) ===")
dts = [d[0] for d in daily]; dcl = [d[4] for d in daily]
for p in fe:
    ds = R.server_date(R.server_to_utc(p["t_in"]))
    i = bisect.bisect_left(dts, ds)
    if i < 51: continue
    c1, m20, m50 = dcl[i-1], sum(dcl[i-20:i]) / 20, sum(dcl[i-50:i]) / 50
    tr = "haussière" if c1 > m50 and m20 > m50 else "baissière" if c1 < m50 and m20 < m50 else "mixte"
    print("  %s %-5s  tendance D1 : %s" % (p["t_in"].date(), p["side"], tr))
