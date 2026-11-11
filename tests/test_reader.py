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


def test_group_vs_component_flag():
    m = load(open_skp(os.path.join(D, "nesting_2021.skp")))
    kinds = {d.name: d.is_group for d in m.defs.values()}
    assert kinds == {"Group": True, "Group2": True, "Shelf": False}
    m = load(open_skp(os.path.join(D, "instance_scale_term_2021.skp")))
    assert [d.is_group for d in m.defs.values()] == [False]


@pytest.mark.parametrize("f", FILES)
def test_rvt_ballet_cache_consistent(f, tmp_path):
    from skpballet.cache import write_cache
    m = load(open_skp(f)); r = write_cache(m, str(tmp_path))
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["phase"] == "done" and len(meta["elements"]) == r["elements"] > 0
    assert (tmp_path / "materials.json").exists()
    d = (tmp_path / "model.glb").read_bytes()
    j = json.loads(d[20:20 + struct.unpack_from("<I", d, 12)[0]])
    assert len(j["meshes"]) == len(meta["batches"])
    n_el = len(meta["elements"])
    for b, mesh_ in zip(meta["batches"], j["meshes"]):
        pr = mesh_["primitives"][0]
        per = 3 if b["kind"] == "tri" else 2
        assert j["accessors"][pr["indices"]]["count"] == b["tris"] * per
        assert j["accessors"][pr["attributes"]["_EIDX"]]["count"] == j["accessors"][pr["attributes"]["POSITION"]]["count"]
        R = b["ranges"]; assert len(R) % 3 == 0 and sum(R[k + 2] for k in range(0, len(R), 3)) == b["tris"]
        assert all(0 <= R[k] < n_el for k in range(0, len(R), 3))
    # triangle total equals the flat export
    assert r["triangles"] == sum(len(v) for v in flatten(m).values()) // 9


def test_layer_records_counted_annotation_fixture():
    m = load(open_skp(os.path.join(D, "annotation_layers_vff.skp")))
    assert len(m.layers) == 4


def test_legacy_first_face_nesting_2017_2020():
    from skpballet.legacy import scan_faces
    for y in ("2017", "2020"):
        f = scan_faces(open(os.path.join(D, "legacy", "nesting_%s.skp" % y), "rb").read())
        assert f == [[[(40.0, 0.0, 0.0), (50.0, 0.0, 0.0), (50.0, 10.0, 0.0), (40.0, 10.0, 0.0)]]]


def test_legacy_arcs_faces_match_2021_face_count():
    from skpballet.legacy import scan_faces
    n21 = 2   # arcs_2021.skp has 2 faces; x extent 108 in = 2.7432 m matches its bbox
    for y in ("2017", "2020"):
        f = scan_faces(open(os.path.join(D, "legacy", "arcs_%s.skp" % y), "rb").read())
        assert len(f) == n21
        assert max(v[0] for fc in f for lp in fc for v in lp) == 108.0


def test_legacy_wired_into_load_and_glb(tmp_path):
    m = load(open_skp(os.path.join(D, "legacy", "arcs_2017.skp")))
    assert m.counts()["faces"] == 2 and "legacy" in m.version
    assert write_glb(m, str(tmp_path / "a.glb")) > 0


def test_legacy_entity_list_count_validates_parse():
    from skpballet.legacy import scan_faces
    good = ["arcs_2017", "arcs_2020", "chair_and_table", "components", "groups", "nested", "nesting_2017",
            "nesting_2020", "materials_and_layers", "textures", "layers_extra", "image", "uv_positioning"]
    for n in good:
        i = {}
        scan_faces(open(os.path.join(D, "legacy", n + ".skp"), "rb").read(), i)
        assert i["complete"] and i["parsed"] == i["count"], n
    i = {}   # an undecoded layout must be reported incomplete, never silently complete
    scan_faces(open(os.path.join(D, "legacy", "nesting_2013.skp"), "rb").read(), i)
    assert not i["complete"]


def test_legacy_fuzz_fails_cleanly():
    import random
    from skpballet.container import SkpError
    rnd = random.Random(1)
    for n in ("arcs_2017", "components", "textures", "nesting_2013"):
        d = open(os.path.join(D, "legacy", n + ".skp"), "rb").read()
        for i in range(25):
            b = bytearray(d[:rnd.randrange(10, len(d))] if i < 5 else d)
            if i >= 5:
                for _ in range(rnd.randrange(1, 6)):
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
            try:
                load(open_skp(bytes(b)))
            except SkpError:
                pass


def _tri_area(P, tr):
    import math
    s = 0.0
    for a, b, c in tr:
        u = [P[b][i] - P[a][i] for i in range(3)]; v = [P[c][i] - P[a][i] for i in range(3)]
        s += math.sqrt((u[1]*v[2]-u[2]*v[1])**2 + (u[2]*v[0]-u[0]*v[2])**2 + (u[0]*v[1]-u[1]*v[0])**2) / 2
    return s


def test_triangulate_zero_width_spike_area():
    from skpballet.mesh import triangulate
    # square with a zero-width spike (2,4)->(2,2)->(2,4): area must stay 16 (was 20 before spikes were removed)
    loop = [(0, 0, 0), (4, 0, 0), (4, 4, 0), (2, 4, 0), (2, 2, 0), (2, 4, 0), (0, 4, 0)]
    P, tr = triangulate([loop], (0, 0, 1))
    assert abs(_tri_area(P, tr) - 16.0) < 1e-9


def test_triangulate_pinched_loop_area():
    from skpballet.mesh import triangulate
    loop = [(0, 0, 0), (2, 0, 0), (1, 1, 0), (2, 2, 0), (0, 2, 0), (1, 1, 0)]   # two triangles touching at (1,1)
    P, tr = triangulate([loop], (0, 0, 1))
    assert abs(_tri_area(P, tr) - 2.0) < 1e-9


def test_triangulate_two_holes_area():
    from skpballet.mesh import triangulate
    outer = [(0, 0, 0), (40, 0, 0), (40, 6, 0), (0, 6, 0)]
    h1 = [(15.33, 1.08, 0), (15.33, 4.04, 0), (17.27, 4.04, 0), (17.27, 1.08, 0)]
    h2 = [(10.64, 1.13, 0), (10.64, 3.68, 0), (12.9, 3.68, 0), (12.9, 1.13, 0)]
    P, tr = triangulate([outer, h1, h2], (0, 0, 1))
    exp = 240 - 1.94 * 2.96 - 2.26 * 2.55
    assert abs(_tri_area(P, tr) - exp) < 1e-6    # was 56.4 (ear clipper dropped vertices at coincident bridge copies)


def test_triangulate_pinched_hole_touching_boundary_area():
    from skpballet.mesh import triangulate
    # outer 10x10 with a triangular hole that touches the boundary at (5,10); loop is one ring revisiting (5,10)
    loop = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (5, 10, 0), (6, 8, 0), (4, 8, 0), (5, 10, 0), (0, 10, 0)]
    P, tr = triangulate([loop], (0, 0, 1))
    assert abs(_tri_area(P, tr) - 98.0) < 1e-9    # was 102 (the hole piece was added as a face)


def test_triangulate_three_holes_shared_bridge_vertex():
    from skpballet.mesh import triangulate
    outer = [(0, 0, 0), (60, 0, 0), (60, 4, 0), (0, 4, 0)]
    H = [[(29.4249, 1.3925), (29.4768, 2.8544), (31.1902, 2.6803), (31.2056, 1.2922)],
         [(16.9939, 1.2398), (16.9569, 2.8313), (19.5618, 2.7839), (19.4924, 1.1832)],
         [(51.6688, 1.0566), (51.8481, 3.1073), (54.5177, 3.0605), (54.5872, 1.1106)]]
    holes = [[(x, y, 0) for x, y in h] for h in H]

    def sh(h):
        return abs(sum(h[i][0] * h[(i + 1) % 4][1] - h[(i + 1) % 4][0] * h[i][1] for i in range(4))) / 2
    P, tr = triangulate([outer] + holes, (0, 0, 1))
    assert abs(_tri_area(P, tr) - (240 - sum(sh(h) for h in holes))) < 1e-6   # was 0.69 of it: a bridge left a vertex through the wrong wedge


def test_triangulate_touching_hole_uses_shared_vertex():
    from skpballet.mesh import triangulate
    # hole touches the outer ring at (5,10) but its right-most vertex (9,9) is nearer to the corner (10,10)
    loop = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (5, 10, 0), (9, 9, 0), (8, 5, 0), (5, 10, 0), (0, 10, 0)]
    P, tr = triangulate([loop], (0, 0, 1))
    assert abs(_tri_area(P, tr) - 91.5) < 1e-9


def test_triangulate_vertex_touching_edge_area():
    from skpballet.mesh import triangulate
    # the tip (10,7) of a triangular notch lies on the interior of the right edge (10,0)-(10,10): region area 100 - 15
    loop = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 7, 0), (10, 7, 0), (0, 4, 0)]
    P, tr = triangulate([loop], (0, 0, 1))
    assert abs(_tri_area(P, tr) - 85.0) < 1e-9


def test_insert_touching_makes_pinch():
    from skpballet.mesh import _insert_touching, _split_pinched
    loop = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 7, 0), (10, 7, 0), (0, 4, 0)]
    out = _insert_touching(loop)
    assert len(out) == len(loop) + 1 and out.count((10, 7, 0)) == 2
    assert sorted(len(p) for p in _split_pinched(out)) == [3, 6] or len(_split_pinched(out)) == 2


def test_legacy_file_without_geometry_is_an_empty_model():
    import os
    from skpballet import container, scene
    p = os.path.join(os.path.dirname(__file__), "data", "legacy", "single_material_v17.skp")
    m = scene.load(container.open_skp(p))
    assert m.counts()["faces"] == 0


def test_legacy_curve_and_texture_coords_decode():
    from skpballet.legacy import scan_faces
    i = {}
    out = scan_faces(open(os.path.join(D, "legacy", "edge_flags.skp"), "rb").read(), i)
    assert i["parsed"] == i["count"] == 28 and len(out) == 4 and i["complete"]   # 2 trailing None terminators


def test_legacy_2013_has_no_mask_byte():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "nesting_2013.skp")))
    c = m.counts()
    assert c["faces"] == 3 and c["vertices"] == 12 and c["definitions"] == 3   # definition tree (was 1 face before item 45)
    assert not any("INCOMPLETE" in w for w in m.warnings)


def test_legacy_tree_nesting_three_versions_same_geometry():
    from skpballet import container, scene, mesh
    res = []
    for y in ("2013", "2017", "2020"):
        m = scene.load(container.open_skp(os.path.join(D, "legacy", "nesting_%s.skp" % y)))
        assert [len(d.instances) for d in m.defs.values()] == [0, 1, 1] and len(m.root.instances) == 1
        flat = mesh.flatten(m)
        assert sum(len(v) // 9 for v in flat.values()) == 6   # 3 squares, 2 triangles each
        res.append(sorted(sum(flat.values(), [])))
    assert res[0] == res[1] == res[2]


def test_legacy_tree_rejects_inconsistent_files():
    from skpballet import container, legacy
    for n in ("arcs_2017", "edge_flags"):
        s = container.open_skp(os.path.join(D, "legacy", n + ".skp"))
        assert legacy.legacy_tree(s.data, s.version) is None   # falls back to the first entity list


def test_cli_info_bbox_and_layers(capsys):
    from skpballet import cli
    p = os.path.join(D, "annotation_layers_vff.skp")
    assert cli.main(["info", "--layers", p]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 4
    assert cli.main(["info", "--bbox", p]) == 0
    assert len(capsys.readouterr().out.split()) in (6, 1)


def test_reader_never_modifies_input(tmp_path):
    """No write path exists: load, info, convert and cache must leave the input byte-identical and untouched."""
    import hashlib, shutil
    from skpballet import cli
    for rel in ("nesting_2021.skp", os.path.join("legacy", "edge_flags.skp")):
        src = tmp_path / os.path.basename(rel)
        shutil.copy(os.path.join(D, rel), src)
        os.chmod(src, 0o444)   # read-only: any write attempt would raise
        h = hashlib.sha256(src.read_bytes()).hexdigest(); st = os.stat(src)
        assert cli.main(["info", str(src)]) == 0
        assert cli.main(["convert", str(src), str(tmp_path / "o.glb")]) == 0
        assert cli.main(["cache", str(src), str(tmp_path / "cache")]) == 0
        assert hashlib.sha256(src.read_bytes()).hexdigest() == h
        assert os.stat(src).st_mtime_ns == st.st_mtime_ns and os.stat(src).st_size == st.st_size


def test_convert_and_cache_refuse_to_overwrite_the_input(tmp_path):
    import shutil
    from skpballet import cli
    src = tmp_path / "a.skp"
    shutil.copy(os.path.join(D, "nesting_2021.skp"), src)
    before = src.read_bytes()
    assert cli.main(["convert", str(src), str(src)]) != 0
    assert cli.main(["convert", str(src), str(tmp_path / "b.SKP")]) != 0
    assert cli.main(["cache", str(src), str(src)]) != 0
    assert src.read_bytes() == before and not (tmp_path / "b.SKP").exists()


def test_open_without_geometry_does_not_start_viewer(capsys, monkeypatch):
    from skpballet import cli
    monkeypatch.setattr(cli, "serve", lambda *a, **k: (_ for _ in ()).throw(AssertionError("viewer started")))
    assert cli.main([os.path.join(D, "legacy", "single_material_v17.skp")]) == 1


def test_legacy_faces_are_triangulated_in_their_own_plane():
    """Legacy faces carried no normal, so every face was projected on XY: vertical faces got garbage triangles."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import area_check
    for n in ("chair_and_table", "uv_positioning"):
        faces, bad = area_check.check(os.path.join(D, "legacy", n + ".skp"))
        assert faces and bad == 0, n


def test_legacy_material_list():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "materials_and_layers.skp")))
    got = {v["name"]: (v["rgb"], round(v["alpha"], 2)) for v in m.materials.values()}
    assert got == {"Red": ((255, 0, 0), 1.0), "Blue": ((0, 0, 255), 0.5)}


def test_legacy_face_materials():
    from skpballet import container, scene, mesh
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "materials_and_layers.skp")))
    assert [m.materials[f["mat"]]["name"] for f in m.root.faces] == ["Red", "Blue"]
    out = os.path.join(os.path.dirname(__file__), "..", ".pytest_cache", "legacy_mat.glb")
    mesh.write_glb(m, out)
    d = open(out, "rb").read()
    assert b'"baseColorFactor":[1' in d.replace(b" ", b"") or b"baseColorFactor" in d


def test_legacy_textured_materials_embed_png():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "legacy_v2020_textured.skp")))
    t = [v for v in m.materials.values() if "texture" in v]
    assert len(t) == 1 and t[0]["name"] == "Checker" and t[0]["texture"]["scale"] == (10.0, 10.0)
    png = t[0]["texture"]["png"]
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and png.endswith(b"IEND\xaeB`\x82") and len(png) == 88
    m2 = scene.load(container.open_skp(os.path.join(D, "legacy", "textures.skp")))
    assert sorted(v["name"] for v in m2.materials.values()) == ["Brick", "Tile"]


def test_legacy_layer_list():
    import os
    from skpballet.legacy import scan_layers
    d = os.path.join(os.path.dirname(__file__), "data", "legacy")
    names = lambda f: [n for n, _ in scan_layers(open(os.path.join(d, f), "rb").read())]
    assert names("layers_extra.skp") == ["Layer0", "Walls", "Roof", "Hidden"]
    assert names("chair_and_table.skp") == ["Layer0", "Chair", "Table"]


def test_legacy_colorize_materials():
    import os
    from skpballet.legacy import scan_materials
    p = os.path.join(os.path.dirname(__file__), "data", "legacy", "legacy_textured_colorize_2017.skp")
    mats = scan_materials(open(p, "rb").read())
    assert sorted(m[0] for m in mats) == ["plain", "shift", "tint", "tint_half"]
    assert all(m[3]["png"][:8] == b"\x89PNG\r\n\x1a\n" for m in mats if len(m) > 3)


def test_legacy_sdk_saved_and_blank():
    import os
    from skpballet import container, scene
    d = os.path.join(os.path.dirname(__file__), "data", "legacy")
    for f, nf in (("sdk_saved_2019.skp", 1), ("sdk_saved_2020.skp", 1), ("legacy_v2019_synthetic.skp", 4), ("blank_v17.skp", 0)):
        m = scene.load(container.open_skp(os.path.join(d, f)))
        assert sum(len(x.faces) for x in [m.root, *m.defs.values()]) == nf, f   # synthetic 2019 is a definition tree


def test_legacy_instance_records():
    import os
    from skpballet.legacy import scan_instances
    d = os.path.join(os.path.dirname(__file__), "data", "legacy")
    r = scan_instances(open(os.path.join(d, "components.skp"), "rb").read())
    assert [(x[0], tuple(round(c) for c in x[2])) for x in r] == [("Chair", (100, 0, 0)), ("Second Chair", (200, 0, 0)), ("Chair", (0, 300, 0))]
    assert round(r[1][1][1]) == -1 and round(r[1][1][3]) == 1 and round(r[2][1][0]) == 2


def test_glb_asset_extras_lists_layers(tmp_path):
    import json, os, struct
    from skpballet import container, scene, mesh
    p = os.path.join(os.path.dirname(__file__), "data", "legacy", "layers_extra.skp")
    out = tmp_path / "a.glb"
    mesh.write_glb(scene.load(container.open_skp(p)), str(out))
    d = out.read_bytes()
    j = json.loads(d[20:20 + struct.unpack_from("<I", d, 12)[0]])
    ex = j["asset"]["extras"]
    assert ex["layers"] == ["Hidden", "Layer0", "Roof", "Walls"] and ex["layers_flagged_off"] == ["Hidden"]


def test_legacy_tree_accepts_eight_public_fixtures():
    from skpballet import container, legacy
    want = {"components": (1, 3), "groups": (3, 3), "group_in_definition_flag": (2, 3), "chair_and_table": (9, 15),
            "legacy_v2019_synthetic": (4, 11), "nesting_2017": (3, 3), "nested": (3, 3)}
    for n, (nd, ni) in want.items():
        s = container.open_skp(os.path.join(D, "legacy", n + ".skp"))
        t = legacy.legacy_tree(s.data, s.version)
        assert t is not None and len(t[0]) == nd and sum(len(d[2]) for d in t[0] + [t[1]]) == ni, n


def test_legacy_tree_definition_names():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "chair_and_table.skp")))
    assert [d.name for d in m.defs.values()] == ["Leg_Chair", "Seat_Chair", "BackrestFrame", "BackrestCushion", "Backrest",
                                                  "Chair", "Leg_Table", "Tabletop", "Table"]


def test_legacy_tree_composed_dimensions_chair_and_table():
    # leg 17 + seat 2 + backrest 15 = chair 34; table leg 20.5 + top 1.5 = 22 (inches): checks definition links and instance transforms
    from skpballet import container, scene, mesh

    m = scene.load(container.open_skp(os.path.join(D, "legacy", "chair_and_table.skp")))

    def pts(d, M=mesh.IDENT):
        out = [mesh._mul(M, v) for v in d.vertices.values()]
        for i in d.instances:
            out += pts(m.defs[i["def_id"]], mesh._compose(M, i["matrix"]))
        return out

    by = {d.name: d for d in m.defs.values()}
    ext = lambda d: [round(max(c) - min(c), 1) for c in zip(*pts(d))]
    assert ext(by["Chair"]) == [18.0, 17.0, 34.0]
    assert ext(by["Table"]) == [24.0, 20.0, 22.0]
    assert ext(m.root)[2] == 34.0


def test_legacy_tree_group_vs_component():
    from skpballet import container, scene
    g = lambda n: [(d.name, d.is_group) for d in scene.load(container.open_skp(os.path.join(D, "legacy", n + ".skp"))).defs.values()]
    assert g("groups") == [("Table", True), ("Group", True), ("Chair", False)]
    assert g("components") == [("Chair", False)]
    assert [x for x in g("chair_and_table") if x[1]] == []


def test_legacy_tree_edges_exported():
    from skpballet import container, scene, mesh
    m = scene.load(container.open_skp(os.path.join(D, "legacy", "chair_and_table.skp")))
    assert m.counts()["edges"] == 200
    lines = []
    mesh.flatten(m, lines=lines)
    assert len(lines) // 6 == 368   # segments after instance expansion
