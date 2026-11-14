import glob, os, random, sys
import pytest
from skpballet import container, scene
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import model_diff  # noqa: E402

D = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(os.path.join(D, "*.skp")) + glob.glob(os.path.join(D, "legacy", "*.skp")))


@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_file_is_identical_to_itself(path):
    a = scene.load(container.open_skp(path))
    b = scene.load(container.open_skp(path))
    assert model_diff.diff(a, b)[0] == {}


def test_coordinate_change_is_seen():
    p = os.path.join(D, "nesting_2021.skp")
    a = scene.load(container.open_skp(p))
    b = scene.load(container.open_skp(p))
    d = b.root if b.root.vertices else next(x for x in b.defs.values() if x.vertices)
    k = sorted(d.vertices)[0]
    x, y, z = d.vertices[k]
    d.vertices[k] = (x + 1e-6, y, z)
    sec = model_diff.diff(a, b)[0]
    assert sec.get("vertex") == [1, 1]


def test_cli_exit_codes(tmp_path, capsys):
    p = os.path.join(D, "nesting_2021.skp")
    assert model_diff.main([p, p]) == 0
    assert model_diff.main([p, os.path.join(D, "arcs_2021.skp")]) == 1
    bad = tmp_path / "bad.skp"
    bad.write_bytes(b"junk")
    assert model_diff.main([p, str(bad)]) == 2


def test_canon_tolerates_damaged_models_with_none_ids():
    p = os.path.join(D, "nesting_2021.skp")
    a = scene.load(container.open_skp(p))
    b = scene.load(container.open_skp(p))
    d = next(x for x in [b.root] + list(b.defs.values()) if x.vertices and x.edges)
    d.edges[None] = (0, 1)
    d.vertices[None] = (0.0, 0.0, 0.0)
    assert model_diff.diff(a, b)[0].get("edge") == [0, 1]


def test_regress_diff_detects_the_image_change_and_is_quiet_for_head():
    import subprocess
    root = os.path.dirname(os.path.dirname(__file__))
    out = subprocess.run(["git", "log", "--format=%H", "--grep=parse CImage"], cwd=root, capture_output=True, text=True).stdout.split()
    if not out:
        pytest.skip("CImage commit not in history")
    sub = os.path.join(root, "tests", "data", "legacy", "image.skp")
    r = subprocess.run([sys.executable, os.path.join(root, "tools", "regress_diff.py"), out[0] + "~1", sub], capture_output=True, text=True)
    r2 = subprocess.run([sys.executable, os.path.join(root, "tools", "regress_diff.py"), "HEAD", sub], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert r.returncode == 1 and "changed: image.skp" in r.stdout, r.stdout + r.stderr
