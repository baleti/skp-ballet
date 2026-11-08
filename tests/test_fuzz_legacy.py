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
