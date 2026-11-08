"""Synthetic fuzz of mesh.triangulate: jittered outer quad with 1-4 jittered quad holes; compares the triangle area
with outer minus holes. usage: python3 tools/hole_fuzz.py [N] [seed]"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from skpballet import mesh  # noqa: E402


def area(l):
    return sum(l[i][0] * l[(i + 1) % len(l)][1] - l[(i + 1) % len(l)][0] * l[i][1] for i in range(len(l))) / 2


def quad(cx, cy, r, rnd):
    return [(cx + rnd.uniform(-r, -r * .3), cy + rnd.uniform(-r, -r * .3)), (cx + rnd.uniform(r * .3, r), cy + rnd.uniform(-r, -r * .3)),
            (cx + rnd.uniform(r * .3, r), cy + rnd.uniform(r * .3, r)), (cx + rnd.uniform(-r, -r * .3), cy + rnd.uniform(r * .3, r))]


def main(n=600, seed=5):
    rnd = random.Random(seed)
    bad = []
    cent = [(5, 5), (15, 5), (5, 15), (15, 15)]
    for k in range(n):
        o = [(rnd.uniform(-1, 1), rnd.uniform(-1, 1)), (20 + rnd.uniform(-1, 1), rnd.uniform(-1, 1)),
             (20 + rnd.uniform(-1, 1), 20 + rnd.uniform(-1, 1)), (rnd.uniform(-1, 1), 20 + rnd.uniform(-1, 1))]
        hs = [quad(cx, cy, rnd.uniform(1, 4), rnd) for cx, cy in cent[:rnd.choice((1, 2, 3, 4))]]
        want = abs(area(o)) - sum(abs(area(h)) for h in hs)
        loops = [[(x, y, 0) for x, y in o]] + [[(x, y, 0) for x, y in h][::-1] for h in hs]
        P, tr = mesh.triangulate(loops, (0, 0, 1))
        got = sum(abs(area([P[a][:2], P[b][:2], P[c][:2]])) for a, b, c in tr)
        if abs(got - want) > 1e-3 * abs(want):
            bad.append((k, len(hs), round(want, 2), round(got, 2)))
    print("%d of %d wrong" % (len(bad), n), bad[:5])
    return bad


if __name__ == "__main__":
    main(*[int(a) for a in sys.argv[1:3]])
