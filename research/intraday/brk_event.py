"""SPIKE JETABLE : étude d'événements. Première minute dont le plus haut dépasse le plus haut des N dernières minutes (achat) ou dont le plus bas
passe sous le plus bas des N dernières minutes (vente). Une même excursion n'est comptée qu'une fois par 60 min et par sens.
Entrée = ouverture de la minute suivante (ask pour achat, bid pour vente) ; sortie après +5/15/60/240 min. Usage : brk_event.py dossier SYMBOLE sortie.json"""
import bisect, json, os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
HZ = (5, 15, 60, 240)
def main(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    n = len(ts); res = {}
    for N in (240, 1440):
        W = N * 60
        dq_h, dq_l = deque(), deque()          # (ts, valeur) monotones sur la fenêtre [t-W, t)
        last_up = last_dn = -10**12; ev = []
        for j in range(n):
            t = ts[j]
            while dq_h and dq_h[0][0] < t - W: dq_h.popleft()
            while dq_l and dq_l[0][0] < t - W: dq_l.popleft()
            full = bool(dq_h) and dq_h[0][0] <= t - W + 600       # fenêtre réellement couverte (pas de trou au début)
            if full:
                for side, brk in ((1, h[j] > dq_h[0][1]), (-1, l[j] < dq_l[0][1])):
                    last = last_up if side > 0 else last_dn
                    if brk and t - last >= 3600:
                        if side > 0: last_up = t
                        else: last_dn = t
                        k = j + 1
                        if k < n and ts[k] - t <= 120:
                            row = {"t": ts[k], "side": side}
                            for hz in HZ:
                                q = bisect.bisect_left(ts, ts[k] + hz * 60)
                                if q < n and ts[q] - (ts[k] + hz * 60) <= 120:
                                    row[str(hz)] = (o[q] - (o[k] + sp[k])) if side > 0 else (o[k] - (o[q] + sp[q]))
                                    row["g%d" % hz] = (o[q] - o[k]) * side
                            ev.append(row)
            while dq_h and dq_h[-1][1] <= h[j]: dq_h.pop()
            dq_h.append((t, h[j]))
            while dq_l and dq_l[-1][1] >= l[j]: dq_l.pop()
            dq_l.append((t, l[j]))
        res[str(N)] = ev
    json.dump(res, open(out, "w")); print(sym, {k: len(v) for k, v in res.items()})
if __name__ == "__main__": main(*sys.argv[1:4])
