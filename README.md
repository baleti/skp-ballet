# skp-ballet

Read SketchUp `.skp` files (sibling of rvt-ballet). Pure Python, no SDK, MIT.

    ./skp-ballet FILE.skp            # print info, open the viewer in a browser
    ./skp-ballet info FILE.skp       # contents only (--json, --layers, --bbox)
    ./skp-ballet convert FILE.skp [OUT.glb]
    ./skp-ballet cache FILE.skp DIR  # rvt-ballet style cache folder

The tool never writes a .skp: convert/cache refuse an output that is the input or ends in `.skp`; a model without
triangles does not start the viewer (exit 1). `--layers` marks layers whose flag 0x3C8E is 1 as `[off]` (meaning unverified).

Status (read only): SketchUp 2021+ files (zip container with `model.dat`). Lists definitions
(components/groups), vertices, edges, faces, instances, materials, layers; exports a triangulated
glTF binary (metres, Y-up, one primitive per material) that the viewer shows with three.js.
Also (experimental): SketchUp 2013-2020 files (MFC archive). Files whose entity lists form a consistent tree (8 of 8 public
fixtures with instances) load as full definition trees: components and groups, names, instances with transforms, nested
placement (checked on a public chair and table: composed chair 34 in high, table 22 in). Instance-to-definition links are
inferred from slot order, so any file that does not fit the strict rules falls back to the first entity list only (faces, no
instances placed) with a warning. Layer names, materials with embedded PNG textures are listed; UVs are not decoded;
construction points/lines are skipped by length (from one fixture). Edges are exported as line primitives; materials get flat
colours; tag visibility flags are not used. All edges are drawn (hidden/soft edge flags are not decoded). When a legacy file has
components or groups but fails the strict tree rules, `info` shows the warning "instances are NOT placed" and only the first entity
list is exported.
Not yet: textures/UVs, text/dimensions/sections, scenes/cameras, writing (the tool never writes a .skp). Face
triangulation handles holes, pinched loops, spikes and T-touching vertices (area check on real files: about 0.002
percent of faces off by more than 0.1 percent). See docs/FORMAT.md.

The viewer loads three.js from `../rvt-ballet/web/vendor` or `$SKP_BALLET_VENDOR`.
Tests: `python3 -m pytest tests`. Licenses: LICENSES.md.

## Truncated or partial files

2021+ files are zip containers: a truncated one is rejected. Legacy (2013-2020) files have no length field or end
marker, so a truncated one can load with partial geometry. Every legacy load warns about this, and a heuristic (size of
the data after the last entity list plus the usual file end bytes) adds "may be TRUNCATED": no false positives on the
29 public legacy fixtures, 199 of 235 test truncations flagged by TRUNCATED or INCOMPLETE, 2 rejected, 34 silent (calibrated on 2017-2020 files only). Use
`skp-ballet info --strict FILE` (also on convert/cache) to exit with status 3 when a model may be partial
(TRUNCATED, INCOMPLETE or instances NOT placed). Corrupted coordinates (NaN, overflow) are refused with exit 2.

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
The front-end's default Hidden line style is spoiled by edge line batches: with them a flat public 2021+ fixture
(nesting_2021) draws nothing and legacy chair_and_table only faint dotted edges; without them both draw clean outlines
(headless chromium, 2026-11-11). So `cache` omits edge batches unless `--edges` is given. `?style=shaded` or `?style=wire` in the URL selects those styles (`wireframe` is not a valid value and leaves the view empty). An empty model (no
triangles) never finishes loading in the front-end. Verified in headless chromium on public fixtures.
