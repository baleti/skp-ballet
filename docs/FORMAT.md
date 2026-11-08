# SketchUp .skp format notes (2021+ files)

Sources: own inspection of real files (SketchUp 21.x/22.x and 25.x) and the MIT-licensed
OpenSKP notes (docs/BINARY_FORMAT.md). No Trimble SDK material. Statements marked (v) were
verified against files here; (u) are unverified.

## Container (v)
`FF FE FF 0E` + UTF-16 "SketchUp Model" + `FF FE FF 0A` + UTF-16 `{21.0.339}` (version), a few
bytes, then an ordinary ZIP starting at the first `PK\x03\x04`. ZIP entries: `model.dat`
(binary), `meta/meta.dat` (same TLV encoding), `materials/<name>/material.xml` (colour,
alpha), `styles/*/style.xml`, thumbnails, `classifications/*.skc`.
SketchUp 2013-2020 files have no ZIP (MFC CArchive stream): partial experimental support (skpballet/legacy.py, first geometry run, faces only; see below).

## model.dat TLV (v)
Records: tag u16 LE, length u32 LE, payload. Container tags hold nested records (list in
`skpballet/tlv.py`). Tags below are the numeric LE values (OpenSKP writes the bytes, e.g. C409 = 0x09C4).
Counts of vertices/edges/faces from the decoder equal the raw tag counts on every test file.

| tag | meaning |
|---|---|
| 0x01F4 | file root |
| 0x01F6 > 0x1388 | model-level entity collection (top geometry + instances) |
| 0x01F9 > 0x1770 > 0x1771 > 0x157C* | definitions (0x157E name, 0x157D guid, 0x1388 entities) |
| 0x01F7 > 0x30D4 > 0x30D5 > 0x32C8* | materials (0x32CC name); colours come from material.xml |
| 0x01F8 > 0x3A98 > 0x3A99 > 0x3C8C* | layers/tags (0x3C8D name) |
| 0x1388 children | 0x7D0 header, 0x1389 vertices, 0x138A edges, 0x138B faces, 0x138C instances, 0x138E/0x139B unknown lists |
| 0x5DC | entity id: `DE 05 <u32 n> <n-byte LE int>` |
| 0x09C4 vertex (0x09C5 = 3 x f64 inches) | |
| 0x0BB8 edge (0x0BB9 start vertex id, 0x0BBA end id as LE ints; 0x0BBB unknown) | |
| 0x0DAC face (0x0DAD 4 x f64 plane; 0x0DAF material id; 0x0DAE > 0x1194 loop > 0x1195 > 0x0FA0 coedges) | |
| 0x0FA0 coedge: inline `A10F len edge-id`, `A20F len orientation(0 forward, 1 reversed)` | |
| 0x1964 instance: 0x1966 13 x f64, 0x1967 definition id, 0x1968 guid | |

Instance transform (v, via the OpenSKP note and a fixture checked against SketchUp's own
numbers): 9 rotation values (rows = images of x,y,z axes), translation (3), scale s:
`p' = s * (p . R + t)`. Units are inches; the exporter converts to metres and Y-up.

## Known unknown (u)
0x7D1 on edges/faces (same value as the front material in samples; probably material or layer),
back material, layer reference per entity, 0x138E/0x139B lists (probably index/order tables),
0x138D (images/groups?), texture UVs, curves/arcs (edges carry a curve id in 0x0BBB?),
text/dimension/section planes, scenes, styles, attribute dictionaries, hidden flags (D307/6842 in
OpenSKP notes), faces whose loops are degenerate (68 of 74k faces on one large real file
triangulate to an area >0.1 % off the polygon area).

## Plan of record types
1. done: vertices, edges, faces (with holes), instances, definitions, materials, layers.
2. next: per-entity layer/hidden flags, back material, texture images and UVs, edges as lines.
3. then: construction lines/points, text, dimensions, sections, scenes (camera), attributes.
4. later: SketchUp 2013-2020 MFC archive reader; writing (only after read round-trips are exact).

## SketchUp 2013-2020 (legacy MFC CArchive), research notes (not implemented)

Source: public docs of the MIT-licensed OpenSKP project (secondary, as reported; not verified by us, no
legacy sample available on this host). No code copied.

- No ZIP: one uncompressed MFC CArchive object stream with a single global 1-based store map.
- Object tags u16 LE: 0 null; 0xFFFF new class (u16 schema, u16 name length, ASCII name); bit 15 set = class-ref
  to a new object; 0x7FFF escapes to a u32 (bit 31 = class-ref, else back-ref); other values are object back-refs.
- Strings: marker `FF FE FF`, length byte (0xFF escapes to u16, 0xFFFF to u32), UTF-16LE; class names ASCII.
- Numbers little-endian; coordinates f64 inches.
- Per-version differences: v16 has no persistent-id mask in entity preambles, v17+ has one; some entity sizes
  differ between v16 and v17+. Internal versions 13-20 map to SketchUp 2013-2020.
- Pitfalls reported: annotations burn store-map indices without writing bytes; round-profile records skipped;
  OpenSKP parses only part of its old test files (8/14, 11/15 in two docs), so expect variance.
- Plan: first implement the tag/back-ref reader over a public legacy sample (none yet), verify counts against the
  2021 re-save of the same model, only then widen versions.

## Observation: tag (layer) records in annotation_layers_vff.skp (2021+, v26.1)

Layer node 0x3C8C has 0x5DC (id), 0x3C8D (name, EMPTY for all 4 layers here), 0x3C8E (1 byte, 0 here), 0x3C8F
(an embedded record: 0x32C8 containing id and 0x32CC string such as `Layer_Layer0`, UTF-8, non-ASCII names occur;
probably the layer colour material) and 0x3C90 (u32 0). So `layer_names` is empty for this file; the meaning of
0x3C8E (visibility?) is unverified (single data point).

### Legacy layouts (secondary, from OpenSKP legacy.py via summary; unverified unless marked)

- File start (checked on nesting_2017.skp): `FF FE FF 0E` + UTF-16 "SketchUp Model", `FF FE FF 08` + UTF-16 "{17.0.1}",
  16 bytes (GUID-like), then `FF FE FF n` + UTF-16 source path, then the CArchive object stream (class names ASCII,
  e.g. CVertex, CEdge, CFace, CLoop, CEdgeUse, CLayer, CComponentDefinition, CGroup, CComponentInstance, CSkpStyle).
- Entity preamble: object ref to CAttributeContainer, then (ver>=17) u8 mask and one byte per set mask bit forming the
  persistent id. VERIFIED for CVertex in 2017: `00 00` (null attrs), `01 20` (mask 1, pid 0x20), then f64 x,y,z in inches
  (first vertex 40.0,0,0); next object follows as class-ref tag `16 80` (0x8016 = bit 15 | slot 0x16).
- CVertex: early preamble, f64x3. CEdge: preamble, draw base (8 bytes, ver>=5: layer ref, material u16, hidden byte 2,
  soft byte 5, smooth byte 6), obj CVertex x2, obj curve. CEdgeUse: early preamble, obj CEdge, u8 sense, u16 loop
  back-ref. CLoop: early preamble, 2 flag bytes, CEdgeUse refs until u16 0. CFace: preamble, draw base, f64x4 plane,
  u32 nloops, loops, u16 back material. CLayer: early preamble, utf16 name, hidden flag in the first byte after it.
- CComponentDefinition is heuristic in OpenSKP (re-anchoring +-4 bytes, scanning for the thumbnail), so a clean-room
  reader should expect to derive its own tail layout from samples.

### Legacy observations from sample tracing (2017/2020 public fixtures)

- Entity list objects are top-level; faces/edges may appear in any order, edges reference vertices and each other by
  back-ref (u16 slot). A back-ref slot is absolute in the archive; the scanner finds the slot base by search.
- The attribute container (class declared early, class-ref 0x8003 in these files) holds CAttributeNamed objects
  (raw 4, UTF-16 dictionary name, key/typed value pairs, empty key ends) and, in textured faces (image.skp,
  uv_positioning.skp), a CFaceTextureCoords object whose body is f64-based (contains 48.0/36.0 and unit vectors) but
  whose length is not yet decoded: it is not a multiple-of-8 layout after the 3-byte preamble.
- Edge body after the two vertex refs ends with a null curve ref; the entity list then continues directly with the
  next object (here the face, whose first field is the attribute container ref).

## Fixed: ear clipping with several holes

Cause: bridged hole polygons contain exactly coincident vertex copies; the ear test then accepted invalid ears
(the ring became self-crossing) and the fallback dropped vertices (synthetic 2 holes: area 56 instead of 228).
Fix: the copies of the bridge ends are offset sideways by 1e-7 of the bridge length in the 2D working copy (exact 3D
positions are kept), so the ring is strictly simple. Synthetic random rectangular holes: 117/200 wrong -> 0/200;
jittered quads 72/200 -> 8/200 (open, not analysed). Real files: 10 -> 1 face of 11520 off by more than 0.1 percent.
