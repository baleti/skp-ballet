"""skp-ballet FILE.skp            print info and open the viewer
skp-ballet info [--json] FILE  print contents only (bbox in metres, Y-up)
skp-ballet convert FILE [OUT]  write a .glb
skp-ballet cache FILE DIR      write an rvt-ballet cache folder (view with: rvt-ballet serve DIR)"""
import argparse
import functools
import json
import http.server
import os
import sys
import tempfile
import threading
import webbrowser

from . import container, scene, mesh


def bbox(m):
    """Bounding box [min, max] in metres (Y-up) of the instance-expanded geometry, or None."""
    buf = []
    res = mesh.flatten(m, lines=buf)
    pts = [v for b in res.values() for v in b] + buf
    if not pts:
        return None
    xs, ys, zs = pts[0::3], pts[1::3], pts[2::3]
    return [[min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]]


def info_json(path):
    m = scene.load(container.open_skp(path))
    out = dict(file=os.path.basename(path), version=m.version, counts=m.counts(),
               layer_names=sorted(m.layers.values()),
               layers_flagged_off=sorted(m.layers[i] for i in m.layers_off),  # unverified: flag 0x3C8E==1
               groups=sum(1 for d in m.defs.values() if d.is_group), components=sum(1 for d in m.defs.values() if not d.is_group), material_names=sorted(x["name"] for x in m.materials.values()),
               bbox_m=bbox(m), warnings=m.warnings)
    print(json.dumps(out, indent=2))
    return m


def info(path):
    skp = container.open_skp(path)
    m = scene.load(skp)
    print("file:      %s" % os.path.basename(path))
    print("version:   SketchUp %s" % m.version)
    for k, v in m.counts().items():
        print("%-10s %d" % (k + ":", v))
    top = sorted(m.defs.values(), key=lambda d: -len(d.faces))[:10]
    for d in top:
        print("  %-9s %-30s faces=%d edges=%d instances=%d" % ("group" if d.is_group else "component", d.name or "<unnamed %s>" % d.id, len(d.faces), len(d.edges), len(d.instances)))
    print("layers:    " + ", ".join(sorted(m.layers.values())[:20]))
    print("materials: " + ", ".join(sorted(x["name"] for x in m.materials.values())[:20]))
    for w in m.warnings[:5]:
        print("warning:", w)
    return m


def _find_web():
    for c in (os.environ.get("SKP_BALLET_VENDOR"),
              os.path.join(os.path.dirname(__file__), "..", "..", "rvt-ballet", "web", "vendor"),
              os.path.join(os.path.dirname(__file__), "vendor")):
        if c and os.path.isdir(os.path.join(c, "three")):
            return os.path.abspath(c)
    return None


def safe_join(root, urlpath):
    """Map a URL path under root; anything resolving outside root (.., backslashes, absolute) -> a path that does not exist."""
    from urllib.parse import unquote
    rel = unquote(urlpath)
    real_root = os.path.realpath(root)
    if os.path.splitdrive(rel)[0] or "\\" in rel or "\0" in rel:
        return os.path.join(real_root, "__invalid__")
    cand = os.path.realpath(os.path.join(real_root, rel.lstrip("/")))
    try:
        inside = os.path.commonpath([real_root, cand]) == real_root
    except ValueError:
        inside = False
    return cand if inside else os.path.join(real_root, "__invalid__")


def serve(glb, port=0, open_browser=True):
    vendor = _find_web()
    if not vendor:
        print("three.js not found: set SKP_BALLET_VENDOR to a dir holding three/ (see README)", file=sys.stderr)
        return 1
    here = os.path.join(os.path.dirname(__file__), "web")

    class H(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, p):
            p = p.split("?")[0]
            if p == "/model.glb":
                return glb
            if p.startswith("/vendor/"):
                return safe_join(vendor, p[len("/vendor/"):])
            return os.path.join(here, "index.html")

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    print("viewer:", url, "(Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd = a[0] if a[0] in ("info", "convert", "cache") else "open"
    rest = a[1:] if cmd != "open" or a[0] == "open" else a
    if a[0] == "open":
        rest = a[1:]
    ap = argparse.ArgumentParser(prog="skp-ballet " + cmd)
    ap.add_argument("file")
    if cmd == "info":
        ap.add_argument("--json", action="store_true")
        ap.add_argument("--layers", action="store_true", help="one line per layer: id, name, [off] if flag 0x3C8E is 1 (unverified)")
        ap.add_argument("--bbox", action="store_true", help="bounding box in metres, Y-up: minx miny minz maxx maxy maxz")
    if cmd == "convert":
        ap.add_argument("out", nargs="?")
    if cmd == "cache":
        ap.add_argument("outdir")
    if cmd == "open":
        ap.add_argument("--port", type=int, default=0)
        ap.add_argument("--no-browser", action="store_true")
    ns = ap.parse_args(rest)
    try:
        out_arg = getattr(ns, "out", None) or getattr(ns, "outdir", None)
        if out_arg and (os.path.exists(out_arg) and os.path.samefile(out_arg, ns.file) or out_arg.lower().endswith(".skp")):
            print("skp-ballet: refusing to write %s: it is (or looks like) a SketchUp file; skp-ballet never writes .skp" % out_arg, file=sys.stderr)
            return 2
        if cmd == "info" and (ns.layers or ns.bbox):
            m = scene.load(container.open_skp(ns.file))
            if ns.layers:
                for lid, name in sorted(m.layers.items()):
                    print(lid, repr(name), "[off]" if lid in m.layers_off else "")
            if ns.bbox:
                b = bbox(m)
                print(" ".join("%.6g" % x for x in (b[0] + b[1])) if b else "empty")
            return 0
        if cmd == "info" and ns.json:
            info_json(ns.file)
            return 0
        m = info(ns.file)
        if cmd == "info":
            return 0
        if cmd == "cache":
            from . import cache
            print(cache.write_cache(m, ns.outdir, os.path.basename(ns.file)), "->", ns.outdir)
            return 0
        if cmd == "convert":
            out = ns.out or os.path.splitext(ns.file)[0] + ".glb"
            print("triangles:", mesh.write_glb(m, out), "->", out)
            return 0
        glb = os.path.join(tempfile.mkdtemp(prefix="skpballet-"), "model.glb")
        print("triangles:", mesh.write_glb(m, glb))
        return serve(glb, ns.port, not ns.no_browser)
    except (ValueError, OSError) as e:
        print("skp-ballet: %s" % e, file=sys.stderr)
        return 2
