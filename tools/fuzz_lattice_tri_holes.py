# Fuzz: triangular lattice holes (may touch each other and the outer ring), islands excluded; prints wrong-count (abs area error > 1e-4), faces tested, skipped, max error. Usage: PYTHONPATH=. python3 tools/fuzz_lattice_tri_holes.py SEED
import random,sys
from skpballet import mesh
rnd=random.Random(int(sys.argv[1])); bad=[];n=0;mx=0;skipped=0
def area(P,tr): return sum(abs((P[b][0]-P[a][0])*(P[c][1]-P[a][1])-(P[c][0]-P[a][0])*(P[b][1]-P[a][1]))/2 for a,b,c in tr)
S=8
for it in range(1500):
    alltris=[]
    for x in range(S):
        for y in range(S):
            a,b,c,d=(x,y),(x+1,y),(x+1,y+1),(x,y+1)
            alltris+=[(a,b,c),(a,c,d)] if rnd.random()<.5 else [(a,b,d),(b,c,d)]
    inner=[t for t in alltris if True]
    hs=[t for t in inner if rnd.random()<0.12]
    if not hs: continue
    hset=set(hs); free=[t for t in alltris if t not in hset]
    ed=lambda t:[frozenset((t[i],t[(i+1)%3])) for i in range(3)]
    byedge={}
    for t in free:
        for e in ed(t): byedge.setdefault(e,[]).append(t)
    seen={free[0]};st=[free[0]]
    while st:
        t=st.pop()
        for e in ed(t):
            for u in byedge[e]:
                if u not in seen: seen.add(u);st.append(u)
    if not free or len(seen)!=len(free): skipped+=1; continue
    cov=sum(abs((b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]))/2 for a,b,c in hs)
    loops=[[(0,0,0.),(S,0,0.),(S,S,0.),(0,S,0.)]]
    for t in hs:
        l=[(p[0],p[1],0.) for p in t]; loops.append(l if rnd.random()<.5 else l[::-1])
    P,tr=mesh.triangulate(loops,(0,0,1)); n+=1
    e=abs(area(P,tr)-(S*S-cov)); mx=max(mx,e)
    if e>1e-4: bad.append((it,len(hs),round(e,3),hs))
print(len(bad),n,skipped,mx,[b[:3] for b in bad])
