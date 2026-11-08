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

### Layer flag 0x3C8E statistics (real 2021-22 files, 8 files, 266 layer records; aggregate only)

0x3C8E is one byte: 0 in 263 records, 1 in 3. Children seen per layer record: 0x5DC, 0x3C8D, 0x3C8E, 0x3C8F, 0x3C90
(all 266) and 0x3C91 (130). The rare value 1 fits a "hidden"/"off" flag but has NO ground truth here (no SketchUp
to compare, public fixtures have only zeros), so the reader does not use it for visibility yet.

### Textures in real 2021-22 files (12 files, 643 materials; aggregate only)

10 of 643 materials have a texture: material.xml gets a `<texture textureFilename xScale yScale avgColor>` child
and the image sits beside it (`materials/<id>/*.jpg|png`, 10 files). `avgColor` is 0xAABBGGRR and equals the
material's colorRed/Green/Blue in all 10 cases, so the average colour is already what the GLB exporter uses. The
per-face UV data in model.dat is not decoded, so textures are not mapped (item 7 stays open).

### Legacy instance/group record (observed on 5 public fixtures; not implemented in code)

CComponentInstance / CGroup body, after the class declaration (all little-endian):
`pre` (attribute-container ref; a class-ref `03 80` introduces an empty container `00 00 00 00 00`), then a mask
byte `01` plus one byte (an id, 0x25/0x33/0x32/0x90 seen), drawbase 8 bytes (`00 00 00 01 01 00 00 00`), u16
`00 00`, u16 (0x0f, 0x24, 0x38, 0xc7 seen; meaning unknown, maybe a definition/entity id), then **13 f64**:
a 3x3 rotation/scale block (row-major in the fixtures), translation (x,y,z), and a uniform scale. Example
`components.skp`: identity 3x3, translation (100,0,0), scale 1. Then the instance name (UTF-16 `ff fe ff <n>`),
a 16-byte GUID, then references (`36 80` style class-ref to the definition) and the attribute dictionary
(`ff fe ff 0a "attributes"`, key/value pairs). The exact tail layout differs between fixtures (some have 8 extra
bytes + a 16-byte block before the next object), so definition linkage and group tails are still undecoded.
CGroup shares the layout (nesting_2017: translation 0, scale 1). Not wired into scene.py yet.

### Legacy CFaceTextureCoords (observed, not decoded)

Body length 215 bytes after the class name (fixed on the public fixtures that parse with this length): 3 bytes
preamble (attribute ref, mask 0), 4 bytes unknown, then 24 f64 starting at body offset 7 (6 groups of 4 doubles, 32
bytes apart), then 8 bytes. Values seen: `edge_flags` (default mapping): the first double of every group is 1.0
(others 0). `uv_positioning` (a face with manual UV positioning): groups 0 and 1 have first double 50.0, groups
2 to 5 have 1.0, all other doubles 0. So each group is probably `value, 0, 0, 0` padded to 32 bytes, or a 4-vector
whose other components happened to be 0 here; one non-trivial sample cannot tell. No per-face UV is produced; the
GLB uses flat colour for legacy textured materials.

## Legacy face layer reference (observations, 2026-11-08)
The u16 after the 8 draw-base bytes of a CFace is 0 on every face of 16 public fixtures that use only Layer0
(including files that have other layers but no face on them). Non-zero only in materials_and_layers (faces 14, 15;
layers Layer0, Roof, Walls) and chair_and_table (all 7 faces 16; layers Layer0, Chair, Table). Likely an archive
slot of the layer object (0 = default layer), same scheme as the material slot, but the slot-to-layer mapping is not
pinned: attribute dictionaries between layer objects may also use slots. Not applied to the model; exposed as
`info["face_layerrefs"]` from `legacy.scan_faces`. Needs a fixture with a known face-to-layer assignment.
Addendum: on a public 5425-object v20 model with two layers (Layer0, one named layer), all 229 faces carry ref 43 and
none 0, consistent with "non-zero = slot of a non-default layer"; with materials_and_layers the ascending non-zero
refs (14, 15) follow the list order Roof, Walls. chair_and_table has one distinct ref (16) for two non-default
layers, so the mapping stays ambiguous and is NOT applied. Layer record tail varies by version (`00 00 01 id` in
v17, `00 00 00 00` in v20); scan_layers accepts both.

## Legacy instances (verified listing, components.skp, 2026-11-08)
An instance/group record is 13 f64 (3x3 row-major, translation in inches, scale) immediately followed by the UTF-16
instance name. components.skp: 'Chair' identity at (100,0,0); 'Second Chair' rotated 90 degrees about Z (matrix
[0 -1 0; 1 0 0; 0 0 1], note the 6e-17 cos residue) at (200,0,0); 'Chair' with 3x3 = 2*I at (0,300,0).
`legacy.scan_instances` lists these by scanning for the name marker with the 104 bytes before it; the definition link
is still NOT decoded, so the model keeps 0 instances for legacy files (listing only). An earlier note here that the
layout varies with the transform was wrong (misaligned search for the translation value).
The u16 just before the 13 doubles is probably the archive slot of the instance's definition: components.skp has 0x0f for
all three Chair instances ('Chair', 'Second Chair', 'Chair' share one definition), groups.skp 0x0f/0x28/0x38 for
Table/Group/Chair, nested.skp 0x0c/0x25/0x38 for LeafInstance/Engine/Car. Resolving a slot to a definition's entity
list needs a decoder for the whole archive object stream (definition bodies, nested entity lists), but the reader only
parses the first entity list, so the link is recorded here and not used.

## Legacy definition trailer and root list (components.skp, byte walk, 2026-11-08)
After the definition's entity list (ends at 4579): 16-byte id, UTF-16 name, UTF-16 description (empty `ff fe ff 00`),
a block of zero/flag bytes with the pattern `00 00 f1 53 65` (3 unknown bytes), a CThumbnail object (class
declaration `ff ff 01 00 0a 00 CThumbnail`, then about 200 bytes of doubles that look like 4x4 matrices/bbox with 1.0
and 30.0 values), then a u32 (8) and the next entity list, whose first object declares CComponentInstance
(`ff ff 06 00 12 00 CComponentInstance`). Instance body: attr ref `03 80` + `00 00 00 00 00`, mask `01` + id byte
(0x25), drawbase `00 00 00 01 01 00 00 00`, u16 0, u16 definition slot (0x0f), 13 f64, name, 16-byte id, then a
variable tail (class-refs `36 80`/`13 80`/`15 80`, per-instance 4-byte numbers 0x127/0x128/0x129 that count up) that is
not decoded; it must be understood before the following objects of the list can be walked. The u32 8 does not equal the
3 instances, so the list also holds other objects.
Tail walk (components.skp): after an instance's name and 16-byte id comes `36 80` (a class-ref), then for the first
instance an inline attribute container (`03 80 ...`, `ff fe ff 0a attributes`, key/value pairs), then immediately the
NEXT instance's prefix (`01 <id> 0a 00 01 01 01 00 00 00 | u16 | u16 def slot | 13 f64`), so instances are chained
back to back with only their attribute dictionaries in between, and ids count up (0x25, 0x26, 0x27 ...). Child objects
`13 80`/`15 80` + `00 00 01 <id>` + 8..24 bytes of doubles (-1.0, 10.0 values) follow some instances (probably
construction or section items). Scanning (scan_instances) therefore finds every instance without walking the chain.

### Legacy definition slot vs first entity list base slot (6 fixtures)
Archive slot base of the first entity list (the one load_legacy parses) and the definition slots seen in instance records:
components base 19, instances ref 15 (all three); groups base 18, refs 15/40/56; nested base 15, refs 12/37/56;
nesting_2017 base 14, refs 12/57; group_in_definition_flag base 15, refs 12/37/12; chair_and_table base 22, refs include 19
(four Leg_Chair). So the first list belongs to the LOWEST definition slot, which is 3 or 4 below the list base (definition
object + its attribute container + class declaration precede its entities); definitions are written leaf first. Not used
in code: instance records also occur INSIDE other definitions (chair_and_table), so placing them at the root without
decoding their parent would be wrong. A safe special case (all candidates share one slot below the base, as in
components.skp) was not implemented to avoid overfitting.

### 2021+ per-face layer reference (checked 2026-11-08)
On the 5 public 2021+ fixtures a face node carries only tags 0x7D0 (id), 0x0DAD (normal) and 0x0DAE (loops), plus
0x0DAF (material) where set; no layer tag at all, because no public fixture has a face on a non-default layer. The
per-entity layer reference therefore cannot be located without a fixture. The OpenSKP notes (CLayer hidden flag = first byte
after the name) agree with the legacy flag seen in layers_extra ('Hidden') and materials_and_layers ('Walls').

### Legacy CText (legacy_text_arrows_2017, observation only)
CText body = attr ref, mask + id (0x1c), draw base, u16 layer, an embedded CSkFont object (class declaration, UTF-16
font name 'Tahoma', size doubles), then doubles for position/leader vector and a UTF-16 arrow style name ('Dot',
'Closed arrow'). The fixture has two texts (5 of 8 objects parse before the first CText). Text is not part of the
mesh export, so CText stays an unsupported class that ends the parse; the layout is not decoded.
