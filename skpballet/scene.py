"""Decode model.dat into definitions, geometry and instances (read-only)."""
import re
import struct
import xml.etree.ElementTree as ET
from .tlv import parse_tlv

INCH = 0.0254  # SketchUp stores inches; we export metres


def _id(node):
    """Entity id: tag 0x5dc payload = 'de05' u32len varint."""
    if node is None:
        return None
    p = node.payload
    if len(p) >= 6 and p[0] == 0xDE and p[1] == 0x05:
        ln = struct.unpack_from("<I", p, 2)[0]
        return int.from_bytes(p[6 : 6 + ln], "little")
    return None


def _ent_id(node):
    h = node.first(0x7D0)
    return _id(h.first(0x5DC)) if h else None


def _var(node):
    return int.from_bytes(node.payload, "little") if node is not None else None


class Definition:
    def __init__(self, did, name=""):
        self.id, self.name = did, name
        self.guid = ""
        self.vertices = {}   # id -> (x,y,z) inches
        self.edges = {}      # id -> (v1, v2)
        self.faces = []      # dict(id, loops=[[vid..]], mat, normal)
        self.instances = []  # dict(def_id, matrix(13), name, hidden)
        self.is_group = False
        self.annotations = []  # dict(kind, ...): section planes, guide points, linear dimensions (UNVERIFIED kinds, see FORMAT.md)
        self.texts = []      # dict(text, x, y): screen-text records (tag 0x1398 > 0x55F0), position fields UNVERIFIED


class Model:
    def __init__(self):
        self.version = ""
        self.defs = {}       # id -> Definition
        self.root = None     # Definition (top-level entities)
        self.materials = {}  # id -> dict(name, rgb, alpha)
        self.layers = {}     # id -> name
        self.layers_off = set()  # ids whose flag 0x3C8E is 1 (UNVERIFIED meaning: probably hidden)
        self.warnings = []

    def counts(self):
        ds = list(self.defs.values()) + [self.root]
        return dict(
            definitions=len(self.defs), vertices=sum(len(d.vertices) for d in ds),
            edges=sum(len(d.edges) for d in ds), faces=sum(len(d.faces) for d in ds),
            instances=sum(len(d.instances) for d in ds),
            materials=len(self.materials), layers=len(self.layers))


# child tags of an entity collection (0x1388): read above, or present in every public fixture and carrying no geometry
# as far as known (0x138E 0x139B 0x139F 0x13A0 flags/extents?; 0x1397 grouping of arc edges: both UNVERIFIED)
_KNOWN_ENT_TAGS = {0x1391, 0x1392, 0x1399, 0x1398, 0x7D0, 0x1389, 0x138A, 0x138B, 0x138C, 0x138D, 0x138E, 0x1397, 0x139B, 0x139E, 0x139F, 0x13A0}


def _flat_tlv(b):
    p = 0
    while p + 6 <= len(b):
        t, l = struct.unpack_from("<HI", b, p)
        if p + 6 + l > len(b):
            return
        yield t, b[p + 6:p + 6 + l]
        p += 6 + l


def _texts(payload, d):
    """0x1398 payload = flat TLV of 0x55F0 records: 0x55F1 UTF-8 string, 0x55F2/0x55F3 f64 (screen position?)."""
    for t, rec in _flat_tlv(payload):
        if t != 0x55F0:
            continue
        sub = dict(_flat_tlv(rec))
        s = sub.get(0x55F1)
        if s is None:
            continue
        xy = [struct.unpack("<d", sub[k])[0] if len(sub.get(k, b"")) == 8 else None for k in (0x55F2, 0x55F3)]
        d.texts.append(dict(text=s.decode("utf-8", "replace"), x=xy[0], y=xy[1]))


def _f64(node):
    return list(struct.unpack("<%dd" % (len(node.payload) // 8), node.payload)) if node is not None and len(node.payload) % 8 == 0 else None


def _annotations(c, d):
    """Kinds inferred from payload shape and the layer names of annotation_layers_vff (text / reference / dimension):
    0x1391>0x4269 0x426A = point(3) + unit normal(3) + 2 f64 -> section plane; 0x1392>0x426C 0x426D = point -> guide
    point; 0x1399>0x5BCC 0x5BCD/0x5BCE>0x5208>0x520A = point each -> linear dimension (start, end). All UNVERIFIED."""
    if c.tag == 0x1391:
        for x in c.find(0x4269):
            v = _f64(x.first(0x426A))
            if v and len(v) == 8:
                d.annotations.append(dict(kind="section plane", point=v[:3], normal=v[3:6]))
    elif c.tag == 0x1392:
        for x in c.find(0x426C):
            v = _f64(x.first(0x426D))
            if v and len(v) == 3:
                d.annotations.append(dict(kind="guide point", point=v))
    elif c.tag == 0x1399:
        for x in _flat_tlv(c.payload):
            if x[0] != 0x5BCC:
                continue
            pts = []
            for t, rec in _flat_tlv(x[1]):
                if t in (0x5BCD, 0x5BCE):
                    for t2, r2 in _flat_tlv(rec):
                        for t3, r3 in _flat_tlv(r2) if t2 == 0x5208 else ():
                            if t3 == 0x520A and len(r3) == 24:
                                pts.append(list(struct.unpack("<3d", r3)))
            if len(pts) == 2:
                d.annotations.append(dict(kind="dimension", start=pts[0], end=pts[1]))


def _entities(ent, d, model):
    """ent: a 0x1388 node (entity collection)."""
    for c in ent.children:
        if c.tag == 0x1398:
            _texts(c.payload, d)
        _annotations(c, d)
        if c.tag not in _KNOWN_ENT_TAGS and (c.children or c.payload):
            seen = model.__dict__.setdefault("_unread_tags", set())
            if c.tag not in seen:
                seen.add(c.tag)
                model.warnings.append("entity collection 0x%X is NOT read (annotations or other objects?): its content is not in the model" % c.tag)
        if c.tag == 0x1389:
            for v in c.find(0x9C4):
                co = v.first(0x9C5)
                if co is not None and len(co.payload) == 24:
                    d.vertices[_id(v.first(0x5DC))] = struct.unpack("<3d", co.payload)
        elif c.tag == 0x138A:
            for e in c.find(0xBB8):
                d.edges[_ent_id(e)] = (_var(e.first(0xBB9)), _var(e.first(0xBBA)))
        elif c.tag == 0x138B:
            for f in c.find(0xDAC):
                loops = []
                dae = f.first(0xDAE)
                for lp in (dae.find(0x1194) if dae else []):
                    cl = lp.first(0x1195)
                    vs = []
                    for ce in (cl.find(0xFA0) if cl else []):
                        # payload: a10f len edge | a20f len orient (inline TLV)
                        p = ce.payload
                        l1 = struct.unpack_from("<I", p, 2)[0]
                        eid = int.from_bytes(p[6 : 6 + l1], "little")
                        o = p[6 + l1 + 6] if len(p) > 6 + l1 + 6 else 0
                        e = d.edges.get(eid)
                        if e is None:
                            model.warnings.append("face edge %d missing" % eid)
                            continue
                        vs.append(e[0] if o == 0 else e[1])
                    loops.append(vs)
                nrm = f.first(0xDAD)
                d.faces.append(dict(id=_ent_id(f), loops=loops, mat=_var(f.first(0xDAF)),
                                    normal=nrm.f64s()[:3] if nrm else None))
        elif c.tag == 0x138C or c.tag == 0x138D:
            stack = [c]
            while stack:
                x = stack.pop()
                for k in x.children:
                    if k.tag == 0x1964:
                        m = k.first(0x1966)
                        r = k.first(0x1967)
                        if m is not None and r is not None and len(m.payload) == 104:
                            n = k.first(0x1965)
                            d.instances.append(dict(def_id=_var(r), matrix=m.f64s(), id=_ent_id(k),
                                                    name=n.payload.decode("utf-8", "replace") if n is not None else ""))
                    elif k.children:
                        stack.append(k)


def load(skp):
    # millions of small tree nodes: the cyclic GC dominates the parse time (about 45 percent), so pause it
    import gc
    was = gc.isenabled(); gc.disable()
    try:
        return _load_any(skp)
    finally:
        if was:
            gc.enable()


def _load_any(skp):
    """Decode a model; any structural problem raises SkpError."""
    from .container import SkpError, LegacySkp
    if isinstance(skp, LegacySkp):
        from .legacy import load_legacy
        try:
            return load_legacy(skp)
        except SkpError:
            raise
        except Exception as e:
            raise SkpError("legacy file: %s: %s" % (type(e).__name__, e))
    try:
        return _load(skp)
    except SkpError:
        raise
    except Exception as e:
        raise SkpError("corrupt model data (%s: %s)" % (type(e).__name__, e))


def _load(skp):
    model = Model()
    model.version = skp.version
    for note in getattr(skp, "container_notes", ()):
        model.warnings.append("container: " + note + " (extra or damaged data)")
    md = skp.model_dat
    top = parse_tlv(md)[0]
    if len(md) >= 6 and struct.unpack_from("<I", md, 2)[0] != len(md) - 6:   # holds on all public 2021+ fixtures
        model.warnings.append("model.dat: top record length does not match the stream size (%d bytes after it): extra or damaged data" % (len(md) - 6 - struct.unpack_from("<I", md, 2)[0]))
    xml = {}
    for n in skp.names():
        m = re.match(r"materials/(.+)/material\.xml$", n)
        if m:
            try:
                el = ET.fromstring(skp.read(n)).find("{*}material")
                xml[m.group(1)] = (int(el.get("colorRed")), int(el.get("colorGreen")),
                                   int(el.get("colorBlue")), int(el.get("useTrans", "0")),
                                   int(el.get("trans", "0")))
            except ET.ParseError:
                model.warnings.append("materials: %s is not well-formed XML (extra or damaged data)" % n)
            except Exception:
                pass   # layer material.xml files have no <material> element; not an error
    for lst in top.find(0x1F7):
      for l2 in lst.find(0x30D4):
        for e in l2.find(0x30D5):
          for m in e.find(0x32C8):
            name = (m.first(0x32CC).text() if m.first(0x32CC) else "")
            c = xml.get(name)
            model.materials[_id(m.first(0x5DC))] = dict(
                name=name, rgb=c[:3] if c else (200, 200, 200), alpha=(1 - c[4] / 100) if c and c[3] else 1.0)
    for lst in top.find(0x1F8):
      for l2 in lst.find(0x3A98):
        for e in l2.find(0x3A99):
          for l in e.find(0x3C8C):
            lid = _id(l.first(0x5DC))
            nm = l.first(0x3C8D).text() if l.first(0x3C8D) else ""
            if not nm:   # public fixtures keep the name only in 0x3C8F > 0x32CC as "Layer_<name>" (same as the zip member name)
                for t, rec in _flat_tlv(l.first(0x3C8F).payload if l.first(0x3C8F) else b""):
                    for t2, r2 in (_flat_tlv(rec) if t == 0x32C8 else ()):
                        if t2 == 0x32CC:
                            nm = r2.decode("utf-8", "replace")
                            nm = nm[6:] if nm.startswith("Layer_") else nm
            model.layers[lid] = nm
            fl = l.first(0x3C8E)
            if fl is not None and fl.uint() == 1:
                model.layers_off.add(lid)
    for dl in top.find(0x1F9):
        for x in dl.find(0x1770):
            for y in x.find(0x1771):
                for dn in y.find(0x157C):
                    ent = dn.first(0x1388)
                    if ent is None:
                        continue
                    did = _ent_id(ent)
                    nm = dn.first(0x157E)
                    d = Definition(did, nm.text() if nm else "")
                    g = dn.first(0x157D)
                    d.guid = g.payload.hex() if g else ""
                    gf = dn.first(0x1583)  # 1 for groups, 0 for components (observed on 4 public definitions)
                    d.is_group = bool(gf is not None and gf.uint())
                    _entities(ent, d, model)
                    model.defs[did] = d
    model.root = Definition(0, "<model>")
    for r6 in top.find(0x1F6):
        for r in r6.find(0x1388):
            _entities(r, model.root, model)
    return model
