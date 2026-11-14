"""Which fixtures change their DECODED content between a git revision and the working tree?
usage: python3 tools/regress_diff.py REV [DIR_OR_FILES...]     (default: tests/data, recursive)
Builds a throwaway git worktree of REV, loads every .skp with the old and the new skpballet in separate processes and
compares tools/model_diff.canon output. Prints changed file names only (no content); exit 0 none changed, 1 changed.
Pitfall handled: model_diff prepends the repo root to sys.path on import, so each child imports model_diff first, drops
skpballet from sys.modules and only then puts the wanted root first."""
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CHILD = r'''
import sys, json
sys.path.insert(0, sys.argv[3])
import model_diff
for k in [k for k in sys.modules if k.startswith("skpballet")]:
    del sys.modules[k]
sys.path.insert(0, sys.argv[1])
from skpballet import container, scene
out = {}
for f in json.load(open(sys.argv[4])):
    try:
        out[f] = model_diff.canon(scene.load(container.open_skp(f)))
    except Exception as e:
        out[f] = ["ERR " + type(e).__name__]
json.dump(out, open(sys.argv[2], "w"))
'''


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    rev, targets = argv[0], argv[1:] or [os.path.join(ROOT, "tests", "data")]
    files = []
    for t in targets:
        files += sorted(glob.glob(os.path.join(t, "**", "*.skp"), recursive=True)) if os.path.isdir(t) else [t]
    files = [os.path.abspath(f) for f in files]
    with tempfile.TemporaryDirectory() as tmp:
        wt = os.path.join(tmp, "old")
        subprocess.run(["git", "worktree", "add", "-q", "--detach", wt, rev], cwd=ROOT, check=True)
        try:
            lst = os.path.join(tmp, "files.json")
            json.dump(files, open(lst, "w"))
            res = {}
            for tag, root in (("old", wt), ("new", ROOT)):
                o = os.path.join(tmp, tag + ".json")
                subprocess.run([sys.executable, "-c", CHILD, root, o, HERE, lst], check=True, cwd=tmp)
                res[tag] = json.load(open(o))
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=ROOT)
    changed = [f for f in files if res["old"][f] != res["new"][f]]
    print("%d files, %d changed" % (len(files), len(changed)))
    for f in changed:
        print("changed:", os.path.basename(f))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
