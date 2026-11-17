import json, math, statistics as st
S=["DAX","NAS100","US30"]
def ci(r):
    m=st.mean(r); se=st.stdev(r)/math.sqrt(len(r)); return m,m-1.96*se,m+1.96*se
A={s:[tuple(x) for x in json.load(open("bbr_%s.json"%s))] for s in S}
def block(title, f):
    print("\n== "+title)
    allr=[]
    for lab,lo,hi in (("2018-2022",0,2022),("2023-2026",2023,9999),("TOUT",0,9999)):
        r=[x[1] for s in S for x in A[s] if f(x) and lo<=x[0]<=hi]
        if len(r)<30: print("  %-10s n=%d"%(lab,len(r))); continue
        m,a,b=ci(r); print("  %-10s n=%6d  R moyen %+.3f [%+.3f ; %+.3f]  gagnants %4.1f%%  R>=+1 %4.1f%%  perte max %.1f"%(lab,len(r),m,a,b,100*sum(1 for x in r if x>0)/len(r),100*sum(1 for x in r if x>=1)/len(r),min(r)))
    print("  par indice : "+", ".join("%s %+.3f (n=%d)"%(s,st.mean([x[1] for x in A[s] if f(x)]),sum(1 for x in A[s] if f(x))) for s in S))
    print("  par sens   : "+", ".join("%s %+.3f"%("haussier" if sg>0 else "baissier",st.mean([x[1] for s in S for x in A[s] if f(x) and x[3]==sg])) for sg in (1,-1)))
block("toutes réintégrations", lambda x: True)
block("risque (stop-entrée) >= 3 spreads", lambda x: x[2]>=3)
block("risque >= 10 spreads", lambda x: x[2]>=10)
rs=sorted(x[2] for s in S for x in A[s]); print("\nrisque en spreads : médiane %.1f, 10e centile %.1f, 90e %.1f"%(rs[len(rs)//2],rs[len(rs)//10],rs[9*len(rs)//10]))
