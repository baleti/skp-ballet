# Fuzz: random star-shaped outer polygon with disjoint convex holes, random winding, normal +-Z; reports faces whose triangle area is off by >1e-6 relative. Usage: PYTHONPATH=. python3 tools/fuzz_star_holes.py SEED
import random,math,sys
from skpballet import mesh
rnd=random.Random(int(sys.argv[1]));bad=[];n=0
def sa(pts): return sum(pts[i][0]*pts[(i+1)%len(pts)][1]-pts[(i+1)%len(pts)][0]*pts[i][1] for i in range(len(pts)))/2
def area(P,tr): return sum(abs((P[b][0]-P[a][0])*(P[c][1]-P[a][1])-(P[c][0]-P[a][0])*(P[b][1]-P[a][1]))/2 for a,b,c in tr)
for it in range(600):
    k=rnd.randint(5,14)
    outer=[(math.cos(2*math.pi*i/k)*r,math.sin(2*math.pi*i/k)*r) for i in range(k) for r in [rnd.uniform(6,10)]]
    # holes: small polygons within radius 4 of origin, disjoint by rejection
    holes=[]
    for _ in range(rnd.randint(1,8)):
        cx,cy=rnd.uniform(-3,3),rnd.uniform(-3,3); r=rnd.uniform(.3,1)
        if any(math.hypot(cx-h[0],cy-h[1])<r+h[2]+.05 for h in holes): continue
        holes.append((cx,cy,r,rnd.randint(3,7),rnd.random()*6))
    hl=[]
    for cx,cy,r,m,ph in holes:
        pts=[(cx+r*math.cos(ph+2*math.pi*i/m),cy+r*math.sin(ph+2*math.pi*i/m)) for i in range(m)]
        hl.append(pts if rnd.random()<.5 else pts[::-1])
    exp=sa(outer)-sum(abs(sa(h)) for h in hl)
    fl=rnd.random()<.5
    o2=outer[::-1] if fl else outer
    P,tr=mesh.triangulate([[(x,y,0.) for x,y in o2]]+[[(x,y,0.) for x,y in h] for h in hl],(0,0,-1 if fl else 1)); n+=1
    e=abs(area(P,tr)-exp)/exp
    if e>1e-6: bad.append((it,round(e,5)))
print(len(bad),n,bad[:5])
