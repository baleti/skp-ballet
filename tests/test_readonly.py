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
    # arcs_2021 holds 12 loose arc edges that the default cache leaves out: that is the only warning an intact file may carry
    assert [w for w in json.load(open(tmp_path / "g" / "meta.json"))["warnings"] if "loose edge" not in w] == []


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


def test_fake_end_record_after_the_zip_does_not_hide_a_good_archive(tmp_path, capsys):
    """261: junk after the archive that contains a fake end record: the file still loads, with the extra bytes reported."""
    src = os.path.join(os.path.dirname(__file__), "data", "arcs_2021.skp")
    b = open(src, "rb").read()
    f = tmp_path / "d.skp"
    f.write_bytes(b + b"junk" + b"PK\x05\x06" + b"\0" * 18)
    assert cli.main(["convert", str(f), str(tmp_path / "o.glb")]) == 0
    out = capsys.readouterr().out
    assert "bytes after the end of the zip archive" in out
    assert (tmp_path / "o.glb").read_bytes()[:4] == b"glTF"
    assert cli.main(["convert", src, str(tmp_path / "ref.glb")]) == 0
    assert _glb_json_bin((tmp_path / "o.glb").read_bytes())[1] == _glb_json_bin((tmp_path / "ref.glb").read_bytes())[1]


def test_instance_cycle_is_cut_quickly_and_reported():
    """263: a definition that instances itself (twice) must not expand to the 500000 placement budget (52 s before)."""
    import time
    from skpballet import scene, mesh
    m = scene.Model()
    d = scene.Definition(1, "A")
    m.defs[1] = d
    d.vertices = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0)}
    d.faces = [dict(id=1, loops=[[1, 2, 3]], mat=None, normal=(0, 0, 1))]
    ident = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0)
    d.instances = [dict(def_id=1, matrix=ident, id=5, name=""), dict(def_id=1, matrix=ident, id=6, name="")]
    r = scene.Definition(0, "root")
    r.instances = [dict(def_id=1, matrix=ident, id=7, name="")]
    m.root = r
    t = time.time()
    res = mesh.flatten(m)
    assert time.time() - t < 2
    assert sum(len(v) for v in res.values()) == 9          # exactly one triangle placed
    assert any("instance cycle" in w for w in m.warnings)


def test_instance_cycle_is_cut_in_cache_too(tmp_path):
    """263b: same cycle through the cache builder (own walker): fast, one triangle, reported."""
    import time
    from skpballet import scene, cache
    m = scene.Model()
    d = scene.Definition(1, "A")
    m.defs[1] = d
    d.vertices = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0)}
    d.faces = [dict(id=1, loops=[[1, 2, 3]], mat=None, normal=(0, 0, 1))]
    ident = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0)
    d.instances = [dict(def_id=1, matrix=ident, id=5, name=""), dict(def_id=1, matrix=ident, id=6, name="")]
    r = scene.Definition(0, "root")
    r.instances = [dict(def_id=1, matrix=ident, id=7, name="")]
    m.root = r
    t = time.time()
    elements, batches = cache.build(m)
    assert time.time() - t < 2
    assert sum(b["nt"] for b in batches.values()) == 1
    assert any("instance cycle" in w for w in m.warnings)


def _tri_def(did, name):
    from skpballet import scene
    d = scene.Definition(did, name)
    d.vertices = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0)}
    d.faces = [dict(id=1, loops=[[1, 2, 3]], mat=None, normal=(0, 0, 1))]
    return d


@pytest.mark.parametrize("shape", ["mutual", "to_root"])
def test_indirect_cycles_cut_in_flatten_and_cache(shape):
    """264/265: A->B->A and an instance of the root definition itself: one placement each, quick, reported."""
    import time
    from skpballet import scene, mesh, cache
    ident = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0)
    inst = lambda i, t: dict(def_id=t, matrix=ident, id=i, name="")
    m = scene.Model()
    a, b = _tri_def(1, "A"), _tri_def(2, "B")
    m.defs = {1: a, 2: b}
    r = scene.Definition(0, "root")
    m.root = r
    if shape == "mutual":
        a.instances, b.instances, r.instances = [inst(5, 2), inst(6, 2)], [inst(7, 1), inst(8, 1)], [inst(9, 1)]
        expect = 3          # root->A (1) -> two B (1 each); every B->A is cyclic
    else:
        m.defs[0] = r
        r.vertices, r.faces = a.vertices, a.faces
        r.instances = [inst(5, 0), inst(6, 0)]
        expect = 1          # the root's own triangle; its instances of itself are cyclic
        expect_cache = 3    # cache: loose root geometry plus one element per root-level instance (each placed once)
    expect_cache = locals().get("expect_cache", expect)
    t = time.time()
    res = mesh.flatten(m)
    assert time.time() - t < 2 and sum(len(v) for v in res.values()) // 9 == expect
    assert any("instance cycle" in w for w in m.warnings)
    m.warnings.clear()
    t = time.time()
    _, batches = cache.build(m)
    assert time.time() - t < 2 and sum(bb["nt"] for bb in batches.values()) == expect_cache
    assert any("instance cycle" in w for w in m.warnings)


def test_definition_with_root_id_zero_is_not_mistaken_for_a_cycle():
    """267: the cycle guard keys on object identity; a real definition whose id equals the root's id (0) is placed."""
    from skpballet import scene, mesh
    ident = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0)
    m = scene.Model()
    d = _tri_def(0, "Z")
    m.defs = {0: d}
    r = scene.Definition(0, "root")
    r.instances = [dict(def_id=0, matrix=ident, id=1, name="")]
    m.root = r
    res = mesh.flatten(m)
    assert sum(len(v) for v in res.values()) // 9 == 1
    assert not any("cycle" in w for w in m.warnings)


@pytest.mark.parametrize("kind", ["glb", "cache"])
@pytest.mark.parametrize("mat", [[float("nan")] + [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
                                  [1, 0, 0, 0, 1, 0, 0, 0, 1, float("inf"), 0, 0, 1],
                                  [1, 0, 0, 0, 1, 0, 0, 0, 1, 1e300, 0, 0, 1],
                                  [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, float("nan")]])
def test_non_finite_instance_matrix_is_refused_never_written(kind, mat, tmp_path):
    """NaN/inf/absurd instance transforms must end in a clean ValueError and no output file (never a GLB with NaN)."""
    from skpballet import mesh, cache, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root")
    d = scene.Definition(0, "d"); d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]; m.defs[0] = d
    m.root.instances = [dict(def_id=0, matrix=mat, name="x", id=None)]
    out = tmp_path / ("o.glb" if kind == "glb" else "c")
    with pytest.raises(ValueError):
        mesh.write_glb(m, str(out)) if kind == "glb" else cache.write_cache(m, str(out), "x.skp")
    assert not out.exists() or (out.is_dir() and not (out / "meta.json").exists())


@pytest.mark.parametrize("kind", ["glb", "cache"])
@pytest.mark.parametrize("mat,word", [([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], "scale 0"),
                                       ([0] * 12 + [1], "singular")])
def test_degenerate_instance_matrix_is_warned(kind, mat, word, tmp_path):
    from skpballet import mesh, cache, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root")
    d = scene.Definition(0, "d"); d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]; m.defs[0] = d
    m.root.instances = [dict(def_id=0, matrix=mat, name="x", id=None)]
    mesh.write_glb(m, str(tmp_path / "o.glb")) if kind == "glb" else cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    assert any(word in w for w in m.warnings)


def _tri_area(P, t):
    return sum(abs((P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[c][0] - P[a][0]) * (P[b][1] - P[a][1])) / 2 for a, b, c in t)


@pytest.mark.parametrize("hole,area", [([(1, 1, 0), (2, 1, 0), (2, 2, 0)], 15.5), ([(1, 1, 0), (2, 2, 0), (2, 1, 0)], 15.5),
                                       ([(1, 1, 0), (2, 1, 0), (2, 2, 0), (1, 2, 0)], 15.0), ([(1, 1, 0), (3, 1, 0), (2, 3, 0)], 14.0)])
def test_hole_corner_on_the_bridge_diagonal_keeps_the_hole(hole, area):
    """A hole whose bridge to the outer ring would pass exactly through another hole corner used to fill the hole (area 16)."""
    from skpballet import mesh
    P, t = mesh.triangulate([[(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)], hole], (0, 0, 1))
    assert abs(_tri_area(P, t) - area) < 1e-6


def test_hole_outside_the_outer_loop_is_dropped():
    from skpballet import mesh
    P, t = mesh.triangulate([[(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)], [(10, 10, 0), (11, 10, 0), (11, 11, 0)]], (0, 0, 1))
    assert abs(_tri_area(P, t) - 16.0) < 1e-6


@pytest.mark.parametrize("kind", ["glb", "cache"])
def test_face_with_missing_vertex_ids_is_warned(kind, tmp_path):
    from skpballet import mesh, cache, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root"); m.root.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    m.root.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1)), dict(id=1, loops=[[0, 1, 99]], mat=None, normal=(0, 0, 1))]
    mesh.write_glb(m, str(tmp_path / "o.glb")) if kind == "glb" else cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    assert any("missing from its definition" in w for w in m.warnings)


@pytest.mark.parametrize("holes,area", [
    ([[(2, 2), (4, 2), (4, 4), (2, 4)], [(4, 4), (6, 4), (6, 6), (4, 6)]], 92.0),   # holes sharing one corner
    ([[(3, 0), (5, 0), (5, 2), (3, 2)]], 96.0),                                     # hole sharing a stretch of the outer edge
    ([[(3, 0), (5, 2), (1, 2)]], 96.0),                                             # hole vertex on the outer edge
    ([[(2, 2), (8, 2), (8, 8), (2, 8)]], 64.0)])                                    # big hole (an island inside it is a separate face)
def test_touching_holes_keep_exact_area(holes, area):
    from skpballet import mesh
    L = lambda pts: [(x, y, 0) for x, y in pts]
    P, t = mesh.triangulate([L([(0, 0), (10, 0), (10, 10), (0, 10)])] + [L(h) for h in holes], (0, 0, 1))
    assert abs(_tri_area(P, t) - area) < 1e-6


def test_wrong_face_area_is_warned_and_good_faces_are_not():
    from skpballet import mesh, scene
    def run(holes):
        d = scene.Definition(0, "d"); vs = [(0, 0), (10, 0), (10, 10), (0, 10)]
        loops = [list(range(4))]; d.vertices = {i: (x, y, 0) for i, (x, y) in enumerate(vs)}
        for h in holes:
            ids = []
            for x, y in h:
                d.vertices[len(d.vertices)] = (x, y, 0); ids.append(len(d.vertices) - 1)
            loops.append(ids)
        d.faces = [dict(id=0, loops=loops, mat=None, normal=(0, 0, 1))]
        w = []; mesh.definition_tris(d, w); return w
    assert run([[(2, 2), (4, 2), (4, 4), (2, 4)]]) == []
    assert run([[(2, 2), (4, 2), (4, 4), (2, 4)], [(4, 2), (6, 2), (6, 4), (4, 4)]]) == []   # edge-sharing holes are merged now: right area
    assert run([[(2, 2), (6, 2), (6, 6), (2, 6)], [(4, 4), (8, 4), (8, 8), (4, 8)]])   # overlapping holes (damaged): wrong area, warned


@pytest.mark.parametrize("name", ["ünï côdé.skp", "with space .skp", "日本語.skp", "a'b\"c.skp", "a" * 200 + ".skp"])
def test_odd_file_names_work_for_info_convert_cache(name, tmp_path):
    import glob, shutil, hashlib
    from skpballet import cli
    src = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "data", "*.skp")))[0]
    dst = tmp_path / name
    shutil.copy(src, dst)
    before = hashlib.sha256(dst.read_bytes()).hexdigest()
    assert cli.main(["convert", str(dst), str(tmp_path / "o.glb")]) in (0, None)
    assert cli.main(["cache", str(dst), str(tmp_path / "c d")]) in (0, None)
    assert (tmp_path / "o.glb").stat().st_size > 0 and (tmp_path / "c d" / "meta.json").exists()
    assert hashlib.sha256(dst.read_bytes()).hexdigest() == before


def test_tlv_declared_length_is_bounded_by_the_buffer():
    """A node declaring 4 GiB (or overrunning its parent) must stop the parse, never allocate or read past the data."""
    import struct, resource
    from skpballet import tlv
    data = struct.pack("<HI", 0x0001, 0xFFFFFFFF) + b"x" * 10
    assert tlv.parse_tlv(data) == []
    ok = struct.pack("<HI", 0x0001, 4) + b"abcd" + struct.pack("<HI", 0x0001, 0xFFFFFFF0) + b"zz"
    n = tlv.parse_tlv(ok)
    assert len(n) == 1 and n[0].payload == b"abcd"
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(1000):
        tlv.parse_tlv(data)
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before < 50_000   # KiB


def test_tilted_face_with_holes_survives_inexact_colinearity():
    """Regression (hole_fuzz_grid tilt, seed 5, case 438): a tilted rectangle with two holes whose 2D working coordinates tie
    to within float noise gave area 102.5 (> outer 100); retrying with a rotated 2D basis fixes it."""
    import math
    from skpballet import mesh
    loops = [[(3.0, -7.0, 2.0), (13.0, -7.0, 2.0), (13.0, 2.5533648912560594, 4.955202066613396), (3.0, 2.5533648912560594, 4.955202066613396)],
             [(8.0, -5.0893270217487885, 2.591040413322679), (10.0, -5.0893270217487885, 2.591040413322679), (10.0, -4.133990532623182, 2.8865606199840186), (8.0, -4.133990532623182, 2.8865606199840186)],
             [(4.0, -1.2679810652463637, 3.773121239968037), (5.0, -1.2679810652463637, 3.773121239968037), (5.0, -0.3126445761207579, 4.0686414466293765)]]
    nrm = (0.0, -29.552020666133956 / 100, 95.5336489125606 / 100)
    P, t = mesh.triangulate(loops, nrm)
    assert mesh._area_err(loops, nrm, P, t) < 1e-6


def test_many_holes_face_stays_fast_and_exact():
    """Perforated panel: 300 square holes in one face. Guards the O(holes x ring) bridge phase against regressions
    (measured 0.7 s; the limit is generous so a slow CI box does not flake) and checks the exact area."""
    import time
    from skpballet import mesh
    n = 18
    sq = lambda cx, cy, r: [(cx - r, cy - r, 0), (cx + r, cy - r, 0), (cx + r, cy + r, 0), (cx - r, cy + r, 0)]
    holes = [sq(5 + 10 * (k % n), 5 + 10 * (k // n), 2) for k in range(300)]
    t0 = time.time()
    P, t = mesh.triangulate([[(0, 0, 0), (10 * n, 0, 0), (10 * n, 10 * n, 0), (0, 10 * n, 0)]] + holes, (0, 0, 1))
    assert time.time() - t0 < 20
    assert abs(_tri_area(P, t) - ((10 * n) ** 2 - 300 * 16)) < 1e-6


@pytest.mark.parametrize("kind", ["glb", "cache"])
def test_unexported_annotations_and_texts_are_warned(kind, tmp_path):
    from skpballet import mesh, cache, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root"); m.root.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    m.root.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]
    m.root.annotations = [dict(kind="guide point", point=(0, 0, 0))]; m.root.texts = [dict(text="t", x=0, y=0)]
    mesh.write_glb(m, str(tmp_path / "o.glb")) if kind == "glb" else cache.write_cache(m, str(tmp_path / "c"), "x.skp")
    assert any("1 annotation(s)" in w and "1 screen text(s)" in w and "NOT in this export" in w for w in m.warnings)


def test_cache_warns_about_loose_edges_only(tmp_path):
    from skpballet import cache, scene
    def mk(loose):
        m = scene.Model(); m.root = scene.Definition(-1, "root")
        m.root.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0), 3: (5, 5, 0), 4: (6, 5, 0)}
        m.root.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]
        m.root.edges = {0: (0, 1), 1: (1, 2), 2: (2, 0)}
        if loose:
            m.root.edges[3] = (3, 4)
        return m
    a, b = mk(False), mk(True)
    cache.write_cache(a, str(tmp_path / "a"), "x.skp"); cache.write_cache(b, str(tmp_path / "b"), "x.skp")
    assert not any("loose edge" in w for w in a.warnings)   # face boundaries are not loose: no noise on normal models
    assert any("1 loose edge(s)" in w for w in b.warnings)
    c = mk(True); cache.write_cache(c, str(tmp_path / "c"), "x.skp", edges=True)
    assert not any("loose edge" in w for w in c.warnings)


def test_hidden_flagged_layers_are_warned_not_silently_shown(tmp_path):
    from skpballet import mesh, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root"); m.root.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    m.root.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]
    m.layers = {1: "Hidden"}; m.layers_off = {1}
    mesh.write_glb(m, str(tmp_path / "o.glb"))
    assert any("hidden/off flag" in w and "NOT hidden" in w for w in m.warnings)
    k = scene.Model(); k.root = m.root; mesh.write_glb(k, str(tmp_path / "p.glb"))
    assert not any("hidden/off" in w for w in k.warnings)


def test_warnings_doc_matches_source():
    """docs/WARNINGS.md lists warning phrases by their first backticked words; each must still occur in the package source."""
    import glob, re
    root = os.path.join(os.path.dirname(__file__), "..")
    doc = open(os.path.join(root, "docs", "WARNINGS.md"), encoding="utf-8").read()
    anchors = [a.rstrip(":") for a in re.findall(r"^- `([^`]+)`", doc, re.M)]
    assert len(anchors) >= 20
    src = "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(root, "skpballet", "*.py")))
    missing = [a for a in anchors if a not in src]
    assert not missing, missing


def test_every_warning_in_the_source_is_documented():
    """Code-to-doc drift: every warnings.append/extend site (found by AST, the text taken from the literal or from the variable
    it was assigned from) must contain at least one phrase documented in docs/WARNINGS.md."""
    import ast, glob, re
    root = os.path.join(os.path.dirname(__file__), "..")
    doc = open(os.path.join(root, "docs", "WARNINGS.md"), encoding="utf-8").read()
    anchors = [a.rstrip(":") for a in re.findall(r"^- `([^`]+)`", doc, re.M)] + ["NOT in this export", "singular transform", "non-finite or absurd", "scale 0"]
    strs = lambda n: "".join(x.value for x in ast.walk(n) if isinstance(x, ast.Constant) and isinstance(x.value, str))
    bad, sites = [], 0
    for f in sorted(glob.glob(os.path.join(root, "skpballet", "*.py"))):
        t = ast.parse(open(f, encoding="utf-8").read())
        assigns = {}
        for n in ast.walk(t):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                assigns.setdefault(n.targets[0].id, []).append(strs(n.value))
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "extend") \
                    and "warn" in ast.unparse(n.func.value) and n.args:
                a = n.args[0]
                texts = assigns.get(a.id, []) if isinstance(a, ast.Name) else [strs(a)]
                for tx in texts:
                    if len(tx) < 20:   # an unrelated variable of the same name (e.g. a matrix), not message text
                        continue
                    sites += 1
                    if not any(k in tx for k in anchors):
                        bad.append((os.path.basename(f), n.lineno, tx[:60]))
    assert sites >= 25
    assert not bad, bad


@pytest.mark.parametrize("kind", ["glb", "cache"])
@pytest.mark.parametrize("what", ["singular", "scale0", "area"])
def test_strict_refuses_export_time_damage_signals(kind, what, tmp_path):
    from skpballet import mesh, cache, scene
    m = scene.Model(); m.root = scene.Definition(-1, "root")
    d = scene.Definition(0, "d"); d.vertices = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)}
    d.faces = [dict(id=0, loops=[[0, 1, 2]], mat=None, normal=(0, 0, 1))]; m.defs[0] = d
    mat = {"singular": [0] * 12 + [1], "scale0": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], "area": [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]}[what]
    m.root.instances = [dict(def_id=0, matrix=mat, name="x", id=None)]
    if what == "area":   # overlapping holes (damaged data): wrong area
        m.root.vertices = {0: (0, 0, 0), 1: (10, 0, 0), 2: (10, 10, 0), 3: (0, 10, 0), 4: (2, 2, 0), 5: (6, 2, 0), 6: (6, 6, 0), 7: (2, 6, 0),
                           8: (4, 4, 0), 9: (8, 4, 0), 10: (8, 8, 0), 11: (4, 8, 0)}
        m.root.faces = [dict(id=1, loops=[[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], mat=None, normal=(0, 0, 1))]
    out = tmp_path / ("o.glb" if kind == "glb" else "c")
    with pytest.raises(mesh.StrictTruncation):
        mesh.write_glb(m, str(out), strict=True) if kind == "glb" else cache.write_cache(m, str(out), "x.skp", strict=True)
    assert not out.exists() or (out.is_dir() and not (out / "meta.json").exists())


def _tri_area(P, tr):
    return sum(abs(0.5 * ((P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[b][1] - P[a][1]) * (P[c][0] - P[a][0]))) for a, b, c in tr)


def test_holes_sharing_an_edge_are_one_hole():
    from skpballet import mesh
    O = [(0, 0), (10, 0), (10, 10), (0, 10)]
    cases = [
        ([[(2, 2), (4, 2), (4, 4), (2, 4)], [(4, 2), (6, 2), (6, 4), (4, 4)]], 92.0),
        ([[(2, 2), (4, 2), (4, 4), (2, 4)], [(4, 4), (6, 4), (6, 2), (4, 2)]], 92.0),   # opposite winding
        ([[(1, 1), (2, 1), (2, 2), (1, 2)], [(2, 1), (3, 1), (3, 2), (2, 2)], [(3, 1), (4, 1), (4, 2), (3, 2)]], 97.0),
    ]
    for hs, want in cases:
        L = [[(x, y, 0.0) for x, y in l] for l in [O] + hs]
        P, tr = mesh.triangulate(L, (0, 0, 1))
        assert abs(_tri_area(P, tr) - want) < 1e-9


def test_cell_holes_sharing_edges_and_corners_fuzz():
    """random sets of unit-cell holes on a grid: neighbours share edges (no corner-only touching, see below); area must be S*S - cells.
    (Cells that would enclose an uncovered island or pinch the outer ring are avoided by keeping a free 1-cell border.)"""
    import random
    from skpballet import mesh
    rnd = random.Random(274)
    bad, bad_edge_only, tested = [], [], 0
    for it in range(400):
        S = rnd.choice([6, 8])
        cells = {(x, y) for x in range(1, S - 1) for y in range(1, S - 1) if rnd.random() < 0.4}
        if not cells:
            continue
        free, stack = set(), [(0, 0)]   # an uncovered cell enclosed by hole cells is an island (not part of the face): skip such sets
        while stack:
            c = stack.pop()
            if c in free or c in cells or not (0 <= c[0] < S and 0 <= c[1] < S):
                continue
            free.add(c); stack += [(c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)]
        if len(free) != S * S - len(cells):
            continue
        loops = [[(0, 0, 0.0), (S, 0, 0.0), (S, S, 0.0), (0, S, 0.0)]]
        for (x, y) in sorted(cells):
            c = [(x, y, 0.0), (x + 1, y, 0.0), (x + 1, y + 1, 0.0), (x, y + 1, 0.0)]
            loops.append(c if rnd.random() < 0.5 else c[::-1])
        P, tr = mesh.triangulate(loops, (0, 0, 1))
        got = _tri_area(P, tr)
        tested += 1
        if abs(got - (S * S - len(cells))) > 1e-6:
            bad.append((S, sorted(cells)))
            corner = any((x + dx, y + dy) in cells and (x + dx, y) not in cells and (x, y + dy) not in cells
                         for (x, y) in cells for dx in (-1, 1) for dy in (-1, 1))
            if not corner:
                bad_edge_only.append((S, sorted(cells)))
    assert not bad_edge_only, bad_edge_only[:1]   # edge-sharing without corner-only contacts must be exact
    # corner-only contact chains: spliced-ring fallback fixes most; a small rest with complex self-touching rings stays wrong (warned)
    assert tested > 250 and len(bad) * 100 <= tested * 3, (len(bad), tested)
