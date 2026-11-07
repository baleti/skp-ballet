# SketchUp .skp format notes (2021+ files)

Sources: own inspection of real files (SketchUp 21.x/22.x and 25.x) and the MIT-licensed
OpenSKP notes (docs/BINARY_FORMAT.md). No Trimble SDK material. Statements marked (v) were
verified against files here; (u) are unverified.

## Container (v)
`FF FE FF 0E` + UTF-16 "SketchUp Model" + `FF FE FF 0A` + UTF-16 `{21.0.339}` (version), a few
bytes, then an ordinary ZIP starting at the first `PK\x03\x04`. ZIP entries: `model.dat`
(binary), `meta/meta.dat` (same TLV encoding), `materials/<name>/material.xml` (colour,
alpha), `styles/*/style.xml`, thumbnails, `classifications/*.skc`.
SketchUp 2013-2020 files have no ZIP (MFC CArchive stream): unsupported here.

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
