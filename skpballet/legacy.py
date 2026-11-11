"""Experimental reader for SketchUp 2013-2020 (MFC CArchive) geometry. Clean-room from observation of public samples
plus format notes in docs/FORMAT.md. Handles only the geometry entities of the first entity list (CFace, CLoop,
CEdgeUse, CEdge, CVertex); everything else raises LegacyError. Slot numbers are relative to the first class
declaration of the list (absolute base unknown), so references to classes declared earlier are not supported."""
import re
import struct


class LegacyError(Exception):
    pass


class _R:
    def __init__(self, d, pos, nomask=False):
        self.d, self.p = d, pos
        self.nomask = nomask   # SketchUp 13: the attribute-container ref is not followed by a flag-mask byte
        self.classes = {}   # slot -> name
        self.objs = {}      # slot -> object
        self.slot = 1
        self.nverts = self.nedges = self.nfaces = 0
        self.inst_tail = False   # instances are followed by one extra u16 (see FORMAT.md, instance tail)

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
        self.objs[oslot] = ("pending", name)   # back-refs to an object still being read (edge -> owning curve)
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
        if self.nomask:
            return
        mask = self.u8()
        for b in range(8):
            if mask >> b & 1:
                self.u8()

    def drawbase(self):
        """-> first u16 of the 8 draw-base bytes: for faces the archive slot of the front material (0 = none; edges
        always 0). The following u16 is a layer reference (inline layer objects unsupported)."""
        m = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 8
        self.last_layer = self.u16()
        return m

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
        if name in ("CComponentInstance", "CGroup"):
            self.pre(); self.drawbase(); dslot = self.u16(); v = self.f64s(13); nm = self.utf16(); self.p += 16
            if self.inst_tail:
                self.u16()
            return ("inst", nm, dslot, v[:9], v[9:12], v[12], name == "CGroup")
        if name == "CFace":
            self.pre(); matslot = self.drawbase(); layer = self.last_layer
            plane = self.f64s(4)
            n = self.u32()
            if n > 10000:
                raise LegacyError("implausible loop count")
            loops = [self.obj() for _ in range(n)]
            self.u16()
            self.nfaces += 1
            return ("f", plane, loops, matslot, layer)
        if name == "CFaceTextureCoords":
            self.p += 215   # observed fixed length (edge_flags fixture): pre + 6 rows of 4 f64 + 17 unknown bytes
            return ("ftc",)
        if name in ("CConstructionPoint", "CConstructionLine"):
            # observed fixed lengths after pre + drawbase (nested.skp only): point 49, line 68 bytes; not decoded
            self.pre(); self.drawbase(); self.p += 49 if name == "CConstructionPoint" else 68
            return ("cpt",) if name == "CConstructionPoint" else ("cline",)
        if name == "CCurve":
            self.pre(); self.p += 1
            n = self.u32()
            if n > 100000:
                raise LegacyError("implausible curve edge count")
            return ("curve", [self.obj() for _ in range(n)])
        raise LegacyError("unsupported class %s" % name)


def _major(version):
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        return 99


def _last(objs):
    """Index after the last non-None object: trailing None entries are list terminators (edge_flags: 2)."""
    n = len(objs)
    while n and objs[n - 1] is None:
        n -= 1
    return n


def scan_faces(data, info=None, version=""):
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
        r = _R(data, m.start(), nomask=_major(version) <= 13); r.slot = base
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
                    complete=count < 1 << 30 and len(best) == count and all(o is not None for o in best[:_last(best)]))
    faces = [f for f in best if f is not None and f[0] == "f"]
    out = []
    fm = []; fl = []
    for _, plane, loops, matslot, layer in faces:
        fm.append(matslot); fl.append(layer)
        ls = []
        for lp in loops:
            pts = []
            for eu in lp[1]:
                _, e, sense = eu
                v = e[1] if sense == 0 else e[2]
                pts.append(v[1:])
            ls.append(pts)
        out.append(ls)
    if info is not None:
        info["face_matslots"] = fm; info["face_layerrefs"] = fl
        try:
            info["edges"] = _list_geometry(best)[2]
        except (TypeError, IndexError, ValueError):
            info["edges"] = []
    return out


def _refs_ok(objs):
    """Back-references must land on the right kinds (edge use -> edge -> vertices): a wrong slot offset aliases them."""
    for o in objs:
        if o is None:
            continue
        if o[0] == "f":
            for lp in o[2]:
                for eu in (lp[1] if lp and lp[0] == "l" else ()):
                    e = eu[1]
                    if not (isinstance(e, tuple) and e[0] == "e" and isinstance(e[1], tuple) and e[1][0] == "v"
                            and isinstance(e[2], tuple) and e[2][0] == "v"):
                        return False
    return True


def scan_lists(data, version="", limit=200, inst_tail=False, ends=None):
    """All entity lists of a legacy file in stream order: [(objs, slot_base)]. The first list is found as in scan_faces; each
    next one by scanning after the end of the previous list for a u32 count followed by an object tag such that exactly
    `count` objects parse (slot counter offset 0..9 tried; offset 3 is typical: a definition trailer holds a CThumbnail
    class + object). Definitions are written leaf first, the model root last (verified on components.skp: 3 instances,
    4 edges, 1 face). Stops when no further list parses; objects of unsupported classes end a list early."""
    m = min((x for x in (re.search(rb"\xff\xff.\x00.\x00" + c, data) for c in
             (b"CFace", b"CEdge\x00", b"CVertex", b"CLoop")) if x), key=lambda x: x.start(), default=None)
    if not m or m.start() < 10:
        return []
    count = struct.unpack_from("<I", data, m.start() - 4)[0]
    if not 0 < count < 5000000:
        return []
    r = None
    for base in range(1, 400):
        r = _R(data, m.start(), nomask=_major(version) <= 13); r.slot = base; r.inst_tail = inst_tail
        try:
            objs = [r.obj() for _ in range(count)]
        except (LegacyError, IndexError, struct.error):
            continue
        break
    else:
        return []
    out = [(objs, base)]
    if ends is not None:
        ends.append(r.p)
    while len(out) < limit:
        end, found = r.p, None
        for q in range(end + 4, min(len(data) - 2, end + 4000)):
            n = struct.unpack_from("<I", data, q - 4)[0]
            tag = struct.unpack_from("<H", data, q)[0]
            if not 1 <= n <= 100000 or not (tag == 0xFFFF or (tag & 0x8000 and tag != 0x7FFF)):
                continue
            for off in range(0, 10):
                r2 = _R(data, q, nomask=r.nomask)
                r2.inst_tail = inst_tail; r2.classes = dict(r.classes); r2.objs = dict(r.objs); r2.slot = r.slot + off
                try:
                    objs = [r2.obj() for _ in range(n)]
                except (LegacyError, IndexError, struct.error):
                    continue
                if sum(o is not None for o in objs) >= n - 2 and any(o is not None for o in objs) and _refs_ok(objs):
                    found = (objs, r2); break
            if found:
                break
        if not found:
            break
        out.append((found[0], r.slot)); r = found[1]
        if ends is not None:
            ends.append(r.p)
    return out


def scan_materials(data, info=None):
    """Materials of the legacy material list: [(name, (r, g, b), alpha 0..1)]. Layout seen on the public fixtures:
    object preamble (attr ref 00 00, mask 01 + id byte), UTF-16 name, u16 0, RGBA bytes, UTF-16 texture path (empty
    here), 17 bytes (14 zeros, f64-like 1.0 tail, u8), next object is a class-ref to CMaterial. Returns [] when unsure; face to
    material assignment is NOT decoded."""
    m = re.search(rb"\xff\xff(.)\x00\x09\x00CMaterial", data)
    if not m:
        return []
    r = _R(data, m.end())
    out = []
    if info is not None:
        info["base_slot"] = 10   # slot of the first material object (class slot 9 on every public fixture)
    try:
        while True:
            r.p += 2   # attribute ref (None)
            if r.u8() & 1:
                r.u8()
            name = r.utf16()
            tex = None
            if r.u16() == 1:   # textured: u32 1, embedded CDib (decl or class-ref), u32 kind, u32 n + PNG bytes, 2 f64 scale, path
                r.u16()
                t = r.u16()
                if t == 0xFFFF:
                    r.u16(); ln = r.u16(); r.p += ln   # class declaration: schema, name length, name
                r.u32(); n = r.u32()
                if n > len(data) - r.p:
                    raise LegacyError("texture size")
                tex = dict(png=bytes(data[r.p:r.p + n]), scale=None); r.p += n
                tex["scale"] = r.f64s(2); tex["path"] = r.utf16()
                rr, gg, bb, aa = (r.u8() for _ in range(4)); r.p += 5
                aa = 255
            else:
                rr, gg, bb, aa = (r.u8() for _ in range(4))
            r.utf16(); r.p += 17
            out.append((name, (rr, gg, bb), aa / 255.0) + ((tex,) if tex else ()))
            if len(out) > 5000 or r.p + 2 > len(data) or not (struct.unpack_from("<H", data, r.p)[0] & 0x8000) or struct.unpack_from("<H", data, r.p)[0] == 0xFFFF:
                break
            if info is not None and len(out) == 1:
                info["base_slot"] = (struct.unpack_from("<H", data, r.p)[0] & 0x7FFF) + 1   # class-ref slot + 1
            r.p += 2
    except (LegacyError, IndexError, struct.error, UnicodeDecodeError):
        pass
    return out


def scan_layers(data):
    """Layers of a legacy file: [(name, flag)] from the layer list after the class table. Layout seen on the public
    fixtures: UTF-16 name (ff fe ff len ...), flag byte, 00 00 01 id, then the attribute dictionary 'Layer_<name>'.
    The flag is 1 for 'Hidden' (layers_extra) and 'Walls' (materials_and_layers): meaning UNVERIFIED (probably hidden).
    Returns [] when unsure."""
    m = re.search("End-Of-Version-Map".encode("utf-16le"), data)
    if not m:
        return []
    out = []
    for mm in re.finditer(rb"\xff\xfe\xff(.)((?:[^\x00]\x00)+)(.)\x00\x00(?:\x01.|\x00)?(?=\xff\xfe\xff)", data[m.end():], re.S):
        try:
            nm = mm.group(2).decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if len(nm) != mm.group(1)[0] or nm.startswith("Layer_"):
            continue
        if all(nm != o[0] for o in out):
            out.append((nm, mm.group(3)[0]))
    return out


def scan_instances(data):
    """Candidate component instances / groups: [(name, rot3x3 row-major, (tx, ty, tz) inches, scale)]. Record (verified on
    components.skp: translation 100 identity; 200 with a 90 degree rotation; 300 with 3x3 = 2*I): 13 f64 (3x3,
    translation, scale) directly followed by the UTF-16 instance name. The definition link is NOT decoded, so these are
    a listing only. Candidates are filtered by finite, plausible numbers (scale in 1e-6..1e6)."""
    out = []
    p = data.find(b"\xff\xfe\xff")
    while p >= 0:
        q, p = p, data.find(b"\xff\xfe\xff", p + 1)
        if q < 104 or q + 4 > len(data):
            continue
        n = data[q + 3]
        raw = data[q + 4:q + 4 + 2 * n]
        if len(raw) != 2 * n or any(raw[i] == 0 for i in range(0, len(raw), 2)) or any(raw[i] for i in range(1, len(raw), 2)):
            continue
        try:
            v = struct.unpack_from("<13d", data, q - 104)
            nm = raw.decode("utf-16le")
        except (struct.error, UnicodeDecodeError):
            continue
        if not all(x == x and abs(x) < 1e9 for x in v) or not 1e-6 < abs(v[12]) < 1e6:
            continue
        r = v[:9]
        if all(abs(x) < 1e-9 for x in r) or any(abs(x) > 1e6 for x in r):
            continue
        if any(abs(x) > 0 and abs(x) < 1e-100 for x in v):   # denormal-ish garbage
            continue
        out.append((nm, r, v[9:12], v[12]))
    return out


def _newell(pts):
    """Face normal from the outer loop (Newell); None when degenerate so callers keep their default."""
    x = y = z = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        x += (p[1] - q[1]) * (p[2] + q[2]); y += (p[2] - q[2]) * (p[0] + q[0]); z += (p[0] - q[0]) * (p[1] + q[1])
    return (x, y, z) if (x * x + y * y + z * z) > 1e-18 else None


def load_legacy(skp):
    """LegacySkp -> scene.Model with one root definition (faces only; no groups, materials or layers yet)."""
    from .scene import Model, Definition
    from .container import SkpError
    try:
        inf = {}
        faces = scan_faces(skp.data, inf, skp.version)
    except LegacyError as e:
        if "no geometry class" not in str(e):
            raise SkpError("legacy file: %s" % e)
        faces = []   # a model with no geometry at all (e.g. only layers/materials): empty scene, not an error
        inf = dict(count=0, parsed=0, complete=True)
    m = Model(); m.version = skp.version + " (legacy, experimental: first geometry run only)"
    d = Definition(-1, "root"); m.root = d
    mi = {"base_slot": 10}
    mats = scan_materials(skp.data, mi)
    for i, mt in enumerate(mats):
        nm, rgb, al = mt[:3]
        m.materials[i + 1] = dict(name=nm, rgb=rgb, alpha=al, **({"texture": mt[3]} if len(mt) > 3 else {}))
    for i, (nm, fl) in enumerate(scan_layers(skp.data)):
        m.layers[i + 1] = nm
        if fl == 1:
            m.layers_off.add(i + 1)
    tree = legacy_tree(skp.data, skp.version)
    if tree is not None:
        def build(did, name, faces, fslots, edges=()):
            dd = Definition(did, name); vid = {}
            for ei, (pa, pb) in enumerate(edges):
                dd.edges[ei] = (vid.setdefault(pa, len(vid)), vid.setdefault(pb, len(vid)))
            for fi, loops in enumerate(faces):
                ls = [[vid.setdefault(p, len(vid)) for p in lp] for lp in loops]
                k = (fslots[fi] - mi["base_slot"] + 1) if fi < len(fslots) else 0
                dd.faces.append(dict(id=fi, loops=ls, mat=k if 1 <= k <= len(mats) else None, normal=_newell(loops[0])))
            dd.vertices = {i: p for p, i in vid.items()}
            return dd
        for k, (faces, fslots, ins) in enumerate(tree[0]):
            m.defs[k] = build(k, tree[2][k] or "definition %d" % (k + 1), faces, fslots, tree[4][k])
            m.defs[k].is_group = k in tree[3]
            m.defs[k].instances = [dict(def_id=i, matrix=list(v), name=nm, id=None) for i, nm, v in ins]
        faces, fslots, ins = tree[1]
        m.root = build(-1, "root", faces, fslots, tree[4][-1])
        m.root.instances = [dict(def_id=i, matrix=list(v), name=nm, id=None) for i, nm, v in ins]
        m.version = skp.version + " (legacy, experimental: definition tree)"
        m.warnings.append("legacy definition tree: instance-to-definition link inferred from slot order (experimental)")
        return m
    # face front material = archive slot of the material object (observed: faces 10, 11 -> Red, Blue); unknown slots stay unassigned
    slots = inf.get("face_matslots") or []
    vid = {}
    for fi, loops in enumerate(faces):
        ls = []
        for lp in loops:
            ids = []
            for p in lp:
                ids.append(vid.setdefault(p, len(vid)))
            ls.append(ids)
        mi_ = (slots[fi] - mi["base_slot"] + 1) if fi < len(slots) else 0
        d.faces.append(dict(id=fi, loops=ls, mat=mi_ if 1 <= mi_ <= len(mats) else None, normal=_newell(faces[fi][0])))
    for ei, (pa, pb) in enumerate(inf.get("edges") or []):
        d.edges[ei] = (vid.setdefault(pa, len(vid)), vid.setdefault(pb, len(vid)))
    d.vertices = {i: p for p, i in vid.items()}
    if b"CComponentInstance" in skp.data or b"CGroup" in skp.data:
        m.warnings.append("legacy file has components/groups but their lists do not fit the strict definition-tree rules: instances are NOT placed")
    m.warnings.append("legacy 2013-2020 reader is experimental: only the first entity list is decoded (%s of %s objects%s)"
                      % (inf.get("parsed"), inf.get("count"), "" if inf.get("complete") else ", INCOMPLETE"))
    return m


def _list_geometry(objs):
    """One entity list -> (faces as loops of xyz, material slots, edges as ((x,y,z),(x,y,z)) unique by object)."""
    faces, slots, edges, seen = [], [], [], set()

    def add(e):
        if id(e) not in seen and isinstance(e, tuple) and e[0] == "e":
            seen.add(id(e)); edges.append((e[1][1:], e[2][1:]))
    for o in objs:
        if o is None:
            continue
        if o[0] == "e":
            add(o)
        if o[0] != "f":
            continue
        ls = []
        for lp in o[2]:
            for _, e, sense in lp[1]:
                add(e)
            ls.append([(e[1] if sense == 0 else e[2])[1:] for _, e, sense in lp[1]])
        faces.append(ls); slots.append(o[3])
    return faces, slots, edges


def legacy_tree(data, version=""):
    """Experimental definition tree: -> (defs, root) or None. defs = [(faces, matslots, instances)] in stream order and
    root likewise, where instances = [(def_index, name, 13 f64)]. Accepted only if the lists form a consistent tree:
    N non-root lists, exactly N distinct instance definition refs, and the k-th smallest ref lies within 4 slots of the
    k-th list base (observed ref - base in -3..+3 on 10 public fixtures, see FORMAT.md). Anything else -> None."""
    try:
        ends = []
        lists = scan_lists(data, version, ends=ends)
    except (LegacyError, IndexError, struct.error):
        return None
    if len(lists) < 2:
        return None
    refs = sorted({o[2] for objs, _ in lists for o in objs if o and o[0] == "inst"})
    if len(refs) != len(lists) - 1 or any(abs(r - lists[k][1]) > 4 for k, r in enumerate(refs)):
        return None
    if any(lists[k][1] >= lists[k + 1][1] for k in range(len(lists) - 1)):
        return None
    out = []
    for objs, _ in lists:
        try:
            faces, slots, edges = _list_geometry(objs)
        except (TypeError, IndexError, ValueError):
            return None
        ins = [(refs.index(o[2]), o[1], o[3] + o[4] + (o[5],), o[6]) for o in objs if o and o[0] == "inst"]
        out.append((faces, slots, ins, edges))
    for k, (_, _, ins, _) in enumerate(out[:-1]):
        if any(i >= k for i, _, _, _ in ins):   # leaf first: an instance may only use earlier definitions
            return None
    return [(f, sl, [x[:3] for x in i]) for f, sl, i, _ in out[:-1]], (out[-1][0], out[-1][1], [x[:3] for x in out[-1][2]]), \
        [_trailer_names(data, e)[0] for e in ends[:-1]], {i for _, _, ins, _ in out for i, _, _, g in ins if g}, [x[3] for x in out]


def _trailer_names(data, pos):
    """First two UTF-16 strings within 60 bytes after a list end: (name, description) of the definition, else ("", "")."""
    out = []
    p = pos
    while p < min(len(data) - 4, pos + 60) and len(out) < 2:
        if data[p:p + 3] == b"\xff\xfe\xff":
            n = data[p + 3]
            raw = data[p + 4:p + 4 + 2 * n]
            if n < 0xFF and len(raw) == 2 * n:
                try:
                    out.append(raw.decode("utf-16-le")); p += 4 + 2 * n; continue
                except UnicodeDecodeError:
                    break
        p += 1
    return tuple(out + [""] * (2 - len(out)))
