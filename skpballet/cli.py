"""skp-ballet FILE.skp            print info and open the viewer
skp-ballet info FILE.skp       print contents only
skp-ballet convert FILE [OUT]  write a .glb"""
import argparse
import functools
import http.server
import os
import sys
import tempfile
import threading
import webbrowser

from . import container, scene, mesh


def info(path):
    skp = container.open_skp(path)
    m = scene.load(skp)
    print("file:      %s" % os.path.basename(path))
    print("version:   SketchUp %s" % m.version)
    for k, v in m.counts().items():
        print("%-10s %d" % (k + ":", v))
    top = sorted(m.defs.values(), key=lambda d: -len(d.faces))[:10]
    for d in top:
        print("  def %-30s faces=%d edges=%d instances=%d" % (d.name or "<group %s>" % d.id, len(d.faces), len(d.edges), len(d.instances)))
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
                return os.path.join(vendor, os.path.normpath(p[len("/vendor/"):]).lstrip("./"))
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
    cmd = a[0] if a[0] in ("info", "convert") else "open"
    rest = a[1:] if cmd != "open" or a[0] == "open" else a
    if a[0] == "open":
        rest = a[1:]
    ap = argparse.ArgumentParser(prog="skp-ballet " + cmd)
    ap.add_argument("file")
    if cmd == "convert":
        ap.add_argument("out", nargs="?")
    if cmd == "open":
        ap.add_argument("--port", type=int, default=0)
        ap.add_argument("--no-browser", action="store_true")
    ns = ap.parse_args(rest)
    try:
        m = info(ns.file)
        if cmd == "info":
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
