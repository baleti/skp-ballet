"""Check a skp-ballet cache folder: model.glb, meta.json and materials.json exist, meta.json glbSha1/glbBytes match model.glb,
the GLB header length matches the file, and the JSON files parse.
usage: python3 tools/verify_cache.py DIR      exit 0 consistent, 1 inconsistent (reasons on stderr), 2 unreadable"""
import hashlib, json, os, struct, sys


def verify(d):
    errs = []
    try:
        g = open(os.path.join(d, "model.glb"), "rb").read()
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        json.load(open(os.path.join(d, "materials.json"), encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [str(e)]
    if g[:4] != b"glTF" or len(g) < 12 or struct.unpack_from("<I", g, 8)[0] != len(g):
        errs.append("model.glb header/length is wrong")
    if "glbSha1" not in meta:
        errs.append("meta.json has no glbSha1 (written by an older skp-ballet): pair cannot be checked")
    else:
        if meta["glbSha1"] != hashlib.sha1(g).hexdigest() or meta.get("glbBytes") != len(g):
            errs.append("meta.json does not belong to this model.glb (mixed writers or a partial copy)")
    return meta, errs


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    meta, errs = verify(sys.argv[1])
    if meta is None:
        print("unreadable: " + errs[0], file=sys.stderr); sys.exit(2)
    for e in errs:
        print(e, file=sys.stderr)
    print("consistent" if not errs else "INCONSISTENT")
    sys.exit(1 if errs else 0)
