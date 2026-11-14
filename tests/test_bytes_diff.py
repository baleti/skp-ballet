import glob, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import skp_bytes_diff as bd  # noqa: E402
from skpballet import container

D = os.path.join(os.path.dirname(__file__), "data")


def test_self_identical_and_exit_codes(tmp_path):
    p = os.path.join(D, "nesting_2021.skp")
    assert bd.main([p, p]) == 0
    assert bd.main([p, os.path.join(D, "arcs_2021.skp")]) == 1
    bad = tmp_path / "b.skp"
    bad.write_bytes(b"x")
    assert bd.main([p, str(bad)]) == 2


def test_ranges_same_length_and_different_length():
    assert bd.ranges(b"abcdef", b"abXdYf") == [(2, 1, 2, 1), (4, 1, 4, 1)]
    assert bd.ranges(b"abcdef", b"abcXXdef") == [(3, 0, 3, 2)]
    assert bd.ranges(b"abcdef", b"abf") == [(2, 3, 2, 0)]
    assert bd.ranges(b"abc", b"abc") == []


def test_legacy_single_byte_change_is_one_range(tmp_path):
    src = sorted(glob.glob(os.path.join(D, "legacy", "*.skp")))[0]
    d = bytearray(open(src, "rb").read())
    d[len(d) // 2] ^= 1
    p = tmp_path / "m.skp"
    p.write_bytes(bytes(d))
    lines, same = bd.compare(src, str(p))
    assert not same and len(lines) == 1 and lines[0].endswith("+1 B@%d+1" % (len(d) // 2))


def test_2021_member_and_range_reported(tmp_path):
    src = os.path.join(D, "nesting_2021.skp")
    md = bytearray(container.open_skp(src).model_dat)
    # rebuild a stored zip with one model.dat byte changed
    import io, zipfile
    z = open(src, "rb").read()
    k = z.find(b"PK\x03\x04", 4, 4096)
    zin = zipfile.ZipFile(io.BytesIO(z[k:]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as w:
        for i in zin.infolist():
            w.writestr(i.filename, bytes(md[:100] + bytes([md[100] ^ 1]) + md[101:]) if i.filename == "model.dat" else zin.read(i.filename))
    p = tmp_path / "m.skp"
    p.write_bytes(z[:k] + out.getvalue())
    lines, same = bd.compare(src, str(p))
    assert not same and any(l == "model.dat range A@100+1 B@100+1" for l in lines), lines
