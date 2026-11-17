"""SPIKE JETABLE : étude d'événements. Première clôture 5 min au-delà de la bande de Bollinger (160 ; 2,8), calculée sur les 160 barres PRÉCÉDENTES.
Sens = celui de la cassure (continuation). Entrée = ouverture de la minute suivante ; achat à l'ask, vente au bid ; sortie à +5/15/30/60/240 min (bid/ask).
Usage : bb_event.py dossier SYMBOLE sortie.json"""
import bisect, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
H = (5, 15, 30, 60, 240)
def main(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    bts, bc, cur = [], [], None
    for i in range(len(ts)):
        b = ts[i] // 300 * 300
        if cur != b: bts.append(b); bc.append(c[i]); cur = b
        else: bc[-1] = c[i]
    ps, pq = [0.0], [0.0]
    for x in bc: ps.append(ps[-1] + x); pq.append(pq[-1] + x * x)
    z = [None] * len(bts)
    for i in range(160, len(bts)):
        s_, q_ = ps[i] - ps[i-160], pq[i] - pq[i-160]; m = s_ / 160; v = q_ / 160 - m * m
        if v > 0 and bts[i] - bts[i-1] <= 900: z[i] = (bc[i] - m) / math.sqrt(v)
    ev = []
    for i in range(161, len(bts)):
        if z[i] is None or z[i-1] is None: continue
        side = 1 if (z[i] >= 2.8 and z[i-1] < 2.8) else -1 if (z[i] <= -2.8 and z[i-1] > -2.8) else 0
        if not side: continue
        T = bts[i] + 300
        k = bisect.bisect_left(ts, T)
        if k >= len(ts) or ts[k] - T > 120: continue
        row = {"t": ts[k], "side": side}
        for hz in H:
            j = bisect.bisect_left(ts, T + hz * 60)
            if j < len(ts) and ts[j] - (T + hz * 60) <= 120:
                row[hz] = (o[j] - (o[k] + sp[k])) if side > 0 else (o[k] - (o[j] + sp[j]))
                row["g%d" % hz] = (o[j] - o[k]) * side
        row["px"] = o[k]
        ev.append(row)
    json.dump(ev, open(out, "w")); print(sym, len(ev))
if __name__ == "__main__": main(*sys.argv[1:4])
