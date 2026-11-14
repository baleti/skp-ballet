"""Seeded bit-flip sweep: corrupted input must not hang or raise anything but a clean exit."""
import glob, os, random, signal, time
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
def test_bitflips(src, tmp_path):
    data = open(src, "rb").read()
    rnd = random.Random(os.path.basename(src))
    f = str(tmp_path / "b.skp")
    signal.signal(signal.SIGALRM, _alarm)
    for i in range(25):
        b = bytearray(data)
        for _ in range(rnd.choice((1, 1, 3, 8))):
            b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        open(f, "wb").write(bytes(b))
        signal.alarm(5)
        try:
            rc = cli.main(["convert", f, str(tmp_path / "o.glb")])
        finally:
            signal.alarm(0)
        assert rc in (0, 2), (i, rc)


@pytest.mark.parametrize("bad", [1e39, float("nan"), float("inf"), -1e300])
def test_absurd_coordinates_refused(bad):
    from skpballet import mesh
    with pytest.raises(ValueError):
        mesh._check_coords([0.0, 1.0, bad])
    mesh._check_coords([0.0, -5e5, 123.4])
