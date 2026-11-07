"""Flatten a Model to triangles per material (metres, Y-up) and write GLB."""
import json
import math
import struct
from .scene import INCH


def _area2(p, a, b, c):
    return (p[b][0] - p[a][0]) * (p[c][1] - p[a][1]) - (p[b][1] - p[a][1]) * (p[c][0] - p[a][0])


def _in_tri(p, a, b, c, q):
    d1 = _area2(p, a, b, q) if False else (p[b][0]-p[a][0])*(p[q][1]-p[a][1])-(p[b][1]-p[a][1])*(p[q][0]-p[a][0])
    d2 = (p[c][0]-p[b][0])*(p[q][1]-p[b][1])-(p[c][1]-p[b][1])*(p[q][0]-p[b][0])
    d3 = (p[a][0]-p[c][0])*(p[q][1]-p[c][1])-(p[a][1]-p[c][1])*(p[q][0]-p[c][0])
    return (d1 >= 0 and d2 >= 0 and d3 >= 0)


def _signed(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def triangulate(loops3d, normal):
    """loops3d: list of lists of (x,y,z); first is outer. Returns (points3d, tri index triples)."""
    nx, ny, nz = normal
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / n, ny / n, nz / n
    ax = (1, 0, 0) if abs(nx) < 0.9 else (0, 1, 0)
    ux = (ny * ax[2] - nz * ax[1], nz * ax[0] - nx * ax[2], nx * ax[1] - ny * ax[0])
    ul = math.sqrt(sum(c * c for c in ux)) or 1.0
    ux = tuple(c / ul for c in ux)
    uy = (ny * ux[2] - nz * ux[1], nz * ux[0] - nx * ux[2], nx * ux[1] - ny * ux[0])
    P3, P2, rings = [], [], []
    for li, lp in enumerate(loops3d):
        ids = []
        for q in lp:
            ids.append(len(P3)); P3.append(q)
            P2.append((q[0] * ux[0] + q[1] * ux[1] + q[2] * ux[2], q[0] * uy[0] + q[1] * uy[1] + q[2] * uy[2]))
        if len(ids) < 3:
            if li == 0:
                return P3, []
            continue
        pts = [P2[i] for i in ids]
        if (_signed(pts) > 0) != (li == 0):
            ids.reverse()
        rings.append(ids)
    if not rings:
        return P3, []
    outer = rings[0]
    # bridge holes (rightmost hole vertex first) into the outer ring
    for hole in sorted(rings[1:], key=lambda h: -max(P2[i][0] for i in h)):
        hi = max(hole, key=lambda i: P2[i][0])
        best, bd = None, 1e300
        for k, oi in enumerate(outer):
            d = (P2[oi][0] - P2[hi][0]) ** 2 + (P2[oi][1] - P2[hi][1]) ** 2
            if d < bd:
                bd, best = d, k
        hp = hole.index(hi)
        hr = hole[hp:] + hole[:hp]
        d1, d2 = len(P3), len(P3) + 1  # duplicated bridge endpoints get their own node ids
        P3.extend((P3[hi], P3[outer[best]])); P2.extend((P2[hi], P2[outer[best]]))
        outer = outer[: best + 1] + hr + [d1, d2] + outer[best + 1 :]
    idx = list(outer)
    tris = []
    if len(rings) == 1 and all(_area2(P2, idx[k - 1], idx[k], idx[(k + 1) % len(idx)]) >= -1e-12 for k in range(len(idx))):
        for k in range(1, len(idx) - 1):  # convex: fan
            if _area2(P2, idx[0], idx[k], idx[k + 1]) != 0:
                tris.append((idx[0], idx[k], idx[k + 1]))
        return P3, tris
    n = len(idx)
    prv = {idx[k]: idx[k - 1] for k in range(n)}
    nxt = {idx[k]: idx[(k + 1) % n] for k in range(n)}

    def is_refl(v):
        return _area2(P2, prv[v], v, nxt[v]) < 0
    refl = {v for v in idx if is_refl(v)}
    cur, left, fails = idx[0], n, 0
    while left > 3:
        a, c = prv[cur], nxt[cur]
        ok = cur not in refl and _area2(P2, a, cur, c) > 1e-12
        if ok and refl:
            xs = (P2[a][0], P2[cur][0], P2[c][0]); ys = (P2[a][1], P2[cur][1], P2[c][1])
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            pa, pb, pc = P2[a], P2[cur], P2[c]
            for r in refl:
                q = P2[r]
                if q[0] < x0 or q[0] > x1 or q[1] < y0 or q[1] > y1 or q == pa or q == pb or q == pc:
                    continue
                if _in_tri(P2, a, cur, c, r):
                    ok = False
                    break
        if ok:
            tris.append((a, cur, c))
            nxt[a], prv[c] = c, a
            left -= 1
            fails = 0
            for v in (a, c):
                if is_refl(v):
                    refl.add(v)
                else:
                    refl.discard(v)
            refl.discard(cur)
            cur = c
        else:
            cur = c
            fails += 1
            if fails > left:  # no ear found: drop a vertex to make progress
                a, c = prv[cur], nxt[cur]
                nxt[a], prv[c] = c, a
                refl.discard(cur)
                left -= 1
                cur, fails = c, 0
    if left == 3 and _area2(P2, prv[cur], cur, nxt[cur]) != 0:
        tris.append((prv[cur], cur, nxt[cur]))
    return P3, tris


def _mul(m, v):
    """13-value transform (verified semantics from public notes): rows = images of the x,y,z axes,
    then translation, then scale s: p' = s * (p . R + t)."""
    s = m[12] or 1.0
    x, y, z = v
    return (s * (x * m[0] + y * m[3] + z * m[6] + m[9]),
            s * (x * m[1] + y * m[4] + z * m[7] + m[10]),
            s * (x * m[2] + y * m[5] + z * m[8] + m[11]))


def _compose(a, b):
    """matrix that applies b first, then a (scale folded into the 3x3 and translation)."""
    o = _mul(a, _mul(b, (0, 0, 0)))
    r = [tuple(c - oc for c, oc in zip(_mul(a, _mul(b, e)), o)) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return [*r[0], *r[1], *r[2], *o, 1.0]


IDENT = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0]


def definition_tris(d):
    """-> {mat_id: [triangle tuples of 3 points in inches]}"""
    out = {}
    for f in d.faces:
        loops = [[d.vertices[v] for v in lp if v in d.vertices] for lp in f["loops"]]
        loops = [l for l in loops if l]
        if not loops:
            continue
        nrm = f["normal"] or (0, 0, 1)
        P, tr = triangulate(loops, nrm)
        out.setdefault(f["mat"], []).extend((P[a], P[b], P[c]) for a, b, c in tr)
    return out


def flatten(model, max_depth=24, max_tris=5_000_000, lines=None):
    """Returns {mat_id: flat list of floats (x,y,z per vertex, metres, Y-up)}.
    If `lines` is a list, edge segments (6 floats each, same space) are appended to it."""
    cache, res, count = {}, {}, [0]

    def emit(tris_by_mat, m):
        for mat, tris in tris_by_mat.items():
            buf = res.setdefault(mat, [])
            for t in tris:
                for p in t:
                    x, y, z = _mul(m, p)
                    buf.extend((x * INCH, z * INCH, -y * INCH))
                count[0] += 1

    def walk(d, m, depth):
        if depth > max_depth or count[0] > max_tris:
            model.warnings.append("depth/size limit reached")
            return
        if d.id not in cache:
            cache[d.id] = definition_tris(d)
        emit(cache[d.id], m)
        if lines is not None:
            for a, b in d.edges.values():
                if a in d.vertices and b in d.vertices:
                    for p in (d.vertices[a], d.vertices[b]):
                        x, y, z = _mul(m, p)
                        lines.extend((x * INCH, z * INCH, -y * INCH))
        for inst in d.instances:
            sub = model.defs.get(inst["def_id"])
            if sub is not None:
                walk(sub, _compose(m, inst["matrix"]), depth + 1)

    walk(model.root, IDENT, 0)
    return res


def write_glb(model, path, edges=True):
    seg = [] if edges else None
    res = flatten(model, lines=seg)
    bin_, views, accs, prims, mats = bytearray(), [], [], [], []
    for mid, buf in sorted(res.items(), key=lambda kv: str(kv[0])):
        if not buf:
            continue
        n = len(buf) // 3
        off = len(bin_)
        bin_ += struct.pack("<%df" % len(buf), *buf)
        xs, ys, zs = buf[0::3], buf[1::3], buf[2::3]
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(buf) * 4, target=34962))
        accs.append(dict(bufferView=len(views) - 1, componentType=5126, count=n, type="VEC3",
                         min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)]))
        mt = model.materials.get(mid, dict(name="default", rgb=(200, 200, 200), alpha=1.0))
        mats.append(dict(name=mt["name"], doubleSided=True,
                         pbrMetallicRoughness=dict(baseColorFactor=[c / 255 for c in mt["rgb"]] + [mt["alpha"]],
                                                   metallicFactor=0, roughnessFactor=0.9),
                         **({"alphaMode": "BLEND"} if mt["alpha"] < 1 else {})))
        prims.append(dict(attributes=dict(POSITION=len(accs) - 1), material=len(mats) - 1, mode=4))
    if seg:
        n = len(seg) // 3
        off = len(bin_)
        bin_ += struct.pack("<%df" % len(seg), *seg)
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(seg) * 4, target=34962))
        accs.append(dict(bufferView=len(views) - 1, componentType=5126, count=n, type="VEC3",
                         min=[min(seg[0::3]), min(seg[1::3]), min(seg[2::3])],
                         max=[max(seg[0::3]), max(seg[1::3]), max(seg[2::3])]))
        mats.append(dict(name="edges", pbrMetallicRoughness=dict(baseColorFactor=[0.05, 0.05, 0.05, 1],
                                                                 metallicFactor=0, roughnessFactor=1)))
        prims.append(dict(attributes=dict(POSITION=len(accs) - 1), material=len(mats) - 1, mode=1))
    js = dict(asset=dict(version="2.0", generator="skp-ballet"), scene=0, scenes=[dict(nodes=[0])],
              nodes=[dict(mesh=0, name="model")], meshes=[dict(primitives=prims)] if prims else [dict(primitives=[])],
              materials=mats, accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(j) + 8 + len(bin_)))
        f.write(struct.pack("<I4s", len(j), b"JSON") + j)
        f.write(struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_))
    return sum(len(b) // 9 for b in res.values())
