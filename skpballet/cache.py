"""Write an rvt-ballet style cache folder (model.glb with per-vertex _EIDX, meta.json, materials.json) from a .skp,
so the rvt-ballet front-end (`rvt-ballet serve DIR`) can show it. Pure Python, read-only on the .skp.
One element per top-level instance (whole subtree) plus one for loose top-level geometry."""
import json
import os
import struct

from . import mesh
from .mesh import INCH, IDENT, _mul, _compose, _flips, _lin


def _elements(model):
    """-> list of (name, cls, cat, [(definition, matrix)] to walk)."""
    els = []
    if model.root.faces or model.root.edges:
        els.append(("Model", "SkpLoose", "Model", model.root, IDENT, False))
    for inst in model.root.instances:
        sub = model.defs.get(inst["def_id"])
        if sub is not None:
            w = mesh._degenerate(inst["matrix"])
            if w and w not in model.warnings:
                model.warnings.append(w)
            kind = "Group" if sub.is_group else "Component"
            els.append((inst.get("name") or sub.name or kind, "Skp" + kind, kind, sub, _compose(IDENT, inst["matrix"]), True))
    return els


def build(model, max_depth=24, edges=False):
    """-> (elements, batches). batches: dict key -> dict(kind, mat, pos, eidx, idx, ranges)"""
    mesh.note_unexported(model)
    batches = {}
    elements = []

    def batch(kind, mat):
        return batches.setdefault((kind, mat), dict(kind=kind, mat=mat, pos=[], eidx=[], idx=[], ranges=[], nv=0, nt=0))

    cache = {}
    nodes = [0]
    tot = [0]   # triangles emitted so far
    for ei, (name, cls, cat, d0, m0, sub_only) in enumerate(_elements(model)):
        path = set()
        def walk(d, m, depth, top):
            nodes[0] += 1
            if nodes[0] > mesh.MAX_PLACEMENTS:
                mesh._budget_warning(model, mesh.MAX_PLACEMENTS)
                return
            if depth > max_depth:
                return
            if tot[0] > mesh.MAX_TRIS:   # same 5M triangle cap as mesh.flatten: bounded memory
                msg = "triangle limit (%d) reached: the rest is NOT placed" % mesh.MAX_TRIS
                if msg not in model.warnings:
                    model.warnings.append(msg)
                return
            ck = -1 if d.id == -1 else id(d)   # identity key (root id 0 vs a real definition id 0); -1 is the per-element loose-geometry wrapper
            if ck not in cache:
                cache[ck] = mesh.definition_tris(d, model.warnings)
            flip = _flips(m)
            for mat, tris in cache[ck].items():
                b = batch("tri", mat if mat in model.materials else None)
                start = b["nt"]
                for t in tris:
                    t = t[::-1] if flip else t
                    for p in t:
                        x, y, z = _mul(m, p)
                        b["pos"].extend((x * INCH, z * INCH, -y * INCH))
                        b["eidx"].append(float(ei))
                    b["idx"].extend((b["nv"], b["nv"] + 1, b["nv"] + 2))
                    b["nv"] += 3
                    b["nt"] += 1
                    tot[0] += 1
                if b["nt"] > start:
                    b["ranges"].extend((ei, start, b["nt"] - start))
            segs = [(d.vertices[a], d.vertices[c]) for a, c in d.edges.values() if a in d.vertices and c in d.vertices]
            if segs and edges:
                b = batch("line", None); start = b["nt"]
                for pa, pb in segs:
                    for p in (pa, pb):
                        x, y, z = _mul(m, p)
                        b["pos"].extend((x * INCH, z * INCH, -y * INCH)); b["eidx"].append(float(ei))
                    b["idx"].extend((b["nv"], b["nv"] + 1)); b["nv"] += 2; b["nt"] += 1
                b["ranges"].extend((ei, start, b["nt"] - start))
            path.add(id(d))
            for inst in d.instances:
                s = model.defs.get(inst["def_id"])
                if s is None:
                    continue
                if id(s) in path:   # a definition containing itself: corrupt file, do not expand it
                    w = "instance cycle: a definition contains itself (corrupt file); the cyclic instance is NOT placed"
                    if w not in model.warnings:
                        model.warnings.append(w)
                    continue
                w = mesh._degenerate(inst["matrix"])
                if w and w not in model.warnings:
                    model.warnings.append(w)
                walk(s, _compose(m, inst["matrix"]), depth + 1, False)
            path.discard(id(d))
        if sub_only:
            walk(d0, m0, 0, True)
        else:      # loose geometry only, not the instances (they are their own elements)
            only = type("L", (), {})()
            only.id = -1; only.faces = d0.faces; only.edges = d0.edges; only.vertices = d0.vertices; only.instances = []
            cache.pop(-1, None)
            walk(only, m0, 0, True)
        elements.append([ei + 1, cls, cat, name, "", "", "mesh", False, "", ""])
    return elements, batches


def write_cache(model, outdir, name="model.skp", edges=False, strict=False):
    nw = len(model.warnings)
    elements, batches = build(model, edges=edges)
    if strict and mesh._truncated(model, nw):
        raise mesh.StrictTruncation("--strict: export truncated, nothing written: " + mesh._truncated(model, nw)[0])
    os.makedirs(outdir, exist_ok=True)
    mats = [dict(name="default", rgb=[200, 200, 200], alpha=1.0, tex_class="none")]
    midx = {None: 0}
    for k, mt in model.materials.items():
        midx[k] = len(mats)
        _rgb, _a = mesh.sane_color(mt["rgb"], mt["alpha"])
        mats.append(dict(name=mt["name"], rgb=_rgb, alpha=_a, tex_class="none"))
    bin_, views, accs, meshes, matsj, nodes, bmeta = bytearray(), [], [], [], [], [], []
    lo, hi = [1e30] * 3, [-1e30] * 3

    def add(fmt, vals, target):
        off = len(bin_)
        if fmt == "f":
            mesh._check_coords(vals)   # NaN/inf/absurd floats: refuse (ValueError) instead of an OverflowError traceback or a poisoned cache
        bin_.extend(struct.pack("<%d%s" % (len(vals), fmt), *vals))
        bin_.extend(b"\0" * (-len(bin_) % 4))
        views.append(dict(buffer=0, byteOffset=off, byteLength=struct.calcsize("<" + fmt) * len(vals), target=target))
        return len(views) - 1
    for (kind, mat), b in sorted(batches.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if not b["idx"]:
            continue
        pos = b["pos"]
        mesh._check_coords(pos)   # before packing: absurd values must raise ValueError, not OverflowError
        _p32 = struct.unpack("<%df" % len(pos), struct.pack("<%df" % len(pos), *pos))   # min/max of the stored float32 values
        mn = [min(_p32[i::3]) for i in range(3)]; mx = [max(_p32[i::3]) for i in range(3)]
        lo = [min(a, c) for a, c in zip(lo, mn)]; hi = [max(a, c) for a, c in zip(hi, mx)]
        mt = mats[midx.get(mat, 0)] if kind == "tri" else dict(name="edges", rgb=[13, 13, 13], alpha=1.0)
        label = mt["name"] + ("" if kind == "tri" else " (lines)")
        a_pos = len(accs); accs.append(dict(bufferView=add("f", pos, 34962), componentType=5126, count=len(pos) // 3, type="VEC3", min=mn, max=mx))
        a_ei = len(accs); accs.append(dict(bufferView=add("f", b["eidx"], 34962), componentType=5126, count=len(b["eidx"]), type="SCALAR"))
        a_ix = len(accs); accs.append(dict(bufferView=add("I", b["idx"], 34963), componentType=5125, count=len(b["idx"]), type="SCALAR"))
        a = mt["alpha"]
        matsj.append(dict(name=label, pbrMetallicRoughness=dict(baseColorFactor=[_lin(c) for c in mt["rgb"]] + [a], metallicFactor=0.0, roughnessFactor=0.85),
                          doubleSided=True, **({"alphaMode": "BLEND"} if a < 1 else {})))
        bi = len(meshes)
        meshes.append(dict(name=label, primitives=[dict(attributes=dict(POSITION=a_pos, _EIDX=a_ei), indices=a_ix, material=len(matsj) - 1, mode=4 if kind == "tri" else 1)], extras=dict(batch=bi)))
        nodes.append(dict(mesh=bi, name=label, extras=dict(batch=bi)))
        bmeta.append(dict(cat=label, kind=kind if kind == "tri" else "line", color="#%02x%02x%02x" % tuple(mt["rgb"]), alpha=a, ranges=b["ranges"], tris=b["nt"]))
    js = dict(asset=dict(version="2.0", generator="skp-ballet"), scene=0, scenes=[dict(nodes=list(range(len(nodes))))], nodes=nodes,
              meshes=meshes, materials=matsj, accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    jb = json.dumps(js, separators=(",", ":")).encode(); jb += b" " * (-len(jb) % 4)
    with mesh.atomic_open(os.path.join(outdir, "model.glb"), "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(jb) + 8 + len(bin_)))
        f.write(struct.pack("<I4s", len(jb), b"JSON") + jb)
        f.write(struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_))
    # meta.json bbox is Revit style: Z-up metres; glTF is Y-up (x, z, -y)
    bb = [[lo[0], -hi[2], lo[1]], [hi[0], -lo[2], hi[1]]] if batches and lo[0] < 1e29 else [[0, 0, 0], [0, 0, 0]]
    meta = dict(file=name, levels=[], grids=[], rooms=[], views=[], sheets=[], fidLabels={"mesh": "triangle mesh from the SketchUp file"}, phases=[],
                defaultHidden=[], stamps={"reader": "skp-ballet", "viewer": "skp-ballet"}, phase="done", batches=bmeta, bbox=bb,
                coverage={}, coverageByClass={}, bboxAgreement={}, elements=elements, source="skp", warnings=list(model.warnings))
    with mesh.atomic_open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, separators=(",", ":"))
    with mesh.atomic_open(os.path.join(outdir, "materials.json"), "w", encoding="utf-8") as f:
        json.dump(dict(materials=mats, textureClasses={}), f, separators=(",", ":"))
    return dict(elements=len(elements), batches=len(bmeta), triangles=sum(b["tris"] for b in bmeta if b["kind"] == "tri"))
