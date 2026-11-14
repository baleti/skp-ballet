"""The tool must never modify, replace or remove its input .skp."""
import glob, hashlib, os, shutil
import pytest
from skpballet import cli

DATA = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(os.path.join(DATA, "*.skp")) + glob.glob(os.path.join(DATA, "legacy", "*.skp")))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_commands_leave_input_untouched(src, tmp_path, capsys):
    f = str(tmp_path / "in.skp")
    shutil.copy(src, f)
    os.chmod(f, 0o444)
    before = sha(f)
    st = os.stat(f)
    cli.main(["info", f])
    cli.main(["info", "--json", f])
    cli.main(["convert", f, str(tmp_path / "o.glb")])
    cli.main(["cache", f, str(tmp_path / "cache")])
    assert sha(f) == before
    assert os.stat(f).st_mtime_ns == st.st_mtime_ns
    assert sorted(os.listdir(tmp_path)) == ["cache", "in.skp", "o.glb"]


def test_refuses_output_over_input(tmp_path, capsys):
    f = str(tmp_path / "in.skp")
    shutil.copy(FILES[0], f)
    before = sha(f)
    link = str(tmp_path / "link.glb")
    os.symlink(f, link)
    assert cli.main(["convert", f, f]) == 2
    assert cli.main(["convert", f, link]) == 2
    assert cli.main(["convert", f, str(tmp_path / "x.SKP")]) == 2
    assert cli.main(["convert", f, str(tmp_path / "x.glb.skp")]) == 2
    assert not (tmp_path / "x.glb.skp").exists() and not (tmp_path / "x.SKP").exists()
    assert sha(f) == before


def test_source_has_no_input_write_modes():
    """Only output writers (cache.py, mesh.py) may open files for writing."""
    import re
    root = os.path.join(os.path.dirname(__file__), "..", "skpballet")
    bad = []
    for p in glob.glob(os.path.join(root, "*.py")):
        name = os.path.basename(p)
        txt = open(p, encoding="utf-8").read()
        if re.search(r"open\([^)]*[\"'](?:r\+|a|ab|rb\+|w\+)[\"']", txt):
            bad.append(name)
        if name not in ("cache.py", "mesh.py") and re.search(r"open\([^)]*[\"']w", txt):
            bad.append(name)
    assert not bad, bad


@pytest.mark.parametrize("kind", ["missing", "empty", "dir", "garbage"])
def test_bad_inputs_fail_cleanly(kind, tmp_path):
    p = tmp_path / "x.skp"
    if kind == "empty":
        p.write_bytes(b"")
    elif kind == "dir":
        p.mkdir()
    elif kind == "garbage":
        p.write_bytes(os.urandom(4096))
    rc = cli.main(["info", str(p)])
    assert rc in (1, 2)
    assert not p.is_file() or p.stat().st_size in (0, 4096)


def test_cli_damaged_inputs_exit_2_without_traceback(tmp_path):
    import glob, subprocess, sys
    data = os.path.join(os.path.dirname(__file__), "data")
    legacy = sorted(glob.glob(os.path.join(data, "legacy", "*.skp")))[0]
    nest = os.path.join(data, "nesting_2021.skp")
    cases = {"empty": b"", "text": b"hello\n", "trunc30": open(nest, "rb").read()[:30],
             "trunc1500": open(nest, "rb").read()[:1500], "legacy3000": open(legacy, "rb").read()[:3000]}
    root = os.path.dirname(os.path.dirname(__file__))
    for name, blob in cases.items():
        p = tmp_path / (name + ".skp")
        p.write_bytes(blob)
        for args in (["info", str(p)], ["info", str(p), "--json"], ["convert", str(p), str(tmp_path / (name + ".glb"))],
                     ["cache", str(p), str(tmp_path / ("c_" + name))]):
            r = subprocess.run([sys.executable, "-m", "skpballet"] + args, cwd=root, capture_output=True, text=True, timeout=30)
            assert r.returncode in ((0, 2) if name.startswith("legacy") else (2,)) and "Traceback" not in r.stderr, (name, args, r.returncode, r.stderr[-300:])
    r = subprocess.run([sys.executable, "-m", "skpballet", "info", str(tmp_path / "missing.skp")], cwd=root, capture_output=True, text=True)
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_cli_strict_exits_3_on_truncated_legacy_and_default_command_does_not_traceback(tmp_path):
    import glob, subprocess, sys
    data = os.path.join(os.path.dirname(__file__), "data", "legacy")
    root = os.path.dirname(os.path.dirname(__file__))
    flagged = 0
    for f in sorted(glob.glob(os.path.join(data, "*.skp")))[:6]:
        blob = open(f, "rb").read()
        p = tmp_path / "cut.skp"
        p.write_bytes(blob[:len(blob) // 2])
        r = subprocess.run([sys.executable, "-m", "skpballet", "info", str(p), "--strict"], cwd=root, capture_output=True, text=True, timeout=60)
        assert "Traceback" not in r.stderr and r.returncode in (2, 3), (f, r.returncode, r.stderr[-200:])
        flagged += r.returncode in (2, 3)
        # default command (info + viewer) must also fail cleanly; viewer is never started on a rejected file
        if r.returncode == 2:
            r2 = subprocess.run([sys.executable, "-m", "skpballet", str(p)], cwd=root, capture_output=True, text=True, timeout=60)
            assert r2.returncode == 2 and "Traceback" not in r2.stderr
    assert flagged == len(sorted(glob.glob(os.path.join(data, "*.skp")))[:6]) > 0


def test_legacy_image_file_uses_root_list_not_image_definition():
    """image.skp: root face 10x10 in; the Image0 definition (48x36 in face) is written first. openskp agrees (cross-check)."""
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(os.path.dirname(__file__), "data", "legacy", "image.skp")))
    xs = sorted(p[0] for p in m.root.vertices.values())
    assert xs == [0.0, 0.0, 10.0, 10.0], m.root.vertices
    assert any("LAST entity list" in w for w in m.warnings), m.warnings


def test_legacy_multiple_lists_with_rejected_tree_warns(monkeypatch):
    from skpballet import container, legacy, scene
    f = os.path.join(os.path.dirname(__file__), "data", "legacy", "components.skp")
    assert not any("definition tree was rejected" in w for w in scene.load(container.open_skp(f)).warnings)
    monkeypatch.setattr(legacy, "legacy_tree", lambda *a, **k: None)
    m = scene.load(container.open_skp(f))
    assert any("definition tree was rejected" in w and "NOT read" in w for w in m.warnings), m.warnings


def test_legacy_untested_versions_6_to_16_warn(monkeypatch, capsys):
    from skpballet import container, legacy, scene
    f = os.path.join(os.path.dirname(__file__), "data", "legacy", "components.skp")
    assert not any("UNTESTED" in w for w in scene.load(container.open_skp(f)).warnings)
    real = container.open_skp(f)
    for major, expect in ((5, False), (6, True), (9, True), (12, True), (13, False), (14, True), (16, True), (17, False)):
        real.version = "%d.0.1" % major
        assert any("UNTESTED" in w for w in legacy.load_legacy(real).warnings) == expect, major


def test_strict_failure_writes_nothing_and_leaves_existing_output(tmp_path):
    from skpballet import cli
    raw = open(os.path.join(os.path.dirname(__file__), "data", "legacy", "components.skp"), "rb").read(); n = len(raw)
    bad = tmp_path / "bad.skp"; bad.write_bytes(raw[:n // 2] + bytes(n - n // 2))   # zero-filled half: damaged data
    pre = tmp_path / "pre.glb"; pre.write_bytes(b"keep")
    assert cli.main(["convert", "--strict", str(bad), str(pre)]) == 3
    assert pre.read_bytes() == b"keep"
    assert cli.main(["convert", "--strict", str(bad), str(tmp_path / "new.glb")]) == 3
    assert not (tmp_path / "new.glb").exists()
    cd = tmp_path / "cache"; cd.mkdir(); (cd / "model.glb").write_bytes(b"keep")
    assert cli.main(["cache", "--strict", str(bad), str(cd)]) == 3
    assert (cd / "model.glb").read_bytes() == b"keep" and os.listdir(cd) == ["model.glb"]


def test_outputs_carry_the_warnings(tmp_path):
    import json, struct
    raw = open(os.path.join(os.path.dirname(__file__), "data", "legacy", "components.skp"), "rb").read(); n = len(raw)
    bad = tmp_path / "bad.skp"; bad.write_bytes(raw[:n // 2] + bytes(n - n // 2))
    assert cli.main(["convert", str(bad), str(tmp_path / "o.glb")]) == 0
    d = (tmp_path / "o.glb").read_bytes(); ln = struct.unpack("<I", d[12:16])[0]
    w = json.loads(d[20:20 + ln])["asset"]["extras"]["warnings"]
    assert any("damaged data" in x for x in w)
    assert cli.main(["cache", str(bad), str(tmp_path / "c")]) == 0
    assert any("damaged data" in x for x in json.load(open(tmp_path / "c" / "meta.json"))["warnings"])
    good = os.path.join(os.path.dirname(__file__), "data", "arcs_2021.skp")
    assert cli.main(["cache", good, str(tmp_path / "g")]) == 0
    assert json.load(open(tmp_path / "g" / "meta.json"))["warnings"] == []


def test_legacy_plane_misfit_is_warned(tmp_path):
    import glob, os, struct
    from skpballet.container import open_skp
    from skpballet.scene import load as load_model
    src = os.path.join(os.path.dirname(__file__), "data", "legacy", "uv_positioning.skp")
    raw = open(src, "rb").read()
    def warns(b):
        p = tmp_path / "x.skp"; p.write_bytes(b)
        return [w for w in load_model(open_skp(str(p))).warnings if "stored plane" in w]
    assert warns(raw) == []
    pat = struct.pack("<4d", 0.0, 0.0, 1.0, -5.0)
    assert pat in raw
    bad = raw.replace(pat, struct.pack("<4d", 0.0, 0.0, 1.0, -6.0), 1)
    assert warns(bad) and "damaged data" in warns(bad)[0]
    # normal flipped to disagree with the loop
    flipped = raw.replace(pat, struct.pack("<4d", 0.0, 0.0, -1.0, 5.0), 1)
    assert warns(flipped)


@pytest.mark.parametrize("rgb,alpha", [((300, 0, 0), 1.0), ((-5, 0, 0), 1.0), ((255, 0, 0), -0.5), ((255, 0, 0), float("nan")),
                                      ((255, 0, 0), 3.0), ((float("nan"), 0, 0), 1.0)])
def test_out_of_range_material_values_never_reach_glb_or_cache(rgb, alpha, tmp_path):
    import json, math, struct
    from skpballet import mesh, cache, scene
    m = scene.Model(); d = scene.Definition(-1, "root"); m.root = d
    d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=1, normal=(0, 0, 1))]
    m.materials[1] = dict(name="x", rgb=rgb, alpha=alpha)
    def factors(path):
        raw = open(path, "rb").read(); jl = struct.unpack("<I", raw[12:16])[0]
        j = json.loads(raw[20:20 + jl], parse_constant=lambda c: pytest.fail("non-finite JSON constant " + c))
        return [x for mt in j["materials"] for x in mt["pbrMetallicRoughness"]["baseColorFactor"]]
    mesh.write_glb(m, str(tmp_path / "a.glb"))
    cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    for path in (tmp_path / "a.glb", tmp_path / "c" / "model.glb"):
        assert all(0.0 <= x <= 1.0 and not math.isnan(x) for x in factors(str(path))), path
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())
    for b in meta["batches"]:
        assert 0.0 <= b["alpha"] <= 1.0 and len(b["color"]) == 7 and b["color"].startswith("#"), b
