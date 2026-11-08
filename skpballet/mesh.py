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


def _strict_in_tri(p, a, b, c, q):
    d1 = (p[b][0]-p[a][0])*(p[q][1]-p[a][1])-(p[b][1]-p[a][1])*(p[q][0]-p[a][0])
    d2 = (p[c][0]-p[b][0])*(p[q][1]-p[b][1])-(p[c][1]-p[b][1])*(p[q][0]-p[b][0])
    d3 = (p[a][0]-p[c][0])*(p[q][1]-p[c][1])-(p[a][1]-p[c][1])*(p[q][0]-p[c][0])
    return d1 > 1e-12 and d2 > 1e-12 and d3 > 1e-12


def _seg_cross(a, b, c, d):
    """proper intersection of segments ab and cd (shared endpoints and touching do not count)"""
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = o(a, b, c), o(a, b, d), o(c, d, a), o(c, d, b)
    return ((o1 > 1e-12 and o2 < -1e-12) or (o1 < -1e-12 and o2 > 1e-12)) and \
           ((o3 > 1e-12 and o4 < -1e-12) or (o3 < -1e-12 and o4 > 1e-12))


def _bridge_clear(P2, hi, oi, outer, hole, others):
    a, b = P2[hi], P2[oi]
    for ring in [outer, hole] + others:
        n = len(ring)
        for k in range(n):
            c, d = P2[ring[k]], P2[ring[(k + 1) % n]]
            if _seg_cross(a, b, c, d):
                return False
    return True


def _split_pinched(loop):
    """Split a loop that visits the same 3D point twice into simple loops (pieces between the repeats)."""
    out, stack, seen = [], [], {}
    for p in loop:
        key = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
        if key in seen:
            i = seen[key]
            piece = stack[i:]
            for q in piece[1:]:
                seen.pop((round(q[0], 6), round(q[1], 6), round(q[2], 6)), None)
            del stack[i + 1:]
            if len(piece) >= 3:
                out.append(piece)
        else:
            seen[key] = len(stack); stack.append(p)
    if len(stack) >= 3:
        out.append(stack)
    return out or [loop]


def triangulate(loops3d, normal, _split=True):
    """loops3d: list of lists of (x,y,z); first is outer. Returns (points3d, tri index triples)."""
    if _split and len(loops3d) == 1:
        parts = _split_pinched(loops3d[0])
        if len(parts) > 1 or len(parts[0]) != len(loops3d[0]):   # loop touches itself or has a zero-width spike at a repeated vertex: triangulate each simple piece
            def sarea(pt):   # signed area along the face normal
                x = y = z = 0.0
                for i in range(len(pt)):
                    p0, p1 = pt[i], pt[(i + 1) % len(pt)]
                    x += (p0[1] - p1[1]) * (p0[2] + p1[2]); y += (p0[2] - p1[2]) * (p0[0] + p1[0]); z += (p0[0] - p1[0]) * (p0[1] + p1[1])
                return (x * normal[0] + y * normal[1] + z * normal[2]) / 2
            sa = [sarea(pt) for pt in parts]
            big = max(range(len(parts)), key=lambda i: abs(sa[i]))
            # pieces wound against the largest one are holes touching the boundary (a slit), not extra faces
            holes = [pt for i, pt in enumerate(parts) if i != big and sa[i] * sa[big] < 0]
            rest = [pt for i, pt in enumerate(parts) if i != big and sa[i] * sa[big] >= 0]
            groups = [[parts[big]] + holes] + [[pt] for pt in rest]
            P3, tris = [], []
            for g in groups:
                sp, st = triangulate(g, normal, _split=False)
                off = len(P3); P3.extend(sp); tris.extend((a + off, b + off, c + off) for a, b, c in st)
            return P3, tris
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
        cand = sorted(range(len(outer)), key=lambda k: (P2[outer[k]][0] - P2[hi][0]) ** 2 + (P2[outer[k]][1] - P2[hi][1]) ** 2)
        others = [h for h in rings[1:] if h is not hole]
        best = cand[0]
        for k in cand[:60]:   # nearest outer vertex whose bridge does not cross the ring or another hole
            if _bridge_clear(P2, hi, outer[k], outer, hole, others):
                best = k
                break
        hp = hole.index(hi)
        hr = hole[hp:] + hole[:hp]
        if P2[hi] == P2[outer[best]]:   # hole touches the ring at an existing vertex: splice without a bridge
            d1 = len(P3)
            P3.append(P3[hi]); P2.append(P2[hi])
            outer = outer[: best + 1] + hr[1:] + [d1] + outer[best + 1 :]
            continue
        d1, d2 = len(P3), len(P3) + 1  # duplicated bridge endpoints get their own node ids
        # copies of the bridge ends are nudged sideways by a tiny amount so the slit has positive width and the ring
        # stays strictly simple (exactly coincident vertices break ear tests); P3 keeps the exact positions
        bx, by = P2[outer[best]][0] - P2[hi][0], P2[outer[best]][1] - P2[hi][1]
        bl = math.hypot(bx, by) or 1.0
        ox, oy = -by / bl * bl * 1e-7, bx / bl * bl * 1e-7
        P3.extend((P3[hi], P3[outer[best]]))
        P2.extend(((P2[hi][0] + ox, P2[hi][1] + oy), (P2[outer[best]][0] + ox, P2[outer[best]][1] + oy)))
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
    holes = len(rings) > 1
    alive = set(idx)   # with bridged holes the ring touches itself: test every remaining vertex, not only reflex ones
    cur, left, fails = idx[0], n, 0
    while left > 3:
        a, c = prv[cur], nxt[cur]
        ok = cur not in refl and _area2(P2, a, cur, c) > 1e-12
        if ok and (alive if holes else refl):
            xs = (P2[a][0], P2[cur][0], P2[c][0]); ys = (P2[a][1], P2[cur][1], P2[c][1])
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            pa, pb, pc = P2[a], P2[cur], P2[c]
            for r in (alive if holes else refl):
                if r == a or r == cur or r == c:
                    continue
                q = P2[r]
                if q[0] < x0 or q[0] > x1 or q[1] < y0 or q[1] > y1:
                    continue
                if q == pa or q == pb or q == pc:
                    # coincident bridge duplicate: blocks only if one of its own neighbours lies strictly inside
                    if any(_strict_in_tri(P2, a, cur, c, w) or _seg_cross(pa, pc, P2[r], P2[w]) for w in (prv[r], nxt[r])):
                        ok = False
                        break
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
            refl.discard(cur); alive.discard(cur)
            cur = c
        else:
            cur = c
            fails += 1
            if fails > left:  # no ear found: drop a vertex to make progress
                a, c = prv[cur], nxt[cur]
                nxt[a], prv[c] = c, a
                refl.discard(cur); alive.discard(cur)
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


def _flips(m):
    """True if the transform mirrors (negative determinant), which reverses triangle winding."""
    a = m[:9]
    det = (a[0] * (a[4] * a[8] - a[5] * a[7]) - a[1] * (a[3] * a[8] - a[5] * a[6])
           + a[2] * (a[3] * a[7] - a[4] * a[6]))
    s = m[12] or 1.0
    return det * s * s * s < 0


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
            buf = res.setdefault(mat if mat in model.materials else None, [])
            flip = _flips(m)
            for t in tris:
                for p in (t[::-1] if flip else t):
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


def _lin(c):
    """sRGB byte -> linear float (glTF baseColorFactor is linear)."""
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def write_glb(model, path, edges=True):
    seg = [] if edges else None
    import gc
    was = gc.isenabled(); gc.disable()
    try:
        res = flatten(model, lines=seg)
    finally:
        if was:
            gc.enable()
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
                         pbrMetallicRoughness=dict(baseColorFactor=[_lin(c) for c in mt["rgb"]] + [mt["alpha"]],
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
