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
            if cslot not in self.classes and want:
                self.classes[cslot] = want   # class declared before our start: learn it from the expected context
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

    def utf16(self):
        if self.d[self.p:self.p + 3] != b"\xff\xfe\xff":
            raise LegacyError("string marker expected at %d" % self.p)
        self.p += 3
        n = self.u8()
        if n == 0xFF:
            n = self.u16()
            if n == 0xFFFF:
                n = self.u32()
        t = self.d[self.p:self.p + 2 * n].decode("utf-16-le"); self.p += 2 * n
        return t

    def value(self, t):
        if t == 0x00:
            return None
        if t in (0x04, 0x09):
            return self.u32()
        if t in (0x06, 0x0C):
            return self.f64s(1)[0]
        if t == 0x07:
            return self.u8()
        if t == 0x0A:
            return self.utf16()
        if t == 0x0B:
            return [self.value(self.u8()) for _ in range(self.u32())]
        if t in (0x11, 0x12):
            return self.f64s(3)
        raise LegacyError("attribute value type %#x at %d" % (t, self.p))

    def pre(self):
        a = self.obj("CAttributeContainer")      # attribute container or None
        mask = self.u8()
        for b in range(8):
            if mask >> b & 1:
                self.u8()

    def drawbase(self):
        self.p += 8
        self.u16()   # layer id (inline layer objects unsupported)

    def body(self, name):
        if name == "CArcCurve":
            self.pre(); self.p += 5
            return ("arc",) + self.f64s(14)
        if name == "CAttributeContainer":
            self.pre(); out = []
            while True:
                n = self.obj("CAttributeNamed")
                if n is None:
                    break
                out.append(n)
            return ("attrs", out)
        if name == "CAttributeNamed":
            self.pre(); self.p += 4
            dn = self.utf16(); kv = {}
            while True:
                k = self.utf16()
                if k == "":
                    break
                kv[k] = self.value(self.u8())
            self.u32()   # trailer (ver >= 7)
            return ("attr", dn, kv)
        if name == "CVertex":
            self.pre(); self.nverts += 1
            return ("v",) + self.f64s(3)
        if name == "CEdge":
            self.pre(); self.drawbase()
            a = self.obj(); b = self.obj(); c = self.obj()
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


def scan_faces(data, info=None):
    """Parse the first entity list: the declaration of its first class is preceded by u16, u32, u32 count (verified on
    the public 2017/2020 fixtures), and exactly `count` objects follow. Returns faces (list of loops of xyz inches).
    If `info` (a dict) is given it receives count, parsed, complete."""
    m = min((x for x in (re.search(rb"\xff\xff.\x00.\x00" + c, data) for c in
             (b"CFace", b"CEdge\x00", b"CVertex", b"CLoop")) if x), key=lambda x: x.start(), default=None)
    if not m:
        raise LegacyError("no geometry class declaration")
    count = struct.unpack_from("<I", data, m.start() - 4)[0] if m.start() >= 10 else 0
    if not 0 < count < 5000000:
        count = 1 << 30
    best = None
    for base in range(1, 400):   # absolute slot base is unknown: take the first that parses most objects
        r = _R(data, m.start()); r.slot = base
        objs = []
        while len(objs) < count:
            try:
                objs.append(r.obj())
            except (LegacyError, IndexError, struct.error):
                break
        if best is None or sum(o is not None for o in objs) > sum(o is not None for o in best):
            best = objs
    if info is not None:
        info.update(count=count if count < 1 << 30 else None, parsed=len(best),
                    complete=count < 1 << 30 and len(best) == count and all(o is not None for o in best))
    faces = [f for f in best if f is not None and f[0] == "f"]
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


def load_legacy(skp):
    """LegacySkp -> scene.Model with one root definition (faces only; no groups, materials or layers yet)."""
    from .scene import Model, Definition
    from .container import SkpError
    try:
        inf = {}
        faces = scan_faces(skp.data, inf)
    except LegacyError as e:
        raise SkpError("legacy file: %s" % e)
    m = Model(); m.version = skp.version + " (legacy, experimental: first geometry run only)"
    d = Definition(-1, "root"); m.root = d
    vid = {}
    for fi, loops in enumerate(faces):
        ls = []
        for lp in loops:
            ids = []
            for p in lp:
                ids.append(vid.setdefault(p, len(vid)))
            ls.append(ids)
        d.faces.append(dict(id=fi, loops=ls, mat=None, normal=None))
    d.vertices = {i: p for p, i in vid.items()}
    m.warnings.append("legacy 2013-2020 reader is experimental: only the first entity list is decoded (%s of %s objects%s)"
                      % (inf.get("parsed"), inf.get("count"), "" if inf.get("complete") else ", INCOMPLETE"))
    return m
