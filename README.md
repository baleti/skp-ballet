# skp-ballet

Read SketchUp `.skp` files (sibling of rvt-ballet). Pure Python, no SDK, MIT.

    ./skp-ballet FILE.skp            # print info, open the viewer in a browser
    ./skp-ballet info FILE.skp       # contents only
    ./skp-ballet convert FILE.skp [OUT.glb]

Status (read only): SketchUp 2021+ files (zip container with `model.dat`). Lists definitions
(components/groups), vertices, edges, faces, instances, materials, layers; exports a triangulated
glTF binary (metres, Y-up, one primitive per material) that the viewer shows with three.js.
Not yet: SketchUp 2013-2020 files (MFC archive, refused with a clear message), textures, edge/line
export, text/dimensions/sections, scenes/cameras, writing. See docs/FORMAT.md.

The viewer loads three.js from `../rvt-ballet/web/vendor` or `$SKP_BALLET_VENDOR`.
Tests: `python3 -m pytest tests`. Licenses: LICENSES.md.

## Windows / macOS

The `skp-ballet` shell launcher is POSIX only. Everywhere (including Windows and macOS) use
`python -m skpballet FILE.skp`, or `pip install .` which installs a `skp-ballet` command.

## Headless render check

No GPU needed. With the viewer running (`skp-ballet FILE --no-browser --port 18777`):

    chromium --headless=new --no-sandbox --use-angle=swiftshader --enable-unsafe-swiftshader \
      --ignore-gpu-blocklist --enable-webgl --virtual-time-budget=10000 \
      --window-size=900,700 --screenshot=out.png http://127.0.0.1:18777/

Without the swiftshader flags the page stays on "loading..." because no WebGL context can be created.

## rvt-ballet front-end

`skp-ballet cache FILE.skp DIR` writes an rvt-ballet style cache folder (indexed `model.glb` with per-vertex
element index, `meta.json`, `materials.json`; one element per top-level group/component instance). View it with
`rvt-ballet serve DIR`. No `model.sqlite` is written, so element parameter and search panels stay empty.
The front-end's default Hidden line style renders blank for these caches (cause not isolated; not the edge batch, not
flat geometry), while `?style=shaded` (or wireframe) in the URL shows the geometry. Verified in headless chromium on a public fixture.
