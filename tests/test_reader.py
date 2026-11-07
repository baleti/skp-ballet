import json, math, os, struct, sys, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from skpballet import open_skp
from skpballet.scene import load
from skpballet.tlv import parse_tlv
from skpballet.mesh import triangulate, flatten, write_glb

D = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(D + "/*.skp"))


def tri_area(P, tris):
    s = 0
    for a, b, c in tris:
        u = [P[b][i] - P[a][i] for i in range(3)]; v = [P[c][i] - P[a][i] for i in range(3)]
        s += 0.5 * math.sqrt(sum(x * x for x in (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])))
    return s


@pytest.mark.parametrize("f", FILES)
def test_counts_match_raw_tags(f):
    s = open_skp(f); m = load(s)
    raw = {}
    def walk(ns):
        for n in ns:
            raw[n.tag] = raw.get(n.tag, 0) + 1; walk(n.children)
    walk(parse_tlv(s.model_dat))
    c = m.counts()
    assert c["vertices"] == raw.get(0x9C4, 0) and c["edges"] == raw.get(0xBB8, 0) and c["faces"] == raw.get(0xDAC, 0)
    assert not m.warnings


def test_not_skp_rejected():
    with pytest.raises(ValueError):
        open_skp(b"hello world")


def test_legacy_refused_cleanly():
    with pytest.raises(ValueError):
        open_skp(b"\xff\xfe\xff\x0eS\x00k\x00" + b"\0" * 64)


def test_triangulate_concave_with_hole_area():
    outer = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (5, 4, 0), (0, 10, 0)]  # concave notch
    hole = [(1, 1, 0), (1, 2, 0), (2, 2, 0), (2, 1, 0)]
    P, t = triangulate([outer, hole], (0, 0, 1))
    area_outer = 0.5 * abs(sum(outer[i][0]*outer[(i+1) % 5][1] - outer[(i+1) % 5][0]*outer[i][1] for i in range(5)))
    assert tri_area(P, t) == pytest.approx(area_outer - 1.0)


def test_triangulate_many_holes_is_fast():
    outer = [(0, 0, 0), (200, 0, 0), (200, 200, 0), (0, 200, 0)]
    holes = [[(i*10+2, j*10+2, 0), (i*10+2, j*10+5, 0), (i*10+5, j*10+5, 0), (i*10+5, j*10+2, 0)] for i in range(15) for j in range(15)]
    P, t = triangulate([outer] + holes, (0, 0, 1))
    assert tri_area(P, t) == pytest.approx(200 * 200 - 225 * 9)


def test_scale_term_and_translation():
    m = load(open_skp(os.path.join(D, "instance_scale_term_2021.skp")))
    r = flatten(m)[None]
    xs = [x / 0.0254 for x in r[0::3]]
    # a 1 in cube at x=0 and another at x=20 in (SketchUp reports both), no 100x blow-up
    assert min(xs) == pytest.approx(0, abs=1e-6) and max(xs) == pytest.approx(21, abs=1e-6)


def test_nesting_chain_flattens_all_faces():
    m = load(open_skp(os.path.join(D, "nesting_2021.skp")))
    assert sum(len(v) for v in flatten(m).values()) // 9 == 6


@pytest.mark.parametrize("f", FILES)
def test_glb_valid(f, tmp_path):
    m = load(open_skp(f)); p = tmp_path / "o.glb"
    n = write_glb(m, str(p))
    d = p.read_bytes()
    magic, ver, ln = struct.unpack_from("<4sII", d)
    assert magic == b"glTF" and ver == 2 and ln == len(d) and n > 0
    jl = struct.unpack_from("<I", d, 12)[0]
    j = json.loads(d[20:20 + jl])
    tri = [pr for pr in j["meshes"][0]["primitives"] if pr.get("mode", 4) == 4]
    assert sum(j["accessors"][pr["attributes"]["POSITION"]]["count"] for pr in tri) == n * 3
    lines = [pr for pr in j["meshes"][0]["primitives"] if pr.get("mode") == 1]
    assert len(lines) == 1 and j["accessors"][lines[0]["attributes"]["POSITION"]]["count"] % 2 == 0


@pytest.mark.parametrize("f", FILES)
def test_edge_segments_match_instanced_edge_count(f):
    m = load(open_skp(f)); seg = []
    flatten(m, lines=seg)

    def count(d, depth=0):
        c = sum(1 for a, b in d.edges.values() if a in d.vertices and b in d.vertices)
        return c + sum(count(m.defs[i["def_id"]], depth + 1) for i in d.instances if i["def_id"] in m.defs)
    assert len(seg) == count(m.root) * 6 and len(seg) > 0


def test_viewer_server_smoke(tmp_path):
    import threading, urllib.request, http.server
    from skpballet import cli
    if not cli._find_web():
        pytest.skip("three.js vendor dir not available")
    m = load(open_skp(os.path.join(D, "nesting_2021.skp"))); g = tmp_path / "m.glb"; write_glb(m, str(g))
    t = threading.Thread(target=cli.serve, args=(str(g), 18765, False), daemon=True); t.start()
    import time; time.sleep(0.5)
    assert urllib.request.urlopen("http://127.0.0.1:18765/model.glb").read()[:4] == b"glTF"
    assert b"three" in urllib.request.urlopen("http://127.0.0.1:18765/").read()
    assert len(urllib.request.urlopen("http://127.0.0.1:18765/vendor/three/three.module.js").read()) > 100000


def test_corrupt_inputs_fail_cleanly():
    """Truncated and byte-flipped files raise SkpError only (no IndexError, zlib.error, hangs)."""
    import os, random
    from skpballet import container, scene, mesh
    d = open(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"), "rb").read()
    rnd = random.Random(1)
    cases = [d[:int(len(d) * f)] for f in (0, .01, .1, .5, .9, .99)]
    for _ in range(60):
        b = bytearray(d)
        for _ in range(rnd.choice((1, 3, 20))):
            b[rnd.randrange(len(b))] = rnd.randrange(256)
        cases.append(bytes(b))
    for c in cases:
        try:
            mesh.flatten(scene.load(container.open_skp(c)))
        except container.SkpError:
            pass


def test_cli_info_json(capsys):
    from skpballet.cli import main
    assert main(["info", "--json", os.path.join(D, "nesting_2021.skp")]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["counts"]["faces"] > 0 and len(j["bbox_m"]) == 2
    assert all(a <= b for a, b in zip(*j["bbox_m"]))


def test_vendor_path_cannot_escape(tmp_path):
    from skpballet.cli import safe_join
    root = tmp_path / "v"; (root / "three").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("x")
    ok = safe_join(str(root), "three/a.js")
    assert ok == os.path.join(os.path.realpath(str(root)), "three", "a.js")
    for bad in ("../secret.txt", "..%2fsecret.txt", "%2e%2e/secret.txt", "..\\secret.txt",
                "/etc/passwd", "three/../../secret.txt", "C:\\Windows\\win.ini", "a\0b"):
        r = safe_join(str(root), bad)
        assert not os.path.exists(r), bad
        assert os.path.realpath(r).startswith(os.path.realpath(str(root))), bad


def test_mirrored_instance_keeps_outward_winding():
    """A mirrored copy of a triangle must keep the same face direction (winding reversed)."""
    from skpballet.scene import Model, Definition
    from skpballet.mesh import IDENT

    def normal(buf):
        a, b, c = [buf[i:i + 3] for i in (0, 3, 6)]
        u = [b[i] - a[i] for i in range(3)]; v = [c[i] - a[i] for i in range(3)]
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    def build(matrix):
        m = Model(); r = Definition(1); sub = Definition(2)
        sub.vertices = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0)}
        sub.faces = [dict(id=1, loops=[[1, 2, 3]], mat=None, normal=(0, 0, 1))]
        r.instances = [dict(def_id=2, matrix=matrix, id=9)]
        m.root = r; m.defs = {2: sub}
        return flatten(m)[None][-9:]
    plain = normal(build(list(IDENT)))
    mirror = normal(build([-1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0]))   # x -> -x
    # the plain triangle faces +Z (source) = +Y_up; mirrored triangle still faces +Y_up
    assert plain[1] > 0 and mirror[1] > 0


def test_glb_material_colour_linear_alpha_and_default(tmp_path):
    from skpballet.scene import Model, Definition
    m = Model(); r = Definition(0); r.vertices = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0)}
    r.faces = [dict(id=i, loops=[[1, 2, 3]], mat=k, normal=(0, 0, 1)) for i, k in ((1, 7), (2, 8), (3, None), (4, 99))]
    m.root = r
    m.materials = {7: dict(name="red", rgb=(255, 0, 0), alpha=1.0), 8: dict(name="glass", rgb=(128, 128, 128), alpha=0.25)}
    p = tmp_path / "m.glb"; write_glb(m, str(p), edges=False)
    d = p.read_bytes(); j = json.loads(d[20:20 + struct.unpack_from("<I", d, 12)[0]])
    mats = {x["name"]: x for x in j["materials"]}
    assert mats["red"]["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 0.0, 0.0, 1.0]
    g = mats["glass"]; assert g["alphaMode"] == "BLEND" and g["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.25
    assert abs(g["pbrMetallicRoughness"]["baseColorFactor"][0] - 0.2158605) < 1e-5   # sRGB 128 -> linear
    assert "default" in mats and len(j["meshes"][0]["primitives"]) == 3   # None and unknown id share default look
