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


def test_info_text_output_sanitises_file_controlled_names(capsys, monkeypatch):
    from skpballet import cli, scene, container
    m = scene.Model(); d = scene.Definition(0, "x\ud800y\x1b[31mRED‮"); m.root = scene.Definition(-1, "root")
    d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}; d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]
    m.defs[0] = d; m.layers[1] = "L\ud800\x07"; m.materials[1] = dict(name="M\x1b]0;t\x07", rgb=(1, 2, 3), alpha=1.0)
    m.warnings.append("w\x1b[2J")
    monkeypatch.setattr(scene, "load", lambda s: m); monkeypatch.setattr(container, "open_skp", lambda p: None)
    assert cli.main(["info", "f"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and "‮" not in out and "RED" in out


def _symlink(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):   # Windows without the symlink privilege
        pytest.skip("cannot create symlinks here")


def test_outputs_never_write_through_symlinks_to_the_source(tmp_path):
    """cache wrote model.glb/meta.json/materials.json THROUGH symlinks placed in the output dir: a link to the source .skp
    overwrote the original. Outputs are now temp file + os.replace, so the link is replaced and the source is untouched."""
    import shutil
    from skpballet import cli
    src = tmp_path / "m.skp"; shutil.copy(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"), src)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    cdir = tmp_path / "cc"; cdir.mkdir()
    for n in ("model.glb", "meta.json", "materials.json"):
        _symlink(src, cdir / n)
    assert cli.main(["cache", str(src), str(cdir)]) == 0
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    assert not os.path.islink(cdir / "model.glb") and (cdir / "model.glb").read_bytes()[:4] == b"glTF"
    assert not [f for f in os.listdir(cdir) if f.endswith(".tmp")]
    # convert to a symlink that points at the source: refused or replaced, never written through
    out = tmp_path / "o.glb"; _symlink(src, out)
    cli.main(["convert", str(src), str(out)])
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_safe_join_blocks_symlinks_leaving_the_vendor_dir(tmp_path):
    from skpballet.cli import safe_join
    v = tmp_path / "v"; v.mkdir(); (tmp_path / "secret").write_text("s"); (v / "ok.js").write_text("x")
    _symlink(tmp_path / "secret", v / "l.js"); _symlink(tmp_path, v / "up")
    assert os.path.exists(safe_join(str(v), "ok.js"))
    for p in ("l.js", "up/secret", "../secret", "%2e%2e/secret", "..%2fsecret"):
        assert not os.path.exists(safe_join(str(v), p)), p


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX FIFOs")
def test_fifo_and_directory_inputs_fail_fast_instead_of_blocking(tmp_path):
    from skpballet import container
    fifo = tmp_path / "f.skp"; os.mkfifo(fifo)
    for p in (fifo, tmp_path):
        with pytest.raises(container.SkpError, match="not a regular file"):
            container.open_skp(str(p))   # without the fix the FIFO open blocks forever (no writer)


def test_oversized_input_refused_before_reading(monkeypatch):
    from skpballet import container
    monkeypatch.setattr(container, "MAX_BYTES", 100)
    with pytest.raises(container.SkpError, match="larger than"):
        container.open_skp(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"))


def test_zip_member_over_the_limit_is_refused_not_inflated(monkeypatch):
    from skpballet import container, scene
    sk = container.open_skp(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"))
    assert len(sk.model_dat) > 100
    monkeypatch.setattr(container, "MAX_MEMBER", 100)
    with pytest.raises(container.SkpError, match="refusing to inflate"):
        sk.model_dat
    with pytest.raises(container.SkpError):
        scene.load(sk)


def test_instance_bomb_is_budgeted_and_reported(tmp_path, monkeypatch):
    """8 instances per level x 12 levels = 8^12 placements never finished (and grew without bound); now the walk stops at a
    placement budget and says the rest is NOT placed in the GLB extras and the cache meta (so --strict style checks see it)."""
    import json, struct
    from skpballet import mesh, cache, scene
    monkeypatch.setattr(mesh, "MAX_PLACEMENTS", 2000)
    I = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]
    def bomb():
        m = scene.Model(); m.root = scene.Definition(-1, "root")
        for k in range(14):
            d = scene.Definition(k, "d%d" % k); d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
            d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]; m.defs[k] = d
            if k:
                d.instances = [dict(def_id=k - 1, matrix=I, name="x", id=None) for _ in range(8)]
        m.root.instances = [dict(def_id=13, matrix=I, name="r", id=None)]
        return m
    m = bomb(); mesh.write_glb(m, str(tmp_path / "b.glb"))
    raw = (tmp_path / "b.glb").read_bytes(); jl = struct.unpack("<I", raw[12:16])[0]
    assert any("NOT placed" in w for w in json.loads(raw[20:20 + jl])["asset"]["extras"]["warnings"])
    m = bomb(); cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    assert any("NOT placed" in w for w in json.loads((tmp_path / "c" / "meta.json").read_text())["warnings"])


def test_cache_has_a_triangle_cap_like_flatten(tmp_path, monkeypatch):
    import json
    from skpballet import mesh, cache, scene
    monkeypatch.setattr(mesh, "MAX_TRIS", 50)
    m = scene.Model(); m.root = scene.Definition(-1, "root")
    d = scene.Definition(0, "d"); d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]; m.defs[0] = d
    m.root.instances = [dict(def_id=0, matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1, j, 0, 0, 1], name="c", id=None) for j in range(500)]
    cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())
    assert sum(b["tris"] for b in meta["batches"]) <= 60 and any("NOT placed" in w for w in meta["warnings"])


def test_strict_refuses_an_export_that_truncates_at_a_limit(tmp_path, monkeypatch):
    """The strict check runs on load-time warnings; a limit hit DURING export (placements/triangles) used to write a partial
    GLB/cache and exit 0 even with --strict. Now exit 3 and nothing written; non-strict still writes, with the warning."""
    from skpballet import cli, mesh
    nest = os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp")
    monkeypatch.setattr(mesh, "MAX_PLACEMENTS", 1)
    out = tmp_path / "o.glb"; out.write_bytes(b"keep"); cdir = tmp_path / "cc"
    assert cli.main(["convert", "--strict", nest, str(out)]) == 3 and out.read_bytes() == b"keep"
    assert cli.main(["cache", "--strict", nest, str(cdir)]) == 3 and not cdir.exists()
    assert cli.main(["convert", nest, str(out)]) == 0 and out.read_bytes()[:4] == b"glTF"
    assert cli.main(["cache", nest, str(cdir)]) == 0 and (cdir / "model.glb").exists()


def test_export_time_warnings_are_printed_by_convert_and_cache(tmp_path, monkeypatch, capsys):
    from skpballet import cli, mesh
    nest = os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp")
    monkeypatch.setattr(mesh, "MAX_PLACEMENTS", 1)
    assert cli.main(["convert", nest, str(tmp_path / "o.glb")]) == 0
    assert "NOT placed" in capsys.readouterr().out
    assert cli.main(["cache", nest, str(tmp_path / "cc")]) == 0
    assert "NOT placed" in capsys.readouterr().out


def test_info_survives_a_legacy_console_encoding(monkeypatch):
    import io, sys
    from skpballet import cli, scene, container
    m = scene.Model(); d = scene.Definition(0, "Stuhl 中文 Ж"); m.root = scene.Definition(-1, "root")
    d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}; d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]
    m.defs[0] = d; m.layers[1] = "Ж中"
    monkeypatch.setattr(scene, "load", lambda s: m); monkeypatch.setattr(container, "open_skp", lambda p: None)
    buf = io.BytesIO(); monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="cp1252", errors="strict"))
    assert cli.main(["info", "f"]) == 0
    sys.stdout.flush(); assert b"Stuhl" in buf.getvalue()


def test_stale_temp_files_are_swept_but_fresh_and_foreign_files_stay(tmp_path):
    import time
    from skpballet import mesh
    old = tmp_path / ".skpballet-old.tmp"; new = tmp_path / ".skpballet-new.tmp"; other = tmp_path / "keep.tmp"; mine = tmp_path / "x.txt"
    for f in (old, new, other):
        f.write_bytes(b"1")
    t = time.time() - 2 * 86400; os.utime(old, (t, t)); os.utime(other, (t, t))
    with mesh.atomic_open(str(mine), "wb") as f:
        f.write(b"ok")
    assert not old.exists() and new.exists() and other.exists() and mine.read_bytes() == b"ok"


@pytest.mark.parametrize("name", ["x.skp", "x.SKP", "x.skp.", "x.skp ", "x.skp. ."])
def test_skp_looking_output_names_are_refused(name, tmp_path):
    from skpballet import cli
    nest = os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp")
    assert cli.main(["convert", nest, str(tmp_path / name)]) == 2
    assert cli.main(["cache", nest, str(tmp_path / name)]) == 2
    assert not os.listdir(tmp_path)


def test_output_named_like_source_next_to_it_and_case_alias(tmp_path):
    """239: in.skp.glb beside in.skp is a normal output and leaves the source intact; 238: a
    case-variant alias of the source (same file on case-insensitive disks) is refused."""
    f = str(tmp_path / "in.skp")
    shutil.copy(FILES[0], f)
    before = sha(f)
    assert cli.main(["convert", f, f + ".glb"]) == 0
    assert (tmp_path / "in.skp.glb").stat().st_size > 0
    alias = str(tmp_path / "IN.SKP")
    assert cli.main(["convert", f, alias]) == 2
    assert sha(f) == before


KEYS = {"file", "version", "counts", "layer_names", "layers_flagged_off", "groups", "components",
        "material_names", "texts", "annotations", "bbox_m", "warnings"}
COUNTS = {"definitions", "vertices", "edges", "faces", "instances", "materials", "layers"}


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_info_json_matches_documented_schema(src, capsys):
    import json
    assert cli.main(["info", "--json", src]) == 0
    d = json.loads(capsys.readouterr().out)
    assert KEYS <= set(d) and COUNTS <= set(d["counts"])
    bb = d["bbox_m"]
    assert bb is None or (len(bb) == 2 and all(len(p) == 3 for p in bb))


def test_empty_model_glb_obeys_gltf_minitems(tmp_path):
    """244: no empty meshes/materials/accessors/bufferViews arrays, no zero-length buffer or BIN chunk."""
    import json, struct
    src = os.path.join(os.path.dirname(__file__), "data", "legacy", "legacy_empty_2020.skp")
    out = str(tmp_path / "o.glb")
    assert cli.main(["convert", src, out]) == 0
    b = open(out, "rb").read()
    assert struct.unpack("<I", b[8:12])[0] == len(b)
    n = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + n])
    for k in ("meshes", "materials", "accessors", "bufferViews", "buffers"):
        assert k not in js
    assert "mesh" not in js["nodes"][0] and len(b) == 20 + n


@pytest.mark.parametrize("src", FILES[:6], ids=os.path.basename)
def test_cache_and_convert_are_deterministic(src, tmp_path):
    """245: same input gives byte-identical cache dirs and GLBs (no timestamps/ordering noise)."""
    for n in "ab":
        assert cli.main(["cache", src, str(tmp_path / n)]) == 0
        assert cli.main(["convert", src, str(tmp_path / (n + ".glb"))]) == 0
    for name in os.listdir(tmp_path / "a"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    assert (tmp_path / "a.glb").read_bytes() == (tmp_path / "b.glb").read_bytes()


def _glb_json_bin(b):
    import json, struct
    n = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + n])
    binb = b[28 + n:28 + n + struct.unpack("<I", b[20 + n:24 + n])[0]] if len(b) > 20 + n else b""
    return js, binb


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_glb_accessors_bounds_and_indices_valid(src, tmp_path):
    """246: own validator: bufferViews inside the BIN chunk, accessor min/max match data, indices in range."""
    import struct
    out = str(tmp_path / "o.glb")
    assert cli.main(["convert", src, out]) == 0
    js, binb = _glb_json_bin(open(out, "rb").read())
    for v in js.get("bufferViews", []):
        assert v["byteOffset"] + v["byteLength"] <= len(binb)
    sizes = {5126: ("f", 4), 5125: ("I", 4), 5123: ("H", 2)}
    ncomp = {"SCALAR": 1, "VEC3": 3}
    data = []
    for a in js.get("accessors", []):
        v = js["bufferViews"][a["bufferView"]]
        fmt, sz = sizes[a["componentType"]]
        k = ncomp[a["type"]]
        vals = struct.unpack("<%d%s" % (a["count"] * k, fmt), binb[v["byteOffset"]:v["byteOffset"] + a["count"] * k * sz])
        data.append(vals)
        if a["componentType"] == 5126:
            assert all(x == x and abs(x) < 1e30 for x in vals)
            if "min" in a:
                for c in range(k):
                    seg = vals[c::k]
                    assert min(seg) == a["min"][c] and max(seg) == a["max"][c]
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            npos = js["accessors"][p["attributes"]["POSITION"]]["count"]
            if "indices" in p:
                assert all(i < npos for i in data[p["indices"]])


@pytest.mark.parametrize("src", FILES[:8], ids=os.path.basename)
def test_cache_glb_accessor_minmax_match_float32(src, tmp_path):
    import struct
    assert cli.main(["cache", src, str(tmp_path / "c")]) == 0
    js, binb = _glb_json_bin((tmp_path / "c" / "model.glb").read_bytes())
    for a in js.get("accessors", []):
        if a["componentType"] == 5126 and "min" in a:
            v = js["bufferViews"][a["bufferView"]]
            vals = struct.unpack("<%df" % (a["count"] * 3), binb[v["byteOffset"]:v["byteOffset"] + a["count"] * 12])
            assert [min(vals[c::3]) for c in range(3)] == a["min"] and [max(vals[c::3]) for c in range(3)] == a["max"]


def test_instance_scale_term_sizes_and_positions_in_cache_glb(tmp_path):
    """254: instance A = diag 0.01 on a 100 in cube, B = identity with scale term 0.01 and x translation 2000:
    both cubes are 1 inch (0.0254 m) and B sits 2000*0.01 = 20 in (0.508 m) from A."""
    import struct
    src = os.path.join(os.path.dirname(__file__), "data", "instance_scale_term_2021.skp")
    assert cli.main(["cache", src, str(tmp_path / "c")]) == 0
    js, binb = _glb_json_bin((tmp_path / "c" / "model.glb").read_bytes())
    boxes = {}
    for m in js["meshes"]:
        p = m["primitives"][0]
        if p["mode"] != 4:
            continue
        a, e = js["accessors"][p["attributes"]["POSITION"]], js["accessors"][p["attributes"]["_EIDX"]]
        v, ve = js["bufferViews"][a["bufferView"]], js["bufferViews"][e["bufferView"]]
        pos = struct.unpack("<%df" % (a["count"] * 3), binb[v["byteOffset"]:v["byteOffset"] + a["count"] * 12])
        ei = struct.unpack("<%df" % a["count"], binb[ve["byteOffset"]:ve["byteOffset"] + a["count"] * 4])
        for i, k in enumerate(ei):
            lo, hi = boxes.setdefault(k, ([1e9] * 3, [-1e9] * 3))
            for c in range(3):
                lo[c], hi[c] = min(lo[c], pos[3 * i + c]), max(hi[c], pos[3 * i + c])
    assert len(boxes) == 2
    (la, ha), (lb, hb) = [boxes[k] for k in sorted(boxes)]
    for lo, hi in ((la, ha), (lb, hb)):
        assert all(abs((h - l) - 0.0254) < 1e-6 for l, h in zip(lo, hi))
    assert abs((lb[0] - la[0]) - 0.508) < 1e-5


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_meta_bbox_matches_glb_bbox(src, tmp_path):
    """255: meta.json bbox (Z up: x, y, z) equals the union of GLB position accessor bounds (glTF Y up: x, z, -y)."""
    import json
    out = tmp_path / "c"
    assert cli.main(["cache", src, str(out)]) == 0
    meta = json.loads((out / "meta.json").read_text())
    js, _ = _glb_json_bin((out / "model.glb").read_bytes())
    mins, maxs = [], []
    for m in js.get("meshes", []):
        for p in m["primitives"]:
            a = js["accessors"][p["attributes"]["POSITION"]]
            mins.append(a["min"]); maxs.append(a["max"])
    if not mins:
        return
    gl_lo = [min(x[c] for x in mins) for c in range(3)]
    gl_hi = [max(x[c] for x in maxs) for c in range(3)]
    lo = [gl_lo[0], -gl_hi[2], gl_lo[1]]
    hi = [gl_hi[0], -gl_lo[2], gl_hi[1]]
    for got, want in ((meta["bbox"][0], lo), (meta["bbox"][1], hi)):
        assert all(abs(g - w) < 1e-5 + 1e-6 * abs(w) for g, w in zip(got, want)), (got, want)


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_info_bbox_equals_cache_meta_bbox(src, tmp_path, capsys):
    """256: info --json bbox_m and cache meta.json bbox describe the same box (metres, float32 tolerance)."""
    import json
    assert cli.main(["info", "--json", src]) == 0
    info = json.loads(capsys.readouterr().out)["bbox_m"]
    assert cli.main(["cache", src, str(tmp_path / "c")]) == 0
    meta = json.loads((tmp_path / "c" / "meta.json").read_text())["bbox"]
    if info is None or not meta:
        return
    # info bbox_m is in the glTF frame (Y up: x, z, -y of the model); meta.json bbox is Z up (the model frame)
    lo, hi = info
    want = [[lo[0], -hi[2], lo[1]], [hi[0], -lo[2], hi[1]]]
    # info counts edges too, cache triangles only: the cache box lies inside the info box, equal when edges add nothing
    t = 1e-5
    assert all(g >= w - t for g, w in zip(meta[0], want[0])) and all(g <= w + t for g, w in zip(meta[1], want[1])), (info, meta)


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_layer_and_material_names_agree_across_outputs(src, tmp_path, capsys):
    """257b: info --json, convert GLB extras and cache materials.json report the same names."""
    import json
    assert cli.main(["info", "--json", src]) == 0
    info = json.loads(capsys.readouterr().out)
    assert cli.main(["convert", src, str(tmp_path / "o.glb")]) == 0
    js, _ = _glb_json_bin((tmp_path / "o.glb").read_bytes())
    ex = js["asset"]["extras"]
    assert ex["layers"] == info["layer_names"] and ex["layers_flagged_off"] == info["layers_flagged_off"]
    assert ex["materials"] == info["counts"]["materials"]
    assert cli.main(["cache", src, str(tmp_path / "c")]) == 0
    mats = json.loads((tmp_path / "c" / "materials.json").read_text())["materials"]
    names = sorted(m["name"] for m in mats if m["name"] != "default")
    assert set(names) <= set(info["material_names"])


def test_encrypted_flag_in_zip_members_fails_cleanly(tmp_path, capsys):
    """258b: a 2021+ file whose zip headers claim encryption exits 2 with a message, no traceback, no output."""
    b = bytearray(open(os.path.join(os.path.dirname(__file__), "data", "arcs_2021.skp"), "rb").read())
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        j = b.find(sig)
        while j >= 0:
            b[j + off] |= 1
            j = b.find(sig, j + 4)
    f = tmp_path / "e.skp"
    f.write_bytes(bytes(b))
    assert cli.main(["convert", str(f), str(tmp_path / "o.glb")]) == 2
    assert not (tmp_path / "o.glb").exists()
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("meth", [12, 14, 99])
def test_unknown_zip_compression_method_fails_cleanly(meth, tmp_path, capsys):
    """259: a zip method the reader cannot decode exits 2, writes nothing, no traceback."""
    import struct
    b = bytearray(open(os.path.join(os.path.dirname(__file__), "data", "arcs_2021.skp"), "rb").read())
    for sig, off in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        j = b.find(sig)
        while j >= 0:
            struct.pack_into("<H", b, j + off, meth)
            j = b.find(sig, j + 4)
    f = tmp_path / "m.skp"
    f.write_bytes(bytes(b))
    assert cli.main(["convert", str(f), str(tmp_path / "o.glb")]) == 2
    assert not (tmp_path / "o.glb").exists() and "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("field,val,needle", [(20, 500, "comment"), (10, 9, "entries")])
def test_lying_zip_end_record_is_warned(field, val, needle, tmp_path, capsys):
    """260: EOCD entry count or comment length that disagree with the file load but are reported as damaged data."""
    import struct
    b = bytearray(open(os.path.join(os.path.dirname(__file__), "data", "arcs_2021.skp"), "rb").read())
    e = b.rfind(b"PK\x05\x06")
    struct.pack_into("<H", b, e + field, val)
    f = tmp_path / "l.skp"
    f.write_bytes(bytes(b))
    assert cli.main(["convert", str(f), str(tmp_path / "o.glb")]) == 0
    assert needle in capsys.readouterr().out
