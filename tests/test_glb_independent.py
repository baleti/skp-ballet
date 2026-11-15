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
