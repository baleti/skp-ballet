"""Tag-length-value reader for model.dat. Tag u16 LE, length u32 LE, payload."""
import struct

# Container tags (nested TLV), per public OpenSKP notes and own verification.
CONTAINERS = {
    0x01F4, 0x01F7, 0x30D4, 0x30D5, 0x32C8, 0x157C, 0x1388, 0x1389, 0x138A, 0x138B,
    0x138C, 0x138D, 0x1D4C, 0x1964, 0x01F9, 0x1770, 0x1771, 0x07D0, 0x09C4, 0x1194,
    0x1195, 0x010F, 0x4A38, 0x0BB8, 0x1397, 0x4C2C, 0x0DAC, 0x0DAE, 0x01F6, 0x01F8,
    0x3A98, 0x3A99, 0x3C8C, 0x3C8D, 0x1390, 0x1F40, 0x1391, 0x1392, 0x4269, 0x426C,
    0x4268,
}
MAX_DEPTH = 64


class Node:
    __slots__ = ("tag", "payload", "children")

    def __init__(self, tag, payload, children):
        self.tag, self.payload, self.children = tag, payload, children

    def find(self, tag):
        return [c for c in self.children if c.tag == tag]

    def first(self, tag):
        for c in self.children:
            if c.tag == tag:
                return c

    def uint(self):
        return int.from_bytes(self.payload, "little")

    def f64s(self):
        n = len(self.payload) // 8
        return struct.unpack("<%dd" % n, self.payload[: n * 8])

    def text(self):
        return self.payload.decode("utf-8", "replace")


def parse_tlv(data, start=0, end=None, depth=0):
    end = len(data) if end is None else end
    if depth > MAX_DEPTH:
        raise ValueError("TLV nesting too deep")
    out, p = [], start
    while p + 6 <= end:
        tag, ln = struct.unpack_from("<HI", data, p)
        q = p + 6 + ln
        if q > end:
            break
        if tag in CONTAINERS and ln:
            # container payload is not copied (children carry the data); avoids O(depth*size) copying
            out.append(Node(tag, b"", parse_tlv(data, p + 6, q, depth + 1)))
        else:
            out.append(Node(tag, data[p + 6 : q], []))
        p = q
    return out
