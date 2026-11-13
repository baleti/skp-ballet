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
