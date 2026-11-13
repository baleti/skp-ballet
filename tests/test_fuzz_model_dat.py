"""Corrupt the decompressed model.dat of the annotation fixture (all tag kinds incl. 0x1391/0x1392/0x1398/0x1399)
and check the 2021+ reader either decodes or raises a clean error (never hangs, never another exception type)."""
import glob, os, random, signal
import pytest
from skpballet import container, mesh, scene

FILES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "data", "*.skp")))


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang()


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM (not on Windows)")
@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_model_dat_bitflips(path, seed, tmp_path):
    sk = container.open_skp(path)
    good = sk.model_dat

    class Fake(container.SkpFile):
        model_dat = None   # replaced per instance below

    rnd = random.Random(seed)
    signal.signal(signal.SIGALRM, _alarm)
    bad_types = []
    for i in range(60):
        b = bytearray(good)
        for _ in range(rnd.choice((1, 2, 4))):
            b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        f = Fake(sk.version, sk.zip)
        f.__dict__["model_dat"] = bytes(b)
        signal.alarm(10)
        try:
            mesh.write_glb(scene.load(f), str(tmp_path / "o.glb"))
        except (container.SkpError, ValueError):
            pass
        except Hang:
            raise
        except Exception as e:   # anything else is a defect to report with the seed
            bad_types.append((i, type(e).__name__, str(e)[:60]))
        finally:
            signal.alarm(0)
    assert not bad_types, bad_types[:5]
