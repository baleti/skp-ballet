# Warnings

`skp-ballet` never edits a .skp. Warnings tell you where an export (GLB extras `asset.extras.warnings`, cache
`meta.json` `warnings`, `info --json` `warnings`, the viewer banner) may differ from what SketchUp shows. `--strict`
exits 3 and writes nothing when a warning says part of the model is NOT placed (truncated by a limit).

Each line below starts with a phrase that appears in the source; `tests/test_readonly.py::test_warnings_doc_matches_source`
checks every one of them still does.

## Content in the file that is not in the export
- `annotation(s)` ... `NOT in this export`: section planes, guide points, dimensions and screen texts are read, never exported.
- `loose edge(s)`: edges bounding no face (curves, guides) are left out of a cache unless `--edges` is given.
- `hidden/off flag`: layers flagged hidden in the file are still drawn (the flag meaning is unverified).
- `entity collection`: a record collection the reader does not understand; its content is missing.
- `legacy file contains objects that are NOT read`: classes of 2013-2020 files that are skipped.

## Limits and corrupt-file protection (the rest is NOT placed)
- `instance expansion stopped`: more than 500000 instance placements (instance bomb or damaged file).
- `triangle limit`: more than 5 million triangles.
- `depth/size limit reached`: nesting deeper than 24 levels.
- `instance cycle`: a definition contains itself; the cyclic instance is skipped.
- `duplicate definition id`: two definitions share an id; the later one wins.

## Geometry that may be wrong
- `face refers to vertex ids missing`: a face names vertices that do not exist, it is incomplete or skipped.
- `triangulated face area differs`: the triangle area is more than 1% off outer minus holes (degenerate loops, edge-sharing holes).
- `scale 0 read as scale 1` and `singular transform`: an instance matrix is degenerate.
- `non-finite or absurd coordinates`: coordinates beyond 1e30 or NaN; convert and cache refuse such a file.

## Damaged or unusual files
- `model.dat:` record lengths do not tile, or trailing bytes: damaged or padded stream.
- `materials:` and `styles:` entries that are not well-formed XML or have bad colours (defaults used).
- `legacy file has a run of`: long 0x00 or 0xFF runs that intact files do not contain.
- `legacy file: no layer table found`: the file may be truncated (header only).
- `legacy file: unusual amount of data`: bytes after the last entity list; the geometry may be partial.
- `legacy files have no known end marker`: a truncated 2013-2020 file can load with partial geometry and no error.
- `legacy file: ` followed by a count of faces whose stored plane disagrees with the loop geometry: damaged data.
- `face edge`: a face names an edge that does not exist (damaged data).
- `extra or damaged data`: malformed container pieces (zip CRC, missing members, header vs meta version, bad XML).

## Experimental legacy (2013-2020) reader
- `legacy 2013-2020 reader is experimental`: only the first entity list is decoded.
- `legacy definition tree`: instance-to-definition links are inferred from slot order.
- `legacy file has components/groups but their lists do not fit`: instances are NOT placed.
- `legacy file has ` ... `entity lists but the definition tree was rejected`: only the first list is shown.
- `legacy file is SketchUp version`: a version with no public fixture.
- `legacy file contains an image`: the shown entity list may be the image's own face.
