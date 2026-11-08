"""Face triangulation self-check: for every face compare the signed outer-minus-holes area (Newell, along the face
normal) with the sum of the triangle areas produced by skpballet.mesh.triangulate. Prints aggregate numbers only
(no names), so it is safe to run on private files.   usage: python3 tools/area_check.py FILE.skp [...]"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from skpballet import container, mesh, scene  # noqa: E402


def newell(loop):
    x = y = z = 0.0
    for i, p in enumerate(loop):
        q = loop[(i + 1) % len(loop)]
        x += (p[1] - q[1]) * (p[2] + q[2]); y += (p[2] - q[2]) * (p[0] + q[0]); z += (p[0] - q[0]) * (p[1] + q[1])
    return x / 2, y / 2, z / 2


def tri_area(a, b, c):
    u = [b[i] - a[i] for i in range(3)]; v = [c[i] - a[i] for i in range(3)]
    return 0.5 * math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2)


def check(path, tol=1e-3):
    m = scene.load(container.open_skp(path))
    faces = bad = 0
    for d in list(m.defs.values()) + [m.root]:
        for f in d.faces:
            loops = [[d.vertices[v] for v in lp if v in d.vertices] for lp in f["loops"]]
            loops = [l for l in loops if len(l) >= 3]
            if not loops:
                continue
            nrm = f["normal"] or (0, 0, 1)
            nl = math.sqrt(sum(c * c for c in nrm)) or 1.0
            outer = abs(sum(a * b / nl for a, b in zip(newell(loops[0]), nrm)))
            holes = sum(abs(sum(a * b / nl for a, b in zip(newell(h), nrm))) for h in loops[1:])
            want = outer - holes
            P, tr = mesh.triangulate(loops, nrm)
            got = sum(tri_area(P[a], P[b], P[c]) for a, b, c in tr)
            faces += 1
            if abs(got - want) > tol * max(abs(want), 1e-9):
                bad += 1
    return faces, bad


if __name__ == "__main__":
    tf = tb = 0
    for p in sys.argv[1:]:
        n, b = check(p)
        tf += n; tb += b
        print("file %d: faces %d, area mismatch >0.1%% %d" % (sys.argv.index(p), n, b))
    print("total: faces %d mismatches %d" % (tf, tb))
