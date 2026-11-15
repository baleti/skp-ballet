"""Independent GLB consumer (item 286): decodes the written GLB bytes with struct only (no skp-ballet code on the read
side) and compares total triangle area with outer-minus-holes computed from the parsed model, for fixtures without
instances (so no transform composition is needed). Axis swap and the inch->metre scale are applied by the reference."""
import glob, json, math, os, struct
import pytest
from skpballet import open_skp, mesh
from skpballet.scene import load, INCH

D = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(os.path.join(D, "*.skp")) + glob.glob(os.path.join(D, "legacy", "*.skp")))


def _glb_area(path):
    b = open(path, "rb").read()
    assert b[:4] == b"glTF"
    jl = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + jl])
    bin_ = b[20 + jl + 8:]
    area = 0.0
    for me in j.get("meshes", []):
        for pr in me["primitives"]:
            if pr.get("mode", 4) != 4:
                continue
            pos = j["accessors"][pr["attributes"]["POSITION"]]
            bv = j["bufferViews"][pos["bufferView"]]
            o = bv.get("byteOffset", 0) + pos.get("byteOffset", 0)
            P = [struct.unpack_from("<3f", bin_, o + 12 * i) for i in range(pos["count"])]
            if "indices" in pr:
                ia = j["accessors"][pr["indices"]]
                iv = j["bufferViews"][ia["bufferView"]]
                fmt, sz = {5123: ("<H", 2), 5125: ("<I", 4)}[ia["componentType"]]
                io = iv.get("byteOffset", 0) + ia.get("byteOffset", 0)
                idx = [struct.unpack_from(fmt, bin_, io + sz * i)[0] for i in range(ia["count"])]
            else:
                idx = list(range(len(P)))
            for k in range(0, len(idx) - 2, 3):
                a, bb, c = P[idx[k]], P[idx[k + 1]], P[idx[k + 2]]
                u = [bb[i] - a[i] for i in range(3)]; v = [c[i] - a[i] for i in range(3)]
                cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                area += 0.5 * math.sqrt(sum(x * x for x in cr))
    return area


def _loop_area(vs, loop):
    pts = [vs[i] for i in loop]
    n = [0.0, 0.0, 0.0]
    for i in range(len(pts)):
        p, q = pts[i], pts[(i + 1) % len(pts)]
        n[0] += (p[1] - q[1]) * (p[2] + q[2]); n[1] += (p[2] - q[2]) * (p[0] + q[0]); n[2] += (p[0] - q[0]) * (p[1] + q[1])
    return 0.5 * math.sqrt(sum(x * x for x in n))


def _xf(m, p):
    # reference re-statement of the documented transform: p' = s * (p . R + t), applied point by point (no composition)
    s = m[12] or 1.0
    return tuple(s * (p[0] * m[0 + k] + p[1] * m[3 + k] + p[2] * m[6 + k] + m[9 + k]) for k in range(3))


def _ref_area(model):
    total = 0.0

    def walk(d, chain, depth):
        nonlocal total
        if depth > 20:
            raise RecursionError
        for fc in d.faces:
            lp = fc["loops"]
            if not lp:
                continue
            def tr(pt):
                for m in reversed(chain):   # innermost instance applies first
                    pt = _xf(m, pt)
                return pt
            vs = {k: tr(v) for k, v in d.vertices.items()}
            total += (_loop_area(vs, lp[0]) - sum(_loop_area(vs, h) for h in lp[1:])) * INCH * INCH
        for ins in d.instances:
            sub = model.defs.get(ins["def_id"])
            if sub is not None:
                walk(sub, chain + [ins["matrix"]], depth + 1)
    walk(model.root, [], 0)
    return total


@pytest.mark.parametrize("f", FILES)
def test_glb_area_matches_model_area(f, tmp_path):
    try:
        m = load(open_skp(f))
    except Exception:
        pytest.skip("unreadable fixture")
    if any("instance-to-definition lin" in w or "cycle" in w for w in m.warnings):
        pytest.skip("instance links unpinned or cyclic in this fixture")
    out = str(tmp_path / "o.glb")
    mesh.write_glb(m, out)
    ref = _ref_area(m)
    got = _glb_area(out)
    if m.counts()["faces"]:
        assert ref > 0 and got > 0
    assert got == pytest.approx(ref, rel=2e-3, abs=1e-9), (got, ref)


@pytest.mark.parametrize("f", FILES)
def test_triangle_winding_follows_the_stored_face_normal(f):
    """every triangle of every face of every public fixture is counter-clockwise seen from the file's own face normal
    (a reversed triangle would be culled as a hole in a viewer)"""
    try:
        m = load(open_skp(f))
    except Exception:
        pytest.skip("unreadable fixture")
    for d in [m.root] + list(m.defs.values()):
        for fc in d.faces:
            n = fc.get("normal")
            if not fc["loops"] or not n:
                continue
            try:
                L = [[d.vertices[i] for i in l] for l in fc["loops"]]
            except KeyError:
                continue
            P, tr = mesh.triangulate(L, n)
            for a, b, c in tr:
                u = [P[b][i] - P[a][i] for i in range(3)]; v = [P[c][i] - P[a][i] for i in range(3)]
                cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                assert sum(x * y for x, y in zip(cr, n)) >= -1e-12


def _glb_tri_normals(path):
    b = open(path, "rb").read()
    jl = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + jl]); bin_ = b[20 + jl + 8:]
    out = []
    for pr in j["meshes"][0]["primitives"]:
        if pr.get("mode", 4) != 4:
            continue
        pos = j["accessors"][pr["attributes"]["POSITION"]]
        o = j["bufferViews"][pos["bufferView"]].get("byteOffset", 0) + pos.get("byteOffset", 0)
        P = [struct.unpack_from("<3f", bin_, o + 12 * i) for i in range(pos["count"])]
        if "indices" in pr:
            ia = j["accessors"][pr["indices"]]
            io = j["bufferViews"][ia["bufferView"]].get("byteOffset", 0) + ia.get("byteOffset", 0)
            fmt, sz = {5123: ("<H", 2), 5125: ("<I", 4)}[ia["componentType"]]
            idx = [struct.unpack_from(fmt, bin_, io + sz * i)[0] for i in range(ia["count"])]
        else:
            idx = list(range(len(P)))
        for k in range(0, len(idx), 3):
            a, bb, c = (P[i] for i in idx[k:k + 3])
            u = [bb[i] - a[i] for i in range(3)]; v = [c[i] - a[i] for i in range(3)]
            out.append((u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]))
    return out


@pytest.mark.parametrize("diag,want", [((1, 1, 1), (0, 1, 0)), ((-1, 1, 1), (0, 1, 0)), ((1, 1, -1), (0, -1, 0)),
                                       ((-1, -1, 1), (0, 1, 0)), ((-1, -1, -1), (0, -1, 0))])
def test_mirrored_instances_keep_outward_winding(diag, want, tmp_path):
    """a face with normal +z in a definition; the instance matrix scales axes by `diag` (negative = mirror).
    World normal = (0,0,sign(dz)) which the Y-up export maps to (0, sign, 0): the GLB triangles must wind that way
    (read back with the struct-only consumer)."""
    from skpballet import scene
    m = scene.Model(); d = scene.Definition(1, "c"); m.defs[1] = d
    d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0)}
    d.faces = [dict(id=1, loops=[[0, 1, 2, 3]], mat=None, normal=(0, 0, 1))]
    m.root = scene.Definition(0, "<model>")
    m.root.instances = [dict(def_id=1, matrix=[diag[0], 0, 0, 0, diag[1], 0, 0, 0, diag[2], 0, 0, 0, 1.0], name="i", id=None)]
    out = str(tmp_path / "o.glb"); mesh.write_glb(m, out)
    ns = _glb_tri_normals(out)
    assert ns
    for n in ns:
        assert n[0] == pytest.approx(0, abs=1e-12) and n[2] == pytest.approx(0, abs=1e-12)
        assert n[1] * want[1] > 0, (diag, n)


def test_random_general_transforms_nested_keep_winding(tmp_path):
    """random invertible 3x3 (rotation, shear, non-uniform and negative scale), translation and uniform scale s, nested two
    levels. Reference: transform three face points point by point (_xf), take the world normal from the transformed
    points, apply the Y-up swap (x,y,z)->(x,z,-y); every GLB triangle must have a positive dot with it."""
    import random
    from skpballet import scene
    rnd = random.Random(309)
    checked = 0
    for it in range(60):
        def rm():
            while True:
                a = [rnd.uniform(-2, 2) for _ in range(9)]
                det = (a[0] * (a[4] * a[8] - a[5] * a[7]) - a[1] * (a[3] * a[8] - a[5] * a[6]) + a[2] * (a[3] * a[7] - a[4] * a[6]))
                if abs(det) > 0.3:
                    return a + [rnd.uniform(-5, 5) for _ in range(3)] + [rnd.choice([1.0, 1.0, 2.5, 0.4])]
        m1, m2 = rm(), rm()
        m = scene.Model(); inner = scene.Definition(2, "in"); outer = scene.Definition(1, "out"); m.defs = {1: outer, 2: inner}
        inner.vertices = {0: (0, 0, 0), 1: (3, 0, 0), 2: (3, 2, 0), 3: (0, 2, 0)}
        inner.faces = [dict(id=1, loops=[[0, 1, 2, 3]], mat=None, normal=(0, 0, 1))]
        outer.instances = [dict(def_id=2, matrix=m2, name="b", id=None)]
        m.root = scene.Definition(0, "<model>")
        m.root.instances = [dict(def_id=1, matrix=m1, name="a", id=None)]
        out = str(tmp_path / "o.glb"); mesh.write_glb(m, out)
        W = [_xf(m1, _xf(m2, p)) for p in ((0, 0, 0), (3, 0, 0), (3, 2, 0))]
        u = [W[1][i] - W[0][i] for i in range(3)]; v = [W[2][i] - W[0][i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        # the cross product of transformed points is det * (cofactor . n): a mirror reverses it, but the face's front side maps
        # to the front side, so the expected normal is the cofactor image: multiply by sign(det) of the composite linear part
        o = _xf(m1, _xf(m2, (0, 0, 0)))
        ax = [tuple(c - oc for c, oc in zip(_xf(m1, _xf(m2, e)), o)) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        det = (ax[0][0] * (ax[1][1] * ax[2][2] - ax[1][2] * ax[2][1]) - ax[0][1] * (ax[1][0] * ax[2][2] - ax[1][2] * ax[2][0])
               + ax[0][2] * (ax[1][0] * ax[2][1] - ax[1][1] * ax[2][0]))
        sg = 1 if det > 0 else -1
        want = (sg * n[0], sg * n[2], -sg * n[1])
        for t in _glb_tri_normals(out):
            assert sum(x * y for x, y in zip(t, want)) > 0, it
            checked += 1
    assert checked >= 120
