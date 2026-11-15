"""Synthetic fuzz of mesh.triangulate with integer-grid (colinear, tied-coordinate) outer rings and 1-3 holes
(triangles/quads/L shapes) placed on a small grid; compares the triangle area with outer minus holes.
usage: python3 tools/hole_fuzz_grid.py [N] [seed]"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from skpballet import mesh  # noqa: E402


def sarea(l):
    return sum(l[i][0] * l[(i + 1) % len(l)][1] - l[(i + 1) % len(l)][0] * l[i][1] for i in range(len(l))) / 2


SHAPES = [[(0, 0), (1, 0), (0, 1)], [(0, 0), (1, 0), (1, 1)], [(0, 0), (2, 0), (2, 1), (0, 1)], [(0, 0), (1, 0), (1, 1), (0, 1)],
          [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)], [(0, 0), (1, 0), (1, 1)]]


def main(n=2000, seed=1):
    rnd = random.Random(seed)
    bad = []
    for it in range(n):
        S = rnd.choice([8, 10, 12])
        outer = [(0, 0), (S, 0), (S, S), (0, S)]
        cells, holes = set(), []
        for _ in range(rnd.randint(1, 3)):
            sh = rnd.choice(SHAPES)
            if rnd.random() < 0.5:
                sh = [(y, x) for x, y in sh]
            if rnd.random() < 0.5:
                sh = list(reversed(sh))
            ox, oy = rnd.randint(1, S - 3), rnd.randint(1, S - 3)
            pts = [(x + ox, y + oy) for x, y in sh]
            bb = (min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts))
            if any(not (bb[1] < c[0] - 1 or bb[0] > c[1] + 1 or bb[3] < c[2] - 1 or bb[2] > c[3] + 1) for c in cells):
                continue   # keep holes disjoint (and not touching)
            cells.add(bb) if False else cells.add(bb)
            holes.append(pts)
        loops = [[(x, y, 0) for x, y in outer]] + [[(x, y, 0) for x, y in h] for h in holes]
        want = abs(sarea(outer)) - sum(abs(sarea(h)) for h in holes)
        P, t = mesh.triangulate(loops, (0, 0, 1))
        got = sum(abs((P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[c][0] - P[a][0]) * (P[b][1] - P[a][1])) / 2 for a, b, c in t)
        if abs(got - want) > 1e-6:
            bad.append((it, want, got, loops))
    print(len(bad), "of", n, "wrong")
    for b in bad[:3]:
        print(b)
    return bad


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
