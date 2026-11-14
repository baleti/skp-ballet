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


_HDR = struct.Struct("<HI").unpack_from


class Node:
    """TLV node. Payload bytes and nested children are materialised lazily (most subtrees are never read)."""
    __slots__ = ("tag", "_d", "_s", "_e", "_c", "_depth", "_p")

    def __init__(self, tag, payload, children, _d=None, _s=0, _e=0, _depth=0):
        self.tag = tag
        self._d, self._s, self._e, self._depth = _d, _s, _e, _depth
        self._c = children
        self._p = payload

    @property
    def payload(self):
        if self._p is None:
            self._p = self._d[self._s:self._e]
        return self._p

    @property
    def children(self):
        if self._c is None:
            self._c = parse_tlv(self._d, self._s, self._e, self._depth + 1)
        return self._c

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
    app = out.append
    cont = CONTAINERS
    while p + 6 <= end:
        tag, ln = _HDR(data, p)
        q = p + 6 + ln
        if q > end:
            break
        if ln and tag in cont:
            app(Node(tag, b"", None, data, p + 6, q, depth))
        else:
            app(Node(tag, None, [], data, p + 6, q, depth))
        p = q
    return out


def tiling_errors(data, max_depth=5):
    """Count container nodes down to max_depth whose children do not tile the payload exactly (a child overruns the parent, or
    bytes are left over). Intact public 2021+ fixtures give 0 down to depth 5; deeper levels (6) show overruns in intact files
    (non-TLV payloads under a container tag), so they are not checked. Used as a 'damaged data' signal."""
    n = 0
    stack = [(0, len(data), 0)]
    while stack:
        s, e, depth = stack.pop()
        p = s
        while p + 6 <= e:
            tag, ln = _HDR(data, p)
            q = p + 6 + ln
            if q > e:
                n += 1
                break
            if ln and tag in CONTAINERS and depth < max_depth:
                stack.append((p + 6, q, depth + 1))
            p = q
        else:
            if p != e:
                n += 1
    return n
