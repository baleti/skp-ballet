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


class Model:
    def __init__(self):
        self.version = ""
        self.defs = {}       # id -> Definition
        self.root = None     # Definition (top-level entities)
        self.materials = {}  # id -> dict(name, rgb, alpha)
        self.layers = {}     # id -> name
        self.warnings = []

    def counts(self):
        ds = list(self.defs.values()) + [self.root]
        return dict(
            definitions=len(self.defs), vertices=sum(len(d.vertices) for d in ds),
            edges=sum(len(d.edges) for d in ds), faces=sum(len(d.faces) for d in ds),
            instances=sum(len(d.instances) for d in ds),
            materials=len(self.materials), layers=len(self.layers))


def _entities(ent, d, model):
    """ent: a 0x1388 node (entity collection)."""
    for c in ent.children:
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
                            d.instances.append(dict(def_id=_var(r), matrix=m.f64s(), id=_ent_id(k)))
                    elif k.children:
                        stack.append(k)


def load(skp):
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
    top = parse_tlv(skp.model_dat)[0]
    xml = {}
    for n in skp.names():
        m = re.match(r"materials/(.+)/material\.xml$", n)
        if m:
            try:
                el = ET.fromstring(skp.read(n)).find("{*}material")
                xml[m.group(1)] = (int(el.get("colorRed")), int(el.get("colorGreen")),
                                   int(el.get("colorBlue")), int(el.get("useTrans", "0")),
                                   int(el.get("trans", "0")))
            except Exception:
                pass
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
            model.layers[_id(l.first(0x5DC))] = l.first(0x3C8D).text() if l.first(0x3C8D) else ""
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
