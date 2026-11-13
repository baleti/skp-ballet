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


def _records(b, base=0, depth=0, out=None):
    """(header offset, end offset) of every record in b that parses as a clean TLV run (nested up to depth 4)."""
    import struct
    out = [] if out is None else out
    p = 0
    spans = []
    while p + 6 <= len(b):
        t, l = struct.unpack_from("<HI", b, p)
        if p + 6 + l > len(b):
            return out if not spans else out  # not a clean run: ignore this level
        spans.append((p, p + 6 + l))
        p += 6 + l
    if p != len(b):
        return out
    for s, e in spans:
        out.append((base + s, base + e))
        if depth < 4 and e - s > 12:
            _records(b[s + 6:e], base + s + 6, depth + 1, out)
    return out


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM (not on Windows)")
@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_model_dat_structural_mutations(path, seed, tmp_path):
    import struct
    sk = container.open_skp(path)
    good = sk.model_dat
    recs = _records(good)
    assert len(recs) > 20
    tags = sorted({struct.unpack_from("<H", good, s)[0] for s, _ in recs})

    class Fake(container.SkpFile):
        model_dat = None

    rnd = random.Random(seed)
    signal.signal(signal.SIGALRM, _alarm)
    bad = []
    for i in range(60):
        s, e = recs[rnd.randrange(len(recs))]
        b = bytearray(good)
        kind = rnd.choice(("len+", "len-", "lenmax", "delete", "dup", "tag"))
        if kind == "len+":
            struct.pack_into("<I", b, s + 2, struct.unpack_from("<I", b, s + 2)[0] + rnd.randint(1, 40))
        elif kind == "len-":
            struct.pack_into("<I", b, s + 2, max(0, struct.unpack_from("<I", b, s + 2)[0] - rnd.randint(1, 40)))
        elif kind == "lenmax":
            struct.pack_into("<I", b, s + 2, 0xFFFFFFFF)
        elif kind == "delete":
            del b[s:e]
        elif kind == "dup":
            b[e:e] = good[s:e]
        else:
            struct.pack_into("<H", b, s, rnd.choice(tags))
        f = Fake(sk.version, sk.zip)
        f.__dict__["model_dat"] = bytes(b)
        signal.alarm(10)
        try:
            mesh.write_glb(scene.load(f), str(tmp_path / "o.glb"))
        except (container.SkpError, ValueError):
            pass
        except Hang:
            raise
        except Exception as ex:
            bad.append((i, kind, type(ex).__name__, str(ex)[:60]))
        finally:
            signal.alarm(0)
    assert not bad, bad[:5]
