"""Experimental reader for SketchUp 2013-2020 (MFC CArchive) geometry. Clean-room from observation of public samples
plus format notes in docs/FORMAT.md. Handles only the geometry entities of the first entity list (CFace, CLoop,
CEdgeUse, CEdge, CVertex); everything else raises LegacyError. Slot numbers are relative to the first class
declaration of the list (absolute base unknown), so references to classes declared earlier are not supported."""
import re
import struct


class LegacyError(Exception):
    pass


class _R:
    def __init__(self, d, pos):
        self.d, self.p = d, pos
        self.classes = {}   # slot -> name
        self.objs = {}      # slot -> object
        self.slot = 1
        self.nverts = self.nedges = self.nfaces = 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def f64s(self, n):
        v = struct.unpack_from("<%dd" % n, self.d, self.p); self.p += 8 * n; return v

    def obj(self, want=None):
        """-> object or None. Declares classes, allocates slots, dispatches on class name."""
        tag = self.u16()
        if tag == 0:
            return None
        if tag == 0xFFFF:
            self.u16()
            n = self.u16()
            if n > 40:
                raise LegacyError("class name too long at %d" % self.p)
            name = self.d[self.p:self.p + n].decode("ascii"); self.p += n
            cslot = self.slot; self.slot += 1
            self.classes[cslot] = name
        elif tag & 0x8000 and tag != 0x7FFF:
            cslot = tag & 0x7FFF
            if cslot not in self.classes:
                raise LegacyError("class-ref to undeclared slot %d at %d" % (cslot, self.p))
            name = self.classes[cslot]
        elif tag == 0x7FFF:
            raise LegacyError("32-bit tag not supported")
        else:
            if tag not in self.objs:
                raise LegacyError("dangling back-ref %d at %d" % (tag, self.p))
            return self.objs[tag]
        oslot = self.slot; self.slot += 1
        o = self.body(name)
        self.objs[oslot] = o
        return o

    def pre(self):
        if self.u16() != 0:
            raise LegacyError("attribute container not supported at %d" % self.p)
        mask = self.u8()
        for b in range(8):
            if mask >> b & 1:
                self.u8()

    def drawbase(self):
        self.p += 8
        self.u16()   # layer id (inline layer objects unsupported)

    def body(self, name):
        if name == "CVertex":
            self.pre(); self.nverts += 1
            return ("v",) + self.f64s(3)
        if name == "CEdge":
            self.pre(); self.drawbase()
            a = self.obj(); b = self.obj(); c = self.obj()
            if c is not None:
                raise LegacyError("curve edges not supported")
            self.nedges += 1
            return ("e", a, b)
        if name == "CEdgeUse":
            self.pre()
            e = self.obj(); sense = self.u8(); self.u16()
            return ("eu", e, sense)
        if name == "CLoop":
            self.pre(); self.p += 2
            us = []
            while True:
                u = self.obj()
                if u is None:
                    break
                us.append(u)
            return ("l", us)
        if name == "CFace":
            self.pre(); self.drawbase()
            plane = self.f64s(4)
            n = self.u32()
            if n > 10000:
                raise LegacyError("implausible loop count")
            loops = [self.obj() for _ in range(n)]
            self.u16()
            self.nfaces += 1
            return ("f", plane, loops)
        raise LegacyError("unsupported class %s" % name)


def scan_faces(data):
    """Parse the first run of face entities (flat sample models). Returns list of faces: each loop list of xyz in inches."""
    m = re.search(rb"\xff\xff.\x00.\x00CFace", data)
    if not m:
        raise LegacyError("no CFace declaration")
    best = None
    for base in range(1, 400):   # absolute slot base is unknown: take the first that parses
        r = _R(data, m.start()); r.slot = base
        faces = []
        while True:
            try:
                f = r.obj()
            except (LegacyError, IndexError, struct.error):
                break
            if f is None or f[0] != "f":
                break
            faces.append(f)
        if best is None or len(faces) > len(best):
            best = faces
    faces = best
    out = []
    for _, plane, loops in faces:
        ls = []
        for lp in loops:
            pts = []
            for eu in lp[1]:
                _, e, sense = eu
                v = e[1] if sense == 0 else e[2]
                pts.append(v[1:])
            ls.append(pts)
        out.append(ls)
    return out
