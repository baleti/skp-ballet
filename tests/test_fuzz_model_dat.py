"""Corrupt the decompressed model.dat of the annotation fixture (all tag kinds incl. 0x1391/0x1392/0x1398/0x1399)
and check the 2021+ reader either decodes or raises a clean error (never hangs, never another exception type)."""
import os, random, signal
import pytest
from skpballet import container, scene

PATH = os.path.join(os.path.dirname(__file__), "data", "annotation_layers_vff.skp")


class Hang(Exception):
    pass


def _alarm(*_):
    raise Hang()


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM (not on Windows)")
@pytest.mark.parametrize("seed", range(6))
def test_model_dat_bitflips(seed):
    sk = container.open_skp(PATH)
    good = sk.model_dat

    class Fake(container.SkpFile):
        model_dat = None   # replaced per instance below

    rnd = random.Random(seed)
    signal.signal(signal.SIGALRM, _alarm)
    bad_types = []
    for i in range(150):
        b = bytearray(good)
        for _ in range(rnd.choice((1, 2, 4))):
            b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
        f = Fake(sk.version, sk.zip)
        f.__dict__["model_dat"] = bytes(b)
        signal.alarm(10)
        try:
            scene.load(f)
        except container.SkpError:
            pass
        except Hang:
            raise
        except Exception as e:   # anything else is a defect to report with the seed
            bad_types.append((i, type(e).__name__, str(e)[:60]))
        finally:
            signal.alarm(0)
    assert not bad_types, bad_types[:5]
