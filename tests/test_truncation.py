"""Truncated files must fail or degrade quickly, never hang or crash with a non-ValueError/OSError."""
import glob, os, signal, time
import pytest
from skpballet import cli

DATA = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(os.path.join(DATA, "*.skp")) + glob.glob(os.path.join(DATA, "legacy", "*.skp")))


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang()


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM (not on Windows)")
@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_truncation_sweep(src, tmp_path):
    data = open(src, "rb").read()
    cuts = sorted(set(list(range(0, len(data), 1024)) + [1, 16, 64, len(data) - 1]))
    f = str(tmp_path / "t.skp")
    signal.signal(signal.SIGALRM, _alarm)
    worst = 0.0
    for n in cuts:
        if n >= len(data):
            continue
        open(f, "wb").write(data[:n])
        signal.alarm(10)
        t = time.time()
        try:
            rc = cli.main(["convert", f, str(tmp_path / "o.glb")])
        finally:
            signal.alarm(0)
        worst = max(worst, time.time() - t)
        assert rc in (0, 2), (n, rc)
    assert worst < 5


def test_legacy_truncation_is_warned(tmp_path, capsys):
    src = os.path.join(DATA, "legacy", "chair_and_table.skp")
    f = str(tmp_path / "t.skp")
    open(f, "wb").write(open(src, "rb").read()[:18432])
    assert cli.main(["info", f]) == 0
    assert "no known end marker" in capsys.readouterr().out


def test_tail_heuristic_no_false_positive_and_catches_cut():
    from skpballet import legacy
    full = open(os.path.join(DATA, "legacy", "chair_and_table.skp"), "rb").read()
    assert not legacy.tail_suspect(full, "17.0.1")
    for p in glob.glob(os.path.join(DATA, "legacy", "*.skp")):
        d = open(p, "rb").read()
        if d[:4] == b"\xff\xfe\xff\x0e":
            assert not legacy.tail_suspect(d, "17.0.1"), p
    assert legacy.tail_suspect(full[:18432], "17.0.1")
    assert legacy.tail_suspect(full[:28000], "17.0.1")


def test_strict_exit_status(tmp_path):
    src = os.path.join(DATA, "legacy", "chair_and_table.skp")
    full = open(src, "rb").read()
    f = str(tmp_path / "t.skp")
    open(f, "wb").write(full)
    assert cli.main(["info", "--strict", f]) == 0
    open(f, "wb").write(full[:18432])
    assert cli.main(["info", "--strict", f]) == 3
    assert cli.main(["info", f]) == 0


def test_real_versions_no_false_truncation_warning_and_cut_empty_model_warns():
    from skpballet import container, scene
    for p in glob.glob(os.path.join(DATA, "legacy", "*.skp")):
        d = open(p, "rb").read()
        if d[:4] == b"\xff\xfe\xff\x0e":
            m = scene.load(container.open_skp(d))
            assert not any("TRUNCATED" in w for w in m.warnings), p
    d = open(os.path.join(DATA, "legacy", "chair_and_table.skp"), "rb").read()[:2048]
    m = scene.load(container.open_skp(d))   # cut before any geometry: used to look like an empty model
    assert any("TRUNCATED" in w for w in m.warnings)


def test_header_only_cut_of_every_2017plus_file_warns():
    from skpballet import container, scene
    n = 0
    for p in glob.glob(os.path.join(DATA, "legacy", "*.skp")):
        d = open(p, "rb").read()
        if d[:4] != b"\xff\xfe\xff\x0e" or len(d) < 4000:
            continue
        sk = container.open_skp(d[:2048])
        if sk.version.split(".")[0] == "3":
            continue
        n += 1
        assert any("TRUNCATED" in w for w in scene.load(sk).warnings), p
    assert n >= 20


def test_incomplete_warning_names_the_stop_reason():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(DATA, "legacy", "legacy_text_arrows_2017.skp")))
    assert any("unsupported class CText" in w for w in m.warnings)


def test_unread_object_classes_are_reported():
    from skpballet import container, scene
    for name, cls in (("image.skp", "CImage"), ("legacy_text_arrows_2017.skp", "CText")):
        m = scene.load(container.open_skp(os.path.join(DATA, "legacy", name)))
        assert any("NOT read" in w and cls in w for w in m.warnings), name
    m = scene.load(container.open_skp(os.path.join(DATA, "legacy", "chair_and_table.skp")))
    assert not any("NOT read" in w for w in m.warnings)


def test_2021_unread_entity_collections_reported():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(DATA, "annotation_layers_vff.skp")))
    assert not any("NOT read" in w for w in m.warnings)   # 0x1391/0x1392/0x1398/0x1399 are decoded now
    # an unknown collection tag must still be reported
    from skpballet import scene as sc
    assert 0x1391 in sc._KNOWN_ENT_TAGS and 0x13FF not in sc._KNOWN_ENT_TAGS
    for n in ("arcs_2021.skp", "nesting_2021.skp", "scene_without_camera_2021.skp", "instance_scale_term_2021.skp"):
        m = scene.load(container.open_skp(os.path.join(DATA, n)))
        assert not any("NOT read" in w for w in m.warnings), n


def test_2021_screen_texts_decoded():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(DATA, "annotation_layers_vff.skp")))
    texts = sorted(t["text"] for d in list(m.defs.values()) + [m.root] for t in d.texts)
    assert texts == ["Closed arrow", "Dot", "Nested screen note", "Open arrow"]
    assert not any("0x1398" in w for w in m.warnings)


def test_2021_annotations_decoded():
    from skpballet import container, scene
    m = scene.load(container.open_skp(os.path.join(DATA, "annotation_layers_vff.skp")))
    ann = [a for d in list(m.defs.values()) + [m.root] for a in d.annotations]
    kinds = sorted(a["kind"] for a in ann)
    assert kinds == ["dimension"] * 4 + ["guide point"] * 4 + ["section plane"] * 4
    sp = next(a for a in ann if a["kind"] == "section plane")
    assert sp["point"] == [1.0, 2.0, 3.0] and abs(sum(x * x for x in sp["normal"]) - 1) < 1e-12
    dm = next(a for a in ann if a["kind"] == "dimension")
    assert dm["start"] == [0.0, 0.0, 0.0] and dm["end"] == [10.0, 0.0, 0.0]


def test_unknown_entity_tag_is_warned_once():
    from skpballet import scene, tlv
    unk = lambda: tlv.Node(0x13FF, b"\x01\x02", [])
    ent = tlv.Node(0x1388, b"", [unk(), unk()])
    m = scene.Model()
    scene._entities(ent, scene.Definition(-1, "root"), m)
    assert [w for w in m.warnings if "0x13FF is NOT read" in w] == [m.warnings[0]]
    assert len(m.warnings) == 1


def test_2021_layer_names_are_read():
    from skpballet import container, scene
    got = {n: sorted(scene.load(container.open_skp(os.path.join(DATA, n))).layers.values())
           for n in ("arcs_2021.skp", "scene_without_camera_2021.skp", "annotation_layers_vff.skp")}
    assert got["arcs_2021.skp"] == ["Layer0"]
    assert got["scene_without_camera_2021.skp"] == ["Furniture", "Layer0"]
    assert "Layer0" in got["annotation_layers_vff.skp"] and len(got["annotation_layers_vff.skp"]) == 4
    assert all(got["annotation_layers_vff.skp"])
