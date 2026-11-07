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
    assert sum(a["count"] for a in j["accessors"]) == n * 3


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
