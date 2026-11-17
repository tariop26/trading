import json, math, statistics as st
from datetime import datetime, timezone
def ci(v):
    m = st.mean(v); se = st.stdev(v) / math.sqrt(len(v)); return m, m / se
per = (("2018-2022", datetime(2018,1,1), datetime(2023,1,1)), ("2023-oct.2024", datetime(2023,1,1), datetime(2024,10,29)), ("nov.2024-sept.2026", datetime(2024,10,29), datetime(2026,10,1)))
for s in ("XAUUSD", "DAX", "NAS100", "US30"):
    D = json.load(open("brk_%s.json" % s))
    for N, lab_n in (("240", "plus haut/bas 4 h"), ("1440", "plus haut/bas 24 h")):
        E = D[N]; print("\n== %s, cassure du %s : %d événements (net du spread, en points)" % (s, lab_n, len(E)))
        for lab, a, b in per:
            X = [e for e in E if a <= datetime.fromtimestamp(e["t"], timezone.utc).replace(tzinfo=None) < b]
            out = []
            for hz in (5, 15, 60, 240):
                v = [e[str(hz)] for e in X if str(hz) in e]
                if len(v) > 30:
                    m, t = ci(v); g = st.mean(e["g%d" % hz] for e in X if str(hz) in e); out.append("+%d min net %+.2f (brut %+.2f, t=%+.1f)" % (hz, m, g, t))
            print("  %-20s n=%5d | %s" % (lab, len(X), " | ".join(out)))
