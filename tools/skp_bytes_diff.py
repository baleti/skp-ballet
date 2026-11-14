"""Byte-level diff of two .skp files as ranges, for checking that a future writer left untouched regions verbatim.
2021+ files: compares the zip member list (names, CRC32, sizes) and the DECOMPRESSED model.dat byte ranges; legacy files:
compares the raw bytes. Aggregate output only (offsets and lengths, never content), safe on private files.
usage: python3 tools/skp_bytes_diff.py A.skp B.skp      exit 0 identical, 1 different, 2 unreadable"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from skpballet import container  # noqa: E402


def ranges(a, b):
    """List of (offset_a, len_a, offset_b, len_b) for the differing blocks. Same-length inputs use a direct byte
    comparison; otherwise one block between the common prefix and suffix."""
    out = []
    if len(a) == len(b):
        i, n = 0, len(a)
        while i < n:
            if a[i] != b[i]:
                j = i
                while j < n and a[j] != b[j]:
                    j += 1
                out.append((i, j - i, i, j - i))
                i = j
            else:
                i += 1
        return out
    # different lengths: common prefix and suffix are verbatim, the middle is one block (linear time; a writer that
    # inserts or removes bytes shows up as one range, which is what the "untouched regions verbatim" check needs)
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    q = 0
    while q < min(len(a), len(b)) - p and a[len(a) - 1 - q] == b[len(b) - 1 - q]:
        q += 1
    out.append((p, len(a) - p - q, p, len(b) - p - q))
    return out


def compare(pa, pb):
    """Returns (list of text lines, identical_bool)."""
    A, B = container.open_skp(pa), container.open_skp(pb)
    lines = []
    if type(A) is not type(B):
        return ["different container kinds (2021+ zip vs legacy)"], False
    if isinstance(A, container.SkpFile):
        ia = {i.filename: (i.CRC, i.file_size) for i in A.zip.infolist()}
        ib = {i.filename: (i.CRC, i.file_size) for i in B.zip.infolist()}
        for n in sorted(set(ia) | set(ib), key=str):
            if n not in ia:
                lines.append("member only in B (%d bytes)" % ib[n][1])
            elif n not in ib:
                lines.append("member only in A (%d bytes)" % ia[n][1])
            elif ia[n] != ib[n]:
                k = n.split("/")[0]
                lines.append("member %s differs (crc %08x vs %08x, size %d vs %d)" % ("<%s>" % k if k != "model.dat" else "model.dat", ia[n][0], ib[n][0], ia[n][1], ib[n][1]))
        if ia.get("model.dat") != ib.get("model.dat") and "model.dat" in ia and "model.dat" in ib:
            for oa, la, ob, lb in ranges(A.model_dat, B.model_dat):
                lines.append("model.dat range A@%d+%d B@%d+%d" % (oa, la, ob, lb))
        return lines, not lines
    for oa, la, ob, lb in ranges(A.data, B.data):
        lines.append("file range A@%d+%d B@%d+%d" % (oa, la, ob, lb))
    return lines, not lines


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        lines, same = compare(*argv)
    except Exception as e:
        print("unreadable: %s: %s" % (type(e).__name__, e))
        return 2
    print("identical bytes (decompressed model.dat / legacy body)" if same else "\n".join(lines[:200]))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
