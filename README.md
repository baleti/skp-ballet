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
