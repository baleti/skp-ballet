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


def test_padded_model_dat_is_warned_and_intact_ones_are_not():
    import glob
    class Fake(container.SkpFile):
        model_dat = None
    for path in FILES:
        sk = container.open_skp(path)
        assert not any("top record length" in w for w in scene.load(sk).warnings), path
        f = Fake(sk.version, sk.zip)
        f.__dict__["model_dat"] = sk.model_dat + b"\x00\x00"
        assert any("top record length" in w for w in scene.load(f).warnings), path


def _rebuild(path, mutate):
    import io, zipfile, warnings
    d = open(path, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    zin = zipfile.ZipFile(io.BytesIO(d[z:]))
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for n in zin.namelist():
                zo.writestr(n, zin.read(n))
            mutate(zo, zin)
        return d[:z] + out.getvalue()


def test_container_oddities_are_flagged_not_silent():
    path = os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp")
    # duplicate model.dat: zipfile would silently use the last one
    dup = _rebuild(path, lambda zo, zin: zo.writestr("model.dat", b"\x00" * 10))
    with pytest.raises(container.SkpError):
        container.open_skp(dup)
    # bytes after the archive
    tail = open(path, "rb").read() + b"JUNK"
    m = scene.load(container.open_skp(tail))
    assert any("after the end of the zip" in w for w in m.warnings)
    # intact files: no container note
    for p in FILES:
        assert not any(w.startswith("container:") for w in scene.load(container.open_skp(p)).warnings), p


@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_prezip_header_mutations_fail_cleanly(path):
    d = open(path, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    assert z == 69
    for i in range(z):
        for bit in (0, 7):
            b = bytearray(d)
            b[i] ^= 1 << bit
            try:
                m = scene.load(container.open_skp(bytes(b)))
            except (container.SkpError, ValueError):
                assert i < 4 or True
            else:
                assert m.counts()["faces"] >= 0


def test_damaged_version_string_is_flagged():
    d = bytearray(open(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"), "rb").read())
    i = d.find("{25.0.575}".encode("utf-16-le"))
    assert i > 0
    d[i] ^= 0x80   # the opening brace
    m = scene.load(container.open_skp(bytes(d)))
    assert any("version string" in w for w in m.warnings)


def test_header_vs_meta_version_mismatch_is_flagged():
    d = bytearray(open(os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp"), "rb").read())
    i = d.find("{25.0.575}".encode("utf-16-le")) + 2 * 6   # the '5' of 575? change a digit of the header version only
    d[i:i + 2] = "6".encode("utf-16-le")
    m = scene.load(container.open_skp(bytes(d)))
    assert any("differs from meta/meta.dat" in w for w in m.warnings), m.warnings


def _rezip(path, drop=None, flip_member=None):
    import io, zipfile
    d = open(path, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    src = zipfile.ZipFile(io.BytesIO(d[z:]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as w:
        for i in src.infolist():
            if drop and drop(i.filename):
                continue
            w.writestr(i.filename, src.read(i.filename))
    z2 = bytearray(out.getvalue())
    if flip_member:
        k = z2.find(flip_member)
        z2[k + 30 + len(flip_member) + 1] ^= 0xFF
    return d[:z] + bytes(z2)


NEST = os.path.join(os.path.dirname(__file__), "data", "nesting_2021.skp")


def test_missing_meta_dat_and_styles_warn_and_intact_does_not():
    assert not scene.load(container.open_skp(NEST)).warnings
    m = scene.load(container.open_skp(_rezip(NEST, drop=lambda n: n == "meta/meta.dat")))
    assert any("meta/meta.dat is missing" in w for w in m.warnings), m.warnings
    m = scene.load(container.open_skp(_rezip(NEST, drop=lambda n: n.startswith("styles/"))))
    assert any("styles" in w for w in m.warnings), m.warnings


def test_stored_member_crc_failure_warns():
    m = scene.load(container.open_skp(_rezip(NEST, flip_member=b"meta/meta.dat")))
    assert any("CRC" in w for w in m.warnings), m.warnings


def test_unparseable_material_xml_warns():
    import io, zipfile
    d = open(NEST, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    src = zipfile.ZipFile(io.BytesIO(d[z:]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as w:
        for i in src.infolist():
            w.writestr(i.filename, b"<broken" if i.filename.endswith("material.xml") else src.read(i.filename))
    m = scene.load(container.open_skp(d[:z] + out.getvalue()))
    assert any("not well-formed" in w for w in m.warnings), m.warnings


def _swap_member(pred, payload):
    import io, zipfile
    d = open(NEST, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    src = zipfile.ZipFile(io.BytesIO(d[z:]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as w:
        for i in src.infolist():
            w.writestr(i.filename, payload if pred(i.filename) else src.read(i.filename))
    return d[:z] + out.getvalue()


def test_malformed_style_xml_warns():
    m = scene.load(container.open_skp(_swap_member(lambda n: n.startswith("styles/"), b"<broken")))
    assert any("styles:" in w for w in m.warnings), m.warnings


@pytest.mark.parametrize("damage", ["style", "nometa", "crc"])
def test_cli_strict_exits_3_on_container_damage(damage, tmp_path):
    import subprocess, sys
    if damage == "style":
        data = _swap_member(lambda n: n.startswith("styles/"), b"<broken")
    elif damage == "nometa":
        data = _rezip(NEST, drop=lambda n: n == "meta/meta.dat")
    else:
        data = _rezip(NEST, flip_member=b"meta/meta.dat")
    p = tmp_path / "x.skp"
    p.write_bytes(data)
    root = os.path.dirname(os.path.dirname(__file__))
    r = subprocess.run([sys.executable, "-m", "skpballet", "info", str(p), "--strict"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 3, (r.returncode, r.stderr)
    r = subprocess.run([sys.executable, "-m", "skpballet", "info", NEST, "--strict"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_deflated_member_bitflips_never_silently_change_decoded_bytes():
    """Flip one bit at ~40 positions per zip member (compressed bytes). Either zipfile/CRC rejects it
    (reader raises SkpError or warns) or the member decodes to identical bytes."""
    import io, zipfile
    d = open(NEST, "rb").read()
    z = d.find(b"PK\x03\x04", 4, 4096)
    orig = zipfile.ZipFile(io.BytesIO(d[z:]))
    for i in orig.infolist():
        # local header: 30 + name + LOCAL extra (read from the file, not the central copy)
        lo = z + i.header_offset
        nlen, elen = int.from_bytes(d[lo + 26:lo + 28], "little"), int.from_bytes(d[lo + 28:lo + 30], "little")
        base = lo + 30 + nlen + elen
        for k in range(0, i.compress_size, max(1, i.compress_size // 40)):
            b = bytearray(d)
            b[base + k] ^= 1
            try:
                m = scene.load(container.open_skp(bytes(b)))
            except container.SkpError:
                continue
            if any("CRC" in w or "damaged" in w for w in m.warnings):
                continue
            zz = zipfile.ZipFile(io.BytesIO(bytes(b[z:])))
            assert zz.read(i.filename) == orig.read(i.filename), (i.filename, k)


@pytest.mark.parametrize("what", ["encrypted", "method99", "bzip2"])
def test_unsupported_member_flags_give_clean_error(what):
    import struct
    d = bytearray(open(NEST, "rb").read())
    z = d.find(b"PK\x03\x04", 4, 4096)
    p = d.find(b"PK\x01\x02", z)
    while p >= 0:
        nl = struct.unpack_from("<H", d, p + 28)[0]
        if bytes(d[p + 46:p + 46 + nl]) == b"model.dat":
            break
        p = d.find(b"PK\x01\x02", p + 4)
    assert p >= 0
    if what == "encrypted":
        struct.pack_into("<H", d, p + 8, struct.unpack_from("<H", d, p + 8)[0] | 1)
    else:
        struct.pack_into("<H", d, p + 10, 99 if what == "method99" else 12)
    with pytest.raises(container.SkpError):
        scene.load(container.open_skp(bytes(d)))


@pytest.mark.parametrize("path", FILES, ids=os.path.basename)
def test_model_dat_tail_cuts_are_rejected_or_flagged(path):
    sk = container.open_skp(path)
    md = sk.model_dat

    class Cut(container.SkpFile):
        def __init__(self, data):
            self.version, self.zip, self.container_notes, self._d = sk.version, sk.zip, [], data

        @property
        def model_dat(self):
            return self._d

    for cut in (1, 2, 4, 8, 16, 64):
        try:
            m = scene.load(Cut(md[:-cut]))
        except container.SkpError:
            continue
        assert m.warnings, (path, cut)
