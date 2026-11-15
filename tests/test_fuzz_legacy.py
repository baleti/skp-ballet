import glob, os, random
import pytest
from skpballet.container import open_skp, SkpError

D = os.path.join(os.path.dirname(__file__), "data", "legacy")


def test_legacy_fuzz_fails_cleanly(tmp_path):
    rnd = random.Random(7)
    files = sorted(glob.glob(os.path.join(D, "*.skp")))
    for f in files:
        base = open(f, "rb").read()
        for i in range(25):
            b = bytearray(base)
            if i % 3 == 0:
                b = b[: rnd.randrange(1, len(b))]
            else:
                for _ in range(rnd.randrange(1, 12)):
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
            p = tmp_path / "f.skp"
            p.write_bytes(bytes(b))
            try:
                m = open_skp(str(p))
                getattr(m, "model", None)
                from skpballet.scene import load
                from skpballet.mesh import flatten
                flatten(load(m))
            except (SkpError, ValueError, KeyError):
                pass


def test_2021_fuzz_fails_cleanly(tmp_path):
    rnd = random.Random(11)
    from skpballet.scene import load
    from skpballet.mesh import flatten
    for f in sorted(glob.glob(os.path.join(os.path.dirname(D), "*.skp"))):
        base = open(f, "rb").read()
        for i in range(25):
            b = bytearray(base)
            if i % 3 == 0:
                b = b[: rnd.randrange(1, len(b))]
            else:
                for _ in range(rnd.randrange(1, 12)):
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
            p = tmp_path / "g.skp"
            p.write_bytes(bytes(b))
            try:
                flatten(load(open_skp(str(p))))
            except (SkpError, ValueError, KeyError):
                pass


def test_cli_strict_on_mutated_files_never_crashes_or_leaves_output(tmp_path):
    """convert/cache --strict on fuzzed legacy and 2021 files: exit code in {0,1,2,3}, no traceback, and
    exit 3 (or any failure) leaves no output file behind."""
    from skpballet import cli
    rnd = random.Random(301)
    files = sorted(glob.glob(os.path.join(D, "*.skp")))[::3] + sorted(glob.glob(os.path.join(os.path.dirname(D), "*.skp")))
    for f in files:
        base = open(f, "rb").read()
        for i in range(6):
            b = bytearray(base)
            if i % 3 == 0:
                b = b[: rnd.randrange(1, len(b))]
            else:
                for _ in range(rnd.randrange(1, 12)):
                    b[rnd.randrange(len(b))] = rnd.randrange(256)
            p = tmp_path / "in.skp"; p.write_bytes(bytes(b))
            out = tmp_path / "out.glb"
            if out.exists(): out.unlink()
            rc = cli.main(["convert", "--strict", str(p), str(out)])
            assert rc in (0, 1, 2, 3), rc
            if rc != 0:
                assert not out.exists(), (f, i, rc)
