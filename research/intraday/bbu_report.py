import json, math, statistics as st
from collections import Counter
S=["DAX","NAS100","US30"]
T=[]
for s in S:
    for t in json.load(open("bbu_%s.json"%s))["trades"]: t["s"]=s; T.append(t)
def ci(v):
    m=st.mean(v); se=st.stdev(v)/math.sqrt(len(v)); return m,m-1.96*se,m+1.96*se
for kd in (0.5,1.0):
    print("\n== stop = %.1f x distance(bande->médiane)"%kd)
    for lab,lo,hi in (("2018-2022",0,2022),("2023-2026",2023,9999),("TOUT",0,9999)):
        X=[t for t in T if t["kd"]==kd and lo<=int(t["d"][:4])<=hi]
        r=[t["r"] for t in X]; a,b,c=ci(r); cc=Counter(t["code"] for t in X)
        print("  %-10s n=%5d  R moyen %6.3f [%6.3f ; %6.3f]  stop %4.1f%%  TP1+BE %4.1f%%  TP1+TP2 %4.1f%%  fin séance %4.1f%%"%(
            lab,len(X),a,b,c,100*cc["SL"]/len(X),100*cc["TP1+BE"]/len(X),100*cc["TP1+TP2"]/len(X),100*(cc["FIN"]+cc["TP1+FIN"])/len(X)))
    print("  par indice (R moyen, n) : "+", ".join("%s %.3f (%d)"%(s,st.mean([t["r"] for t in T if t["kd"]==kd and t["s"]==s]),sum(1 for t in T if t["kd"]==kd and t["s"]==s)) for s in S))
    print("  par sens : "+", ".join("%s %.3f"%("haussier" if sg>0 else "baissier",st.mean([t["r"] for t in T if t["kd"]==kd and t["side"]==sg])) for sg in (1,-1)))
    yrs={}
    for t in T:
        if t["kd"]==kd: yrs.setdefault(t["d"][:4],[]).append(t["r"])
    print("  par année : "+", ".join("%s %.2f"%(y,st.mean(v)) for y,v in sorted(yrs.items())))
