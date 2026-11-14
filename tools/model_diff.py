"""Decoded-content diff of two .skp files (independent of GLB export): the oracle a future writer must pass, because
"reads back without error" is not evidence (see docs/FORMAT.md, interior bit flip measurements).
usage: python3 tools/model_diff.py A.skp B.skp [--verbose]
Exit 0 identical decoded content, 1 different, 2 unreadable. Default output is aggregate (per-section counts only, no
names), so it is safe on private files; --verbose also prints the first differing lines."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from skpballet import container, scene  # noqa: E402


def canon(m):
    """Canonical lines 'section|text' for a Model, ordered by ids so file order does not matter."""
    out = ["version|%s" % m.version]
    for i in sorted(m.layers):
        out.append("layer|%s|%r|%d" % (i, m.layers[i], i in m.layers_off))
    for i in sorted(m.materials):
        out.append("material|%s|%r" % (i, sorted(m.materials[i].items(), key=lambda kv: kv[0])))
    defs = [("root", m.root)] + [(str(k), m.defs[k]) for k in sorted(m.defs, key=str)]
    for key, d in defs:
        if d is None:
            continue
        out.append("def|%s|%r|%r|%s" % (key, d.name, d.guid, d.is_group))
        for v in sorted(d.vertices):
            out.append("vertex|%s|%s|%r" % (key, v, tuple(d.vertices[v])))
        for e in sorted(d.edges):
            out.append("edge|%s|%s|%r" % (key, e, tuple(d.edges[e])))
        for f in sorted(d.faces, key=lambda f: str(f.get("id"))):
            out.append("face|%s|%r" % (key, sorted(f.items(), key=lambda kv: kv[0])))
        for n in d.instances:
            out.append("instance|%s|%r" % (key, sorted(n.items(), key=lambda kv: kv[0])))
        for n in d.annotations:
            out.append("annotation|%s|%r" % (key, sorted(n.items(), key=lambda kv: kv[0])))
        for n in d.texts:
            out.append("text|%s|%r" % (key, sorted(n.items(), key=lambda kv: kv[0])))
    return out


def diff(a, b):
    """Returns dict section -> (only_in_a, only_in_b) counts, plus the raw differing lines."""
    ca, cb = canon(a), canon(b)
    from collections import Counter
    na, nb = Counter(ca), Counter(cb)
    oa, ob = na - nb, nb - na
    sec = {}
    for l in oa.elements():
        sec.setdefault(l.split("|", 1)[0], [0, 0])[0] += 1
    for l in ob.elements():
        sec.setdefault(l.split("|", 1)[0], [0, 0])[1] += 1
    return sec, sorted(oa.elements()), sorted(ob.elements())


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    try:
        ma, mb = (scene.load(container.open_skp(p)) for p in args)
    except Exception as e:
        print("unreadable: %s: %s" % (type(e).__name__, e))
        return 2
    sec, la, lb = diff(ma, mb)
    if not sec:
        print("identical decoded content (%d records)" % len(canon(ma)))
        return 0
    for s in sorted(sec):
        print("%s: %d only in A, %d only in B" % (s, *sec[s]))
    if "--verbose" in argv:
        for l in la[:20]:
            print("A", l[:200])
        for l in lb[:20]:
            print("B", l[:200])
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
