"""Flatten a Model to triangles per material (metres, Y-up) and write GLB."""
import json
import heapq
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


def _locally_inside(P2, ring, k, t):
    """Does direction ring[k] -> t leave through the interior angle of a CCW ring at vertex k?"""
    n = len(ring)
    a, b, c = P2[ring[k - 1]], P2[ring[k]], P2[ring[(k + 1) % n]]
    def cr(u, w):
        return u[0] * w[1] - u[1] * w[0]
    dc, da, dt = (c[0] - b[0], c[1] - b[1]), (a[0] - b[0], a[1] - b[1]), (t[0] - b[0], t[1] - b[1])
    if cr((b[0] - a[0], b[1] - a[1]), dc) >= 0:   # convex (or straight)
        return cr(dc, dt) >= 0 and cr(dt, da) >= 0
    return cr(dc, dt) >= 0 or cr(dt, da) >= 0


def _seg_cross(a, b, c, d):
    """proper intersection of segments ab and cd (shared endpoints and touching do not count)"""
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = o(a, b, c), o(a, b, d), o(c, d, a), o(c, d, b)
    return ((o1 > 1e-12 and o2 < -1e-12) or (o1 < -1e-12 and o2 > 1e-12)) and \
           ((o3 > 1e-12 and o4 < -1e-12) or (o3 < -1e-12 and o4 > 1e-12))


def _bridge_clear(P2, hi, oi, outer, hole, others, obb=None):
    a, b = P2[hi], P2[oi]
    x0, x1 = (a[0], b[0]) if a[0] < b[0] else (b[0], a[0])
    y0, y1 = (a[1], b[1]) if a[1] < b[1] else (b[1], a[1])
    for ring in [outer, hole] + others:
        if obb is not None and id(ring) in obb:   # unchanged hole ring: skip when its box cannot touch the bridge box (same result, avoids the O(N) scan)
            r0, r1, s0, s1 = obb[id(ring)]
            if r1 < x0 or r0 > x1 or s1 < y0 or s0 > y1:
                continue
        n = len(ring)
        c = P2[ring[0]]
        for k in range(n):
            d = P2[ring[k + 1 if k + 1 < n else 0]]
            # bounding-box reject first: a proper crossing needs overlapping boxes (cheap, avoids most cross tests)
            if not ((c[0] < x0 and d[0] < x0) or (c[0] > x1 and d[0] > x1) or
                    (c[1] < y0 and d[1] < y0) or (c[1] > y1 and d[1] > y1)) and _seg_cross(a, b, c, d):
                return False
            c = d
    # a ring vertex lying ON the bridge (e.g. a diagonal through a hole corner) makes a degenerate ring: reject
    ex, ey = b[0] - a[0], b[1] - a[1]
    el = ex * ex + ey * ey
    if el > 0:
        for ring in [outer, hole] + others:
            if obb is not None and id(ring) in obb:
                r0, r1, s0, s1 = obb[id(ring)]
                if r1 < x0 or r0 > x1 or s1 < y0 or s0 > y1:
                    continue
            for i in ring:
                q = P2[i]
                if i in (hi, oi) or q == a or q == b or q[0] < x0 or q[0] > x1 or q[1] < y0 or q[1] > y1:
                    continue
                if abs(ex * (q[1] - a[1]) - ey * (q[0] - a[0])) <= 1e-9 * el ** 0.5 and 0 < ((q[0] - a[0]) * ex + (q[1] - a[1]) * ey) < el:
                    return False
    return True


def _insert_touching(loop):
    """A vertex lying on the interior of a non-adjacent edge (T-touch) is inserted into that edge as a repeated
    vertex, so the loop becomes an ordinary pinched loop."""
    n = len(loop)
    if n < 4 or n > 600:
        return loop
    out = [[p] for p in loop]   # points to insert after each vertex
    found = False
    for i in range(n):
        p = loop[i]
        for j in range(n):
            if j == i or (j + 1) % n == i:
                continue
            a, b = loop[j], loop[(j + 1) % n]
            if p == a or p == b:
                continue
            dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            L2 = dx * dx + dy * dy + dz * dz
            if L2 == 0:
                continue
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy + (p[2] - a[2]) * dz) / L2
            if t <= 1e-9 or t >= 1 - 1e-9:
                continue
            qx, qy, qz = a[0] + t * dx - p[0], a[1] + t * dy - p[1], a[2] + t * dz - p[2]
            if qx * qx + qy * qy + qz * qz <= 1e-14 * max(L2, 1.0):
                out[j].append(p); found = True
    return [q for pts in out for q in pts] if found else loop


def _insert_hole_touches(outer, holes):
    """A hole vertex lying on the interior of an outer-ring edge (T-touch) is inserted into that edge, so the bridge phase sees the
    contact as a shared ring vertex (it only recognises touching at existing vertices)."""
    n = len(outer)
    if n < 3 or sum(len(h) for h in holes) * n > 300000:
        return outer
    add = {}   # edge index -> [(t, point)]
    for h in holes:
        mine = {}
        for p in h:
            for j in range(n):
                a, b = outer[j], outer[(j + 1) % n]
                if p == a or p == b:
                    continue
                dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                L2 = dx * dx + dy * dy + dz * dz
                if L2 == 0:
                    continue
                t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy + (p[2] - a[2]) * dz) / L2
                if t <= 1e-9 or t >= 1 - 1e-9:
                    continue
                qx, qy, qz = a[0] + t * dx - p[0], a[1] + t * dy - p[1], a[2] + t * dz - p[2]
                if qx * qx + qy * qy + qz * qz <= 1e-14 * max(L2, 1.0):
                    mine.setdefault(j, []).append((t, p))
        for j, lst in mine.items():
            for item in lst:
                if all(q != item[1] for _, q in add.get(j, ())):
                    add.setdefault(j, []).append(item)
    if not add:
        return outer
    out = []
    for j in range(n):
        out.append(outer[j]); out.extend(q for _, q in sorted(add.get(j, ())))
    return out


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


def _merge_edge_sharing_holes(holes):
    """Two holes that share an edge enclose a zero-width wall: they are one hole. Without this one of them was left filled.
    Rings are merged along the shared edge (points compared exactly); no shared edge -> input returned unchanged."""
    seen = {}   # undirected edge -> index of the hole that has it; no edge in two different holes -> nothing to merge (linear fast path)
    shared = set()
    for hi, h in enumerate(holes):
        for i in range(len(h)):
            e = frozenset((h[i], h[(i + 1) % len(h)]))
            if seen.setdefault(e, hi) != hi:
                shared.add(seen[e]); shared.add(hi)
    if not shared:
        return holes
    keep = [list(h) for hi, h in enumerate(holes) if hi not in shared]
    holes = [list(h) for hi, h in enumerate(holes) if hi in shared]
    changed = True
    while changed and len(holes) > 1:
        changed = False
        for ia in range(len(holes)):
            A = holes[ia]
            ea = {(A[i], A[(i + 1) % len(A)]): i for i in range(len(A))}
            for ib in range(ia + 1, len(holes)):
                B = holes[ib]
                for sw in (False, True):
                    Bc = B[::-1] if sw else B
                    for j in range(len(Bc)):
                        v, u = Bc[j], Bc[(j + 1) % len(Bc)]
                        i = ea.get((u, v))
                        if i is None:
                            continue
                        n = len(Bc)
                        path = [Bc[(j + 2 + k) % n] for k in range(n - 2)]   # u's successor .. v's predecessor
                        merged = A[:i + 1] + path + A[i + 1:]
                        k = 0
                        while len(merged) >= 3 and k < len(merged):   # a second shared edge leaves a zero-width spike p,c,p: drop it
                            n2 = len(merged)
                            if merged[k - 1] == merged[(k + 1) % n2]:
                                for r in sorted({k, (k + 1) % n2}, reverse=True):
                                    del merged[r]
                                k = 0
                            else:
                                k += 1
                        if len(merged) >= 3:
                            holes[ia] = merged
                            del holes[ib]
                            changed = True
                        break
                    if changed:
                        break
                if changed:
                    break
            if changed:
                break
    return holes + keep


def _merge_corner_touching_holes(holes):
    """Fallback for holes that touch other holes at single points (chains of corner contacts): two rings sharing a point are
    spliced into one pinched ring (point visited twice), which the pinch handling of the triangulator understands."""
    holes = [list(h) for h in holes]
    done = False
    while not done and len(holes) > 1:
        done = True
        for ia in range(len(holes)):
            for ib in range(ia + 1, len(holes)):
                A, B = holes[ia], holes[ib]
                common = next((p for p in A if p in B), None)
                if common is None:
                    continue
                i, j = A.index(common), B.index(common)
                holes[ia] = A[:i + 1] + B[j + 1:] + B[:j + 1] + A[i + 1:]
                del holes[ib]
                done = False
                break
            if not done:
                break
    return holes


def triangulate(loops3d, normal, _split=True):
    """loops3d: list of lists of (x,y,z); first is outer. Returns (points3d, tri index triples).
    A face with holes whose triangle area is off (exact ties/colinearity in the 2D working plane confuse the bridge and ear
    tests) is retried with the 2D basis rotated by a few arbitrary angles; the best result wins."""
    if len(loops3d) > 2:
        loops3d = [loops3d[0]] + _merge_edge_sharing_holes(loops3d[1:])
    P = tr = None
    if len(loops3d) > 1:
        ins = [_insert_hole_touches(loops3d[0], loops3d[1:])] + loops3d[1:]
        if len(ins[0]) != len(loops3d[0]):   # hole vertices lie on outer edges: use the outer with them inserted, unless that is worse (a hole running along an outer edge)
            P, tr = _triangulate(ins, normal, _split, 0.0)
            if _area_mismatch(ins, normal, P, tr, 1e-6):
                P0, t0 = _triangulate(loops3d, normal, _split, 0.0)
                if _area_err(loops3d, normal, P0, t0) < _area_err(loops3d, normal, P, tr):
                    P, tr = P0, t0
                else:
                    loops3d = ins
            else:
                loops3d = ins
    if P is None:
        P, tr = _triangulate(loops3d, normal, _split, 0.0)
    if len(loops3d) > 1 and len(P) <= 3000 and _area_mismatch(loops3d, normal, P, tr, 1e-6):   # size cap: retries cost up to 5x on hopeless faces
        best, be = (P, tr), _area_err(loops3d, normal, P, tr)
        for ang in (0.3711, 1.0173, 2.2391, 4.0877):
            P2, t2 = _triangulate(loops3d, normal, _split, ang)
            e = _area_err(loops3d, normal, P2, t2)
            if e < be:
                best, be = (P2, t2), e
            if be <= 1e-6:
                break
        if be > 1e-6 and len(loops3d) > 2:   # chains of corner-touching holes: retry with touching holes spliced into pinched rings
            L2 = [loops3d[0]] + _merge_corner_touching_holes(loops3d[1:])
            if len(L2) < len(loops3d):
                P2, t2 = _triangulate(L2, normal, _split, 0.0)
                if _area_err(loops3d, normal, P2, t2) < be:
                    best, be = (P2, t2), _area_err(loops3d, normal, P2, t2)
        if be > 1e-6 and len(loops3d) > 2:   # last resort: holes that still touch each other are shrunk toward their centroid, which un-touches them. 1e-6 first; near-touching holes can still confuse the bridge, so 1e-4 and 1e-3 follow. Accepted only if it improves the area and stays within 1e-4 + 2*f (relative error the shrink itself costs)
            def shrink(h, f):
                n = len(h); c = [sum(p[k] for p in h) / n for k in range(3)]
                return [tuple(p[k] + (c[k] - p[k]) * f for k in range(3)) for p in h]
            for f in (1e-6, 1e-4, 1e-3):
                P2, t2 = _triangulate([loops3d[0]] + [shrink(h, f) for h in loops3d[1:]], normal, _split, 0.0)
                e = _area_err(loops3d, normal, P2, t2)
                if e < be and e <= 1e-4 + 2 * f:
                    best, be = (P2, t2), e
                if be <= 1e-4:
                    break
        return best
    return P, tr


def _triangulate(loops3d, normal, _split, ang):
    if _split and len(loops3d) == 1:
        parts = _split_pinched(_insert_touching(loops3d[0]))
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
                sp, st = _triangulate(g, normal, False, ang)
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
    if ang:   # rotate the 2D basis about the normal
        ca, sa = math.cos(ang), math.sin(ang)
        ux, uy = tuple(ca * a + sa * b for a, b in zip(ux, uy)), tuple(-sa * a + ca * b for a, b in zip(ux, uy))
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
    if len(rings) > 1:   # a hole entirely outside the outer ring (corrupt/odd file) would be bridged into garbage area: drop it
        def inside(pt):
            x, y, c = pt[0], pt[1], False
            for k in range(len(outer)):
                a, b = P2[outer[k - 1]], P2[outer[k]]
                if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                    c = not c
            return c
        def keep(h):
            mean = (sum(P2[i][0] for i in h) / len(h), sum(P2[i][1] for i in h) / len(h))
            return inside(mean) or any(inside(P2[i]) for i in h)
        rings = [outer] + [h for h in rings[1:] if keep(h)]
    # bridge holes (rightmost hole vertex first) into the outer ring
    obb = {}
    for h in rings[1:]:
        xs = [P2[i][0] for i in h]; ys = [P2[i][1] for i in h]
        obb[id(h)] = (min(xs), max(xs), min(ys), max(ys))
    ringcoords = {P2[i] for i in outer}   # 2D positions of every node already in the ring
    for hole in sorted(rings[1:], key=lambda h: -max(P2[i][0] for i in h)):
        hi = max(hole, key=lambda i: P2[i][0])
        touch = None   # a hole vertex that coincides with a ring vertex (hole touching the boundary): splice there
        pos2 = {}
        if any(P2[hv] in ringcoords for hv in hole):   # positions are only needed when the hole can touch the ring
            for kk, oi in enumerate(outer):
                pos2.setdefault(P2[oi], []).append(kk)
        for hv in hole:
            for kk in pos2.get(P2[hv], ()):
                hn = hole[(hole.index(hv) + 1) % len(hole)]
                if _locally_inside(P2, outer, kk, P2[hn]):
                    touch = (hv, kk)
                    break
            if touch:
                break
        ringcoords.update(P2[i] for i in hole)   # the hole joins the ring below
        if touch:
            hi = touch[0]
        hx, hy = P2[hi]
        dd = [(P2[o][0] - hx) ** 2 + (P2[o][1] - hy) ** 2 for o in outer]; cand = sorted(range(len(outer)), key=dd.__getitem__)[:60]   # only the nearest 60 are ever tried
        others = [h for h in rings[1:] if h is not hole]
        best = cand[0]
        if touch:
            cand = [touch[1]]
            best = touch[1]
        for k in cand[:60]:   # nearest outer vertex whose bridge does not cross the ring or another hole
            if _locally_inside(P2, outer, k, P2[hi]) and _bridge_clear(P2, hi, outer[k], outer, hole, others, obb):
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
    grid = None   # uniform grid over the reflex vertices (outline without holes, many vertices): same candidate set, fewer tests
    if (len(idx) > 600) if holes else (len(refl) > 256):
        xs_ = [P2[v][0] for v in idx]; ys_ = [P2[v][1] for v in idx]
        gx0, gy0 = min(xs_), min(ys_)
        gn = int(len(refl) ** 0.5) or 1
        gw = max(max(xs_) - gx0, max(ys_) - gy0, 1e-12) / gn
        grid = {}

        def cell_xy(x, y):
            return (max(0, min(gn - 1, int((x - gx0) / gw))), max(0, min(gn - 1, int((y - gy0) / gw))))

        def cell(v):
            return cell_xy(P2[v][0], P2[v][1])
        for v in (idx if holes else refl):   # with holes every ring vertex is a candidate blocker (the bridged ring touches itself)
            grid.setdefault(cell(v), set()).add(v)
    alive = set(idx)   # with bridged holes the ring touches itself: test every remaining vertex, not only reflex ones
    cur, left, fails = idx[0], n, 0
    while left > 3:
        a, c = prv[cur], nxt[cur]
        ok = cur not in refl and _area2(P2, a, cur, c) > 1e-12
        if ok and (alive if holes else refl):
            xs = (P2[a][0], P2[cur][0], P2[c][0]); ys = (P2[a][1], P2[cur][1], P2[c][1])
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            pa, pb, pc = P2[a], P2[cur], P2[c]
            if grid is not None:
                c0, c1 = cell_xy(x0, y0), cell_xy(x1, y1)
                cand = [r for gi in range(c0[0], c1[0] + 1) for gj in range(c0[1], c1[1] + 1) for r in grid.get((gi, gj), ()) if r in (alive if holes else refl)]
            else:
                cand = alive if holes else refl
            for r in cand:
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
                    if grid is not None:
                        grid.setdefault(cell(v), set()).add(v)
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


def definition_tris(d, warnings=None):
    """-> {mat_id: [triangle tuples of 3 points in inches]}; faces with vertex ids missing from the definition are
    built from the remaining vertices (or skipped) and reported once in `warnings`"""
    out = {}
    for f in d.faces:
        if warnings is not None and any(v not in d.vertices for lp in f["loops"] for v in lp):
            w = "face refers to vertex ids missing from its definition (corrupt file): such faces are incomplete or NOT placed"
            if w not in warnings:
                warnings.append(w)
        loops = [[d.vertices[v] for v in lp if v in d.vertices] for lp in f["loops"]]
        loops = [l for l in loops if l]
        if not loops:
            continue
        nrm = f["normal"] or (0, 0, 1)
        P, tr = triangulate(loops, nrm)
        if warnings is not None and _area_mismatch(loops, nrm, P, tr):
            w = "triangulated face area differs by more than 1%% from outer minus holes in at least one face (degenerate loops or damaged data): "\
                "geometry of such faces may be wrong"
            if w not in warnings:
                warnings.append(w)
        out.setdefault(f["mat"], []).extend((P[a], P[b], P[c]) for a, b, c in tr)
    return out


def _newell(loop):
    x = y = z = 0.0
    for i, p in enumerate(loop):
        q = loop[(i + 1) % len(loop)]
        x += (p[1] - q[1]) * (p[2] + q[2]); y += (p[2] - q[2]) * (p[0] + q[0]); z += (p[0] - q[0]) * (p[1] + q[1])
    return x / 2, y / 2, z / 2


def _area_mismatch(loops, nrm, P, tr, tol=0.01):
    """True if the triangle area (projected on the face normal) differs from outer minus holes by more than tol"""
    return _area_err(loops, nrm, P, tr) > tol


def _area_err(loops, nrm, P, tr):
    """relative difference between the triangle area (projected on the face normal) and outer minus holes"""
    loops = [l for l in loops if len(l) >= 3]
    if not loops or len(loops[0]) < 3:
        return 0.0
    nl = math.sqrt(sum(c * c for c in nrm)) or 1.0
    def proj(v):
        return abs((v[0] * nrm[0] + v[1] * nrm[1] + v[2] * nrm[2]) / nl)
    outer = proj(_newell(loops[0]))
    ax = max(range(3), key=lambda i: abs(nrm[i]))   # drop the dominant normal axis: a fair 2D view for point-in-polygon
    i0, i1 = [k for k in range(3) if k != ax]
    def inside(pt):
        x, y, c = pt[i0], pt[i1], False
        o = loops[0]
        for k in range(len(o)):
            a, b = o[k - 1], o[k]
            if (a[i1] > y) != (b[i1] > y) and x < (b[i0] - a[i0]) * (y - a[i1]) / (b[i1] - a[i1]) + a[i0]:
                c = not c
        return c
    # holes entirely outside the outer loop are dropped by triangulate(), so they do not count here either
    want = outer - sum(proj(_newell(h)) for h in loops[1:]
                       if inside(tuple(sum(v[k] for v in h) / len(h) for k in range(3))) or any(inside(v) for v in h))
    got = 0.0
    for a, b, c in tr:
        pa, pb, pc = P[a], P[b], P[c]
        u = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]); v = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        cx, cy, cz = u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]
        got += abs(cx * nrm[0] + cy * nrm[1] + cz * nrm[2]) / nl / 2
    return abs(got - want) / max(abs(want), outer * 1e-3, 1e-12)


MAX_TRIS = 5_000_000   # triangles emitted per export (flatten and cache)
MAX_PLACEMENTS = 500_000   # instance placements walked per export; an instance bomb (8 instances x 12 levels = 8^12) never finishes otherwise


def _budget_warning(model, n):
    msg = "instance expansion stopped after %d placements: the rest is NOT placed (instance bomb or corrupt file)" % n
    if msg not in model.warnings:
        model.warnings.append(msg)


def _degenerate(m):
    """warning text if an instance transform is zero-scale (read as 1.0) or singular (flattens the geometry), else None"""
    a = m[:9]
    det = (a[0] * (a[4] * a[8] - a[5] * a[7]) - a[1] * (a[3] * a[8] - a[5] * a[6])
           + a[2] * (a[3] * a[7] - a[4] * a[6]))
    if m[12] == 0:
        return "instance with scale 0 read as scale 1 (damaged data or unusual file)"
    if det == 0:
        return "instance with a singular transform: its geometry is flattened (damaged data or unusual file)"
    return None


def note_unexported(model):
    """Annotations and screen texts are read but never exported to GLB/cache: say so once, with counts, so a viewer of the
    export does not take it for the whole model."""
    n_ann = n_txt = 0
    for d in list(model.defs.values()) + [model.root]:
        if d is not None:
            n_ann += len(d.annotations); n_txt += len(d.texts)
    off = getattr(model, "layers_off", None)
    if off:   # the flag meaning is unverified (see FORMAT.md) and per-face layer assignment is not decoded: nothing is hidden
        w = "%d layer(s) carry a hidden/off flag in the file (meaning unverified); their geometry is NOT hidden in this export" % len(off)
        if w not in model.warnings:
            model.warnings.append(w)
    if n_ann or n_txt:
        w = "%d annotation(s) (section planes, guide points, dimensions) and %d screen text(s) are in the file but NOT in this export" % (n_ann, n_txt)
        if w not in model.warnings:
            model.warnings.append(w)


def flatten(model, max_depth=24, max_tris=None, lines=None):
    """Returns {mat_id: flat list of floats (x,y,z per vertex, metres, Y-up)}.
    If `lines` is a list, edge segments (6 floats each, same space) are appended to it."""
    note_unexported(model)
    cache, res, count = {}, {}, [0]
    max_tris = MAX_TRIS if max_tris is None else max_tris
    nodes = [0]

    def emit(tris_by_mat, m):
        for mat, tris in tris_by_mat.items():
            buf = res.setdefault(mat if mat in model.materials else None, [])
            flip = _flips(m)
            for t in tris:
                for p in (t[::-1] if flip else t):
                    x, y, z = _mul(m, p)
                    buf.extend((x * INCH, z * INCH, -y * INCH))
                count[0] += 1

    path = set()   # definitions on the current ancestor chain: an instance of one of them is a cycle (corrupt file)

    def walk(d, m, depth):
        nodes[0] += 1
        if nodes[0] > MAX_PLACEMENTS:
            _budget_warning(model, MAX_PLACEMENTS)
            return
        if depth > max_depth or count[0] > max_tris:
            if "depth/size limit reached" not in model.warnings:
                model.warnings.append("depth/size limit reached")
            return
        if id(d) not in cache:   # object identity: the root (id 0) and a real definition with id 0 must not share an entry
            cache[id(d)] = definition_tris(d, model.warnings)
        emit(cache[id(d)], m)
        if lines is not None:
            for a, b in d.edges.values():
                if a in d.vertices and b in d.vertices:
                    for p in (d.vertices[a], d.vertices[b]):
                        x, y, z = _mul(m, p)
                        lines.extend((x * INCH, z * INCH, -y * INCH))
        path.add(id(d))
        for inst in d.instances:
            sub = model.defs.get(inst["def_id"])
            if sub is None:
                continue
            if id(sub) in path:
                w = "instance cycle: a definition contains itself (corrupt file); the cyclic instance is NOT placed"
                if w not in model.warnings:
                    model.warnings.append(w)
                continue
            w = _degenerate(inst["matrix"])
            if w and w not in model.warnings:
                model.warnings.append(w)
            walk(sub, _compose(m, inst["matrix"]), depth + 1)
        path.discard(id(d))

    walk(model.root, IDENT, 0)
    return res


def sane_color(rgb, alpha):
    """Clamp a material colour to what glTF and the viewers accept: channels int 0..255 (NaN or non-numeric -> 200), alpha 0..1
    (NaN -> 1). Damaged or out-of-range material values must not produce a GLB with factors outside 0..1 or a NaN."""
    def ch(c):
        try:
            c = float(c)
        except (TypeError, ValueError):
            return 200
        return 200 if c != c else int(min(255, max(0, round(c))))
    try:
        a = float(alpha)
    except (TypeError, ValueError):
        a = 1.0
    return [ch(c) for c in list(rgb)[:3]], (1.0 if a != a else min(1.0, max(0.0, a)))


def _lin(c):
    """sRGB byte -> linear float (glTF baseColorFactor is linear)."""
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _check_coords(vals):
    """A GLB with NaN/inf or float32-overflowing positions is invalid: refuse (corrupt input)."""
    for v in vals:
        if not (-1e30 < v < 1e30):   # also false for NaN
            raise ValueError("geometry has non-finite or absurd coordinates (corrupt file?)")


import contextlib


def _sweep_stale_tmp(d, max_age=86400):
    """A process killed mid-write leaves .skpballet-*.tmp behind (the target itself stays intact). Remove our own files of that
    pattern when older than a day, so they do not accumulate next to the user's models; nothing else is touched."""
    import os, time
    try:
        for n in os.listdir(d):
            if n.startswith(".skpballet-") and n.endswith(".tmp"):
                p = os.path.join(d, n)
                if os.path.isfile(p) and not os.path.islink(p) and time.time() - os.path.getmtime(p) > max_age:
                    os.unlink(p)
    except OSError:
        pass


@contextlib.contextmanager
def atomic_open(path, mode="wb", **kw):
    """Write to a temp file in the same directory, then os.replace onto path. Replaces a symlink at path instead of writing
    THROUGH it (a link to a source .skp must never be overwritten) and leaves an existing file intact if the write fails."""
    import os, tempfile
    d = os.path.dirname(os.path.abspath(path))
    _sweep_stale_tmp(d)
    fd, tmp = tempfile.mkstemp(prefix=".skpballet-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, mode, **kw) as f:
            yield f
        um = os.umask(0); os.umask(um)
        try:
            os.chmod(tmp, 0o666 & ~um)   # mkstemp makes 0600; keep the permissions a plain open() would give
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StrictTruncation(ValueError):
    """--strict export refused because a placement/triangle/depth limit truncated the model (nothing is written)."""


def _truncated(model, before):
    return [w for w in model.warnings[before:] if "NOT placed" in w or "depth/size limit" in w or "damaged data" in w]


def write_glb(model, path, edges=True, strict=False):
    seg = [] if edges else None
    nw = len(model.warnings)
    import gc
    was = gc.isenabled(); gc.disable()
    try:
        res = flatten(model, lines=seg)
    finally:
        if was:
            gc.enable()
    if strict and _truncated(model, nw):
        raise StrictTruncation("--strict: export truncated or damaged, nothing written: " + _truncated(model, nw)[0])
    bin_, views, accs, prims, mats = bytearray(), [], [], [], []
    for mid, buf in sorted(res.items(), key=lambda kv: str(kv[0])):
        if not buf:
            continue
        n = len(buf) // 3
        off = len(bin_)
        _check_coords(buf)
        bin_ += struct.pack("<%df" % len(buf), *buf)
        r32 = struct.unpack("<%df" % len(buf), bin_[off:])   # min/max must equal the stored float32 values
        xs, ys, zs = r32[0::3], r32[1::3], r32[2::3]
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(buf) * 4, target=34962))
        accs.append(dict(bufferView=len(views) - 1, componentType=5126, count=n, type="VEC3",
                         min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)]))
        mt = model.materials.get(mid, dict(name="default", rgb=(200, 200, 200), alpha=1.0))
        mt = dict(mt, **dict(zip(("rgb", "alpha"), sane_color(mt["rgb"], mt["alpha"]))))
        mats.append(dict(name=mt["name"], doubleSided=True,
                         pbrMetallicRoughness=dict(baseColorFactor=[_lin(c) for c in mt["rgb"]] + [mt["alpha"]],
                                                   metallicFactor=0, roughnessFactor=0.9),
                         **({"alphaMode": "BLEND"} if mt["alpha"] < 1 else {})))
        prims.append(dict(attributes=dict(POSITION=len(accs) - 1), material=len(mats) - 1, mode=4))
    if seg:
        n = len(seg) // 3
        off = len(bin_)
        _check_coords(seg)
        bin_ += struct.pack("<%df" % len(seg), *seg)
        r32 = struct.unpack("<%df" % len(seg), bin_[off:])
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(seg) * 4, target=34962))
        accs.append(dict(bufferView=len(views) - 1, componentType=5126, count=n, type="VEC3",
                         min=[min(r32[0::3]), min(r32[1::3]), min(r32[2::3])],
                         max=[max(r32[0::3]), max(r32[1::3]), max(r32[2::3])]))
        mats.append(dict(name="edges", pbrMetallicRoughness=dict(baseColorFactor=[0.05, 0.05, 0.05, 1],
                                                                 metallicFactor=0, roughnessFactor=1)))
        prims.append(dict(attributes=dict(POSITION=len(accs) - 1), material=len(mats) - 1, mode=1))
    js = dict(asset=dict(version="2.0", generator="skp-ballet", extras=dict(layers=sorted(model.layers.values()), layers_flagged_off=sorted(model.layers[i] for i in model.layers_off if i in model.layers), materials=len(model.materials), warnings=list(model.warnings))), scene=0, scenes=[dict(nodes=[0])],
              nodes=[dict(mesh=0, name="model") if prims else dict(name="model")])
    # glTF 2.0 schema: arrays have minItems 1 and buffer byteLength >= 1, so an empty model omits them
    for k, v in (("meshes", [dict(primitives=prims)] if prims else []), ("materials", mats), ("accessors", accs),
                 ("bufferViews", views), ("buffers", [dict(byteLength=len(bin_))] if bin_ else [])):
        if v:
            js[k] = v
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    with atomic_open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(j) + (8 + len(bin_) if bin_ else 0)))
        f.write(struct.pack("<I4s", len(j), b"JSON") + j)
        if bin_:
            f.write(struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_))
    return sum(len(b) // 9 for b in res.values())
