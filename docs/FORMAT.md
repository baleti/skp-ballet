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

### Spike: walking the root list of components.skp (2026-11-08, not committed as code)
Reading from the `ff ff 06 00 12 00 CComponentInstance` declaration (u32 count 8 just before it) with the existing object
reader plus a stub instance body (pre, drawbase, u16 def slot, 13 f64, name, 16-byte id) parses the first instance, then
fails at the `36 80` tag after the id: class-ref to slot 54, undeclared. The slot counter is uncertain because the
CThumbnail declaration and object before the list consume slots (class 51, object 52 if the first list ended at slot 51), so
the CComponentInstance class would be 53 and `36 80` (slot 54) would be the first instance object itself, i.e. the tag
after the id may be a back-reference/trailer rather than a class-ref. Needs the exact slot accounting through the
definition trailer before the list can be walked.

### scan_lists bases vs instance definition slots (measured 2026-11-11, 17 fixtures with lists)
List bases from scan_lists (slot of first object, offset guessed 0..9) and instance def refs:
components lists 19,51 refs 15; nesting_2013/2017/2020 lists 14,33,55,76 refs 12,57; groups lists 18,37,53,72 refs 15/40/56;
nested lists 15,34 refs 12/37/56. Differences ref-minus-base: -4; -2,+2; -3,+3,+3; -3,+3,+22. The def object therefore
is NOT at a fixed offset from its own list base: refs are mostly 2..4 BELOW a list base but also above one, so a ref can
point into the middle of a list or to an object after it (e.g. the definition object written after its list trailer).
Conclusion: a fixed-offset link rule would be wrong on 3 of 4 fixtures; the whole archive (class-refs, attribute
containers, thumbnail objects) must be slot-counted exactly before refs can be resolved. load_legacy stays unwired (item 43).

### Instance tail and slot chain (spike 2026-11-11, items 28/44, not code)
Instance body followed by a u16: it is `36 80` (0x8036) on components.skp but 0 on nesting_2017 (Outer/Inner/unnamed all 0), so it is
not a constant class tag; the next bytes are the NEXT object's prefix (`03 80` attr container, mask, id), i.e. no wrapper object
sits between chained instances. Parsing the 16-byte id + one u16 makes nesting_2017 walk its instances inside definition lists
(list 2 and 3 end with an instance, list 4 is the root with one instance): refs Inner 12, unnamed 36, Outer 57 against list
bases 14, 33, 55, 76. The bases of lists after the first are only lower-bounded by scan_lists (it accepts the smallest slot
offset 0..9 that parses), so comparing refs to them proves nothing; the exact slot of each definition object needs the
definition trailer (definition object, name, description, thumbnail class + object) to be parsed and counted. Unverified idea:
a ref points at the definition OBJECT, allocated after its list for later definitions, so ref = slot after list end + small k.
Next step: parse the trailer to get exact slots, then re-check on components (3 instances refs 15) and groups (15/40/56).

### Legacy definition link RESOLVED for tree-consistent files (2026-11-11, item 45; implemented as legacy_tree)
Rule found on 10 fixtures with instances: the distinct instance definition refs, sorted ascending, correspond one to one to the
entity lists in stream order (definitions leaf first, root list last); ref minus list base is -3..+3 (chair_and_table 19,138,
199,260,321,331,573,685,746 vs bases 22,135,196,257,318,329,570,682,743; synthetic 2019 40,65,84,107 vs 43,62,81,104). The def
object slot is allocated before its list, later ones shift by the trailer (thumbnail class + object + inline layer) slots, which
is why a fixed offset fails. legacy_tree accepts a file only if lists = distinct refs + 1 and every ref is within 4 of its
list base and instances only use earlier definitions. Passes on nesting_2013/2017/2020 (3 squares at x 0, 20, 40 inches, identity
instance transforms, 6 triangles, identical across versions). Rejected (fall back to first list): components, groups, nested,
chair_and_table, group_in_definition_flag, synthetic 2019, image: their root or later lists do not parse yet (instance child
objects `13 80`/`15 80` and other classes end the list), not because the rule fails. Instance tail u16 is consumed only in this path.

### Item 46 (2026-11-11): instance tail correction and exact list slots
Correction to the spike above: the u16 after an instance's 16-byte id is NOT part of the instance. In components.skp it is `36 80`,
the class-ref TAG of the next list object (the instance class, declared at slot 54); in nesting it is the list terminator 0.
With no tail consumption scan_lists walks root lists of components/groups/chair_and_table/synthetic 2019/group_in_definition_flag
completely. Slot offsets of later lists are now validated by back-reference kinds (edge use -> edge -> vertex, `_refs_ok`),
since a wrong offset aliases back-refs onto vertices; this makes each later list base exact. legacy_tree now accepts 7 public
fixtures (chair_and_table: 9 definitions, 15 instances, 86 faces, 352 triangles; components: 3 faces; groups; v2019 synthetic:
4 definitions, 11 instances). Still rejected: nested (lists end early), arcs/edge_flags (no instances). Instance transforms are not
independently verified beyond components.skp (bbox 340 in = instance at y 300 scaled 2 over a 20 in chair).

### nested.skp third list (item 47, 2026-11-11, NOT solved)
After list 2 (ends 4743) comes the usual trailer (`Engine` name, `00 f1 53 65` pad, thumbnail class slot 34 `22 80`, an inline CLayer at 5031
with name Layer0). The third list sits at about 5152..5449 and uses CEdge (`0f 80`) and CVertex (`11 80`) objects with ids 0x27..0x2f,
but has no `u32 count` that scan_lists recognises (bytes before the first `0f 80` are `3a 00 00 00 00 00 3d 00 00 00`; 0x3d is
also used as an edge back-ref to slot 61 inside it, so it is a slot, not a count) and its edges reference vertices and layer objects
allocated in the trailer. Tried: tolerating unknown back-refs below the current slot (gives a false 1-object list; reverted).
Needed: parse the trailer's inline CLayer/thumbnail objects so their slots are real, and find how the list length is encoded
(maybe a terminator instead of a count when entities hold sub-lists). Instance record `1b 80` at 5404 follows the edges.

### Legacy definition names (item 48, 2026-11-11)
The first UTF-16 string within 60 bytes after an entity list end is the definition name (second string = description, usually empty; the
root list's trailer holds the model location, e.g. 'Boulder (CO)' / 'USA', not a name). Verified on 9 fixtures, e.g. chair_and_table gives
Leg_Chair, Seat_Chair, BackrestFrame, BackrestCushion, Backrest, Chair, Leg_Table, Tabletop, Table in stream order. Used by legacy_tree.

### nested.skp SOLVED (item 49, 2026-11-11)
The third list is a normal list: u32 count 61 (0x3d) right before the first `0f 80` (my earlier "slot, not a count" reading was wrong; it is both). Its
slot offset after list 2 is 6 (offsets 0..9 tried, only 6 parses 56+ objects). It holds edges, 2 instances, a face, arc edges, then CConstructionPoint (49 byte
body after pre + drawbase + layer) and CConstructionLine (68 bytes), then two trailing 0 terminators that ARE counted in the 61, so a list may end with up
to 2 None objects (scan_lists now accepts n-2 non-None). Construction body lengths come from this single fixture and are skipped, not decoded.
legacy_tree now accepts nested.skp: definitions Wheel, Engine, Car, 28 triangles.

### Legacy edge draw base bytes (item 59, edge_flags.skp, observation only)
The 10 bytes after an edge's attribute preamble (8 draw-base bytes + u16 layer ref), written b0..b9. Distinct patterns on this fixture's edges:
`00 00 01 01 01 01 01 00 00 00` (the common one, also on loops/vertices-bearing objects), `00 00 00 01 01 01 00 00 00 00` (b5=1),
`00 00 00 01 01 00 01 00 00 00` (b6=1), `00 00 00 01 01 00 00 00 00 00` (all zero after b4). OpenSKP notes name hidden = byte 2, soft = byte 5,
smooth = byte 6, which would make the common pattern "hidden" (b2=1) for most edges: implausible, so either the byte numbering is shifted by
the u16 prefix or b2 means something else (e.g. visible). No ground truth for which edges the author hid or softened, so the flags are NOT used
and all edges are drawn. A fixture with one known hidden and one known soft edge would settle it.

### 2021+ instance name (item 76, 2026-11-11)
Instance node (0x1964) child 0x1965 holds the instance name as raw UTF-8 (empty when unnamed): nesting_2021 gives Inner, '' and Outer, the same
names the legacy nesting fixtures give. Other children: 0x1966 13 f64 matrix, 0x1967 definition id (varint), 0x1968 16-byte guid.


## Legacy truncation detection (negative result, 2026-11-13)

Searched all 29 public legacy fixtures for a u32 equal to the file length (minus 0..63) in the
first 4 KiB and in the last 64 bytes: no consistent field (the few hits sit at different offsets
with different deltas per file, i.e. coincidences). File tails also differ per version. So a
truncated legacy file cannot be detected from header or tail; skp-ballet warns on every legacy
load instead.

Truncation signals in use (2026-11-13, legacy files): (1) no layer table found (from v4 on; every intact
public file has one; it sits before the entity lists), (2) bytes after the last entity list outside 2000..4300
(2017+ only), (3) file does not end in zero padding or a 1 flag when no geometry decoded, (4) the first-list
decoder reports INCOMPLETE. Over 235 test cuts (29 files, 1 KiB steps): 222 flagged, 2 rejected, 11 silent: cuts
mostly inside the final settings tail (scenes, styles, thumbnail), which skp-ballet does not read, plus v3. The
chair_and_table cut at 14336 of 30748 bytes (5 of 10 lists) has no TRUNCATED signal (its tail size is coincidentally
normal) but the tree rules reject it, so it warns 'instances are NOT placed' and `--strict` exits 3 (item 98). The
3 intact fixtures that trip `--strict` (text_arrows_2017, v3, v4) do so through INCOMPLETE ("5 of 8 objects", "0 of 5": object
types the decoder does not know, e.g. text), not through NOT placed; they contain no instance classes. INCOMPLETE therefore means
"not everything decoded", which is true for those files, but it is not proof of truncation.

## Legacy class coverage on the 29 public fixtures (2026-11-13)

Classes declared per file count (files containing the class). Entity-list decoder (S) = handled inside the first-list
parser; other readers = handled by a separate scanner; none = not read at all.

| Class | Files | Handled by |
|---|---|---|
| CVersionMap, CSkFont, CCamera, CSkpStyle, CCustomLineStyle, CViewPage | 29, 29, 28, 26, 7, 2 | none (settings, scenes, styles) |
| CLayer | 29 | scan_layers (names, flag unverified) |
| CAttributeContainer, CAttributeNamed | 26 | entity-list decoder (skipped content) |
| CVertex, CEdge, CEdgeUse, CLoop, CFace | 24 | entity-list decoder |
| CMaterial, CDib | 15, 6 | scan_materials (colour, alpha, embedded PNG) |
| CComponentDefinition | 10 | legacy_tree trailer names |
| CComponentInstance, CGroup | 9, 7 | entity-list decoder + legacy_tree |
| CArcCurve, CCurve | 5, 2 | entity-list decoder (arcs as edges) |
| CFaceTextureCoords | 3 | entity-list decoder (UV not exported) |
| CConstructionLine, CConstructionPoint | 2, 1 | entity-list decoder (skipped by length, not exported) |
| CText | 1 (text_arrows_2017) | none: decoding stops there (INCOMPLETE) |
| CImage | 1 (image.skp) | none inside entity lists; check image.skp stops cleanly |

## 2021+ annotation records (annotation_layers_vff.skp, 2026-11-13; kinds are inferred, not verified)

Entity-collection (0x1388) children besides geometry, all found only in this fixture:
- 0x1398: flat TLV of 0x55F0 records = screen text: 0x55F1 UTF-8 string, 0x55F2/0x55F3 f64 pair (0.23, 0.66: screen
  fractions?), 0x55F5 / 0x55F7 3 x f64. Strings: "Nested screen note", "Dot", "Closed arrow", "Open arrow".
- 0x1391 > 0x4269 > 0x426A (64 bytes): point (1,2,3), unit normal (3,4,5)/|..|, 0, 7.07 (= |(3,4,5)|, plane offset?) =
  section plane.
- 0x1392 > 0x426C > 0x426D (24 bytes): point (1,2,3) / (1,2,4); 0x426E zero vector = guide point?
- 0x1399 flat TLV of 0x5BCC records, each with two 0x5BCD/0x5BCE > 0x5208 > 0x520A points (0,0,0) and (10,0,0) = linear
  dimension, start and end.
The three layer names of the fixture (translated from Chinese: leader text, reference elements, dimension) match
text / section+guide / dimension. skp-ballet lists them in `info` and does not draw them.

## Integrity fields in 2021+ files (negative result, 2026-11-13)

Looked for a checksum or length of model.dat in meta/meta.dat and inside model.dat itself (crc32, adler32, md5,
sha1, sha256, plain length u32/u64, also md5/sha of every zip member against the 16-byte GUID-like field of meta.dat)
on 3 fixtures: nothing matches. model.dat starts with tag 0x01F4 whose u32 length equals the rest of the file minus
the 6-byte header (the only self-check: a truncated or padded stream fails it). The ZIP CRC-32 per member is checked
by zipfile on read and covers the stored bytes only, so a structurally damaged but re-zipped model.dat (duplicated or
lengthened record, see tests/test_fuzz_model_dat.py) decodes without any error. Consequence for a future writer: there
is no hidden checksum to keep in sync besides the ZIP CRCs, and also no way for a reader to detect such damage.

## 2021+ pre-zip header (69 bytes, identical layout on 5 fixtures, 2026-11-13)

`FF FE FF 0E` + UTF-16LE "SketchUp Model" (MFC-style counted string), `FF FE FF 0A` + UTF-16LE "{25.0.575}" (version),
then `56 46 46 08 00 01 00 11 00` (constant) and 4 bytes that differ per file: not a crc32/adler32/md5/sha1 of the zip,
the whole file or the members (looks like an id). The zip starts at offset 69. The reader checks the 4 magic bytes and
finds `PK\x03\x04`; flipping any other header byte is accepted (45 of 69 single-bit flips on nesting_2021 changed
nothing visible, 20 made the version "unknown", 4 were rejected). A missing version now warns.

### Legacy tail cuts (measured 2026-11-14, 29 public legacy fixtures)
Cutting N bytes off the end, count of fixtures flagged by a `--strict` trigger / silent: N=1: 4/25, N=2: 4/25, N=4: 19/10, N=8: 11/18,
N=16: 5/24, N=64 and N=256: 27/2. At 90, 95 and 99 percent every fixture carries at least the generic "no known end marker" warning
but only the cases above reach the strict triggers. The last ~16 to 40 bytes are zero padding or flag words (7 distinct endings in
29 files), so a cut there loses no geometry but also cannot be told from an intact file. Consequence for any future writer: it must
never rely on "the reader did not complain" for legacy files; a legacy file without a verified end structure is read-only.

### Legacy appended bytes (measured 2026-11-14, 29 fixtures)
Appending bytes does not change any decoded count (29/29 unchanged in every case). Strict-flagged / silent: +1 zero byte 4/25,
+16 zeros 4/25, +4 0xFF 27/2, +70 garbage 27/2, +4096 zeros 22/7. Appended trailing data is therefore mostly invisible to the
reader; a writer must treat unknown trailing bytes as data to preserve verbatim, not as noise.

### Legacy interior bit flips (measured 2026-11-14, 29 fixtures x 20 random single-bit flips, seed 11, compared by GLB sha256)
540 no effect on the decoded output, 22 changed output WITH a strict-level warning, 11 changed output SILENTLY (1.9 percent of
all flips, 33 percent of flips that mattered), 7 rejected, 0 hangs, 0 unexpected exception types. By decoded counts alone only 3 of
870 flips looked silent, because most silent changes move coordinates. The legacy container has no integrity field, so a damaged
but parseable file is accepted; a writer must never "repair" or re-emit a legacy file it has only read.

### 2021+ model.dat interior bit flips (measured 2026-11-14, 5 fixtures x 300 flips of the DECOMPRESSED stream, seed 13, GLB sha256)
1183 no effect, 261 changed output SILENTLY (17 percent), 54 changed with a warning, 2 rejected, 0 hangs. Real files are protected
only by zip member CRC32 (see the deflated-member test): flips in the stored file are caught, but a flip made before compression
(for example by a writer bug, since the writer recomputes the CRC) is accepted and shows up only as changed geometry. For a writer
this means the oracle for correctness cannot be "reads back without error"; it must compare decoded content with the intended edit.

### image.skp: first entity list is the image definition (found 2026-11-14 by cross-check with openskp)
Public fixture image.skp holds a root face of 10x10 in at the origin and one hidden instance (rotated 90 degrees about X, moved 40 in)
of a definition `Image0` that has its own 48x36 in face. The first entity list in the file is the IMAGE definition's, and the
reader shows it as the model (48x36 face) while the root's 10x10 face is not read. Now warned ("the image's own face"), which
triggers `--strict` together with the existing CImage "NOT read" warning. Not fixed: needs the root list located without a tree.
Follow-up (2026-11-14): the root list of image.skp starts at offset 4840 with count 6 and its FIRST object is a CImage (class
declared there); `scan_lists` stops because `_R.obj()` raises "unsupported class CImage" for every slot offset, so the root's
10x10 in face (doubles 10.0 at 5044..) is never reached. Visible in the CImage record: a 13-double transform-like block (1.0
diagonal, 40.0 translation), a 16-byte GUID (10 11 12 .. 1f with 2 bytes differing), then the next objects; its total length
is not pinned yet, so it cannot be skipped safely.

Resolved (2026-11-14): CImage is instance-shaped (pre, draw base, definition ref u16, 13 f64 = 12 transform + 1.0, UTF-16 source path,
16-byte GUID; same as CComponentInstance, layout from the MIT notes of the public OpenSKP project and confirmed by parsing image.skp
to the end of the list: 2 lists, 5 and 6 objects). With CImage parsed, `scan_lists` reaches the root list and `load_legacy` takes the
LAST list as the model root when a file has a CImage and at least 2 lists; image.skp now shows the 10x10 in root face like openskp
does. The image's picture quad (instance of Image0, hidden) is still not shown; only one public fixture has a CImage, so this rests on one file.

## Legacy version coverage and version switches (2026-11-14)
Public legacy fixtures exist for SketchUp file versions 3, 4, 5, 13, 17, 18, 19, 20 only. Versions 6-12 and 14-16 have NO fixture.
Version-dependent switches in skpballet/legacy.py: the "no flag-mask byte after the attribute-container ref" rule is applied to
every version <= 13 (calibrated on v13 alone; v5 follows the same code path without it being checked beyond v5's one fixture);
truncation signals (tail_suspect, end marker check) only run for version >= 17 (calibrated on 2017-2020), so files of versions
4-16 get no truncation detection except the missing-layer-table check (from v4). v3 and v4 decode 0 faces (INCOMPLETE; v5
carries one extra byte before the first CVertex, cause not pinned). Guard: files of versions 6-12 and 14-16 raise an
"UNTESTED version" warning that also trips --strict (tests/test_readonly.py). Remove it per version only once a public
fixture of that version decodes and is cross-checked.

### Legacy truncation on versions below 17 (measured 2026-11-14, fixtures v3, v4, v5, v13)
nesting_2013 (v13) cut by 1 byte, 64, 256 and 10 percent: geometry unchanged, no warning (harmless: only trailing data lost). Cut by 30 percent:
2 of 3 instances/definitions survive, NO warning; cut by 50 percent: 1 of 3 faces survives, NO warning (silent geometry loss).
v5 (one fixture): silent up to a 10 percent cut, strict-flagged from 30 percent (the face is lost, flagged through INCOMPLETE).
The existing end-of-file test `_end_ok` is False on all four intact pre-17 fixtures, so it cannot serve as a guard there
(it would flag intact files). Conclusion: for legacy versions below 17 there is currently no usable truncation signal that catches a
mid-file cut; this is the same read-only rule as for any legacy file, now with measured evidence for the older versions.

### Legacy mid-file block damage (measured 2026-11-14, 29 fixtures x 8 random windows per case, seed 178/179, counts compared)
Windows of 64/256/512 bytes overwritten with 0x00 or 0xFF at random offsets: zero 64: 232 cases, 6 silent count changes; zero 256 and 512:
0 silent (the zero-run warning catches them, 227/224 warned); 0xFF 64/256/512: 4, 7 and 11 silent count changes. Of 1,392 cases
(minus refused) the silent changes split into materials 21, layers 10, definitions 5, instances 5, and geometry (vertices/edges/faces)
4 each; the 9 cases with geometry or tree changes were: edge_flags (3, coordinates zeroed so vertices MERGE: the list still parses
28 of 28 objects, i.e. value damage inside a parsed record is not detectable without a checksum), 4 definition/instance losses
(nesting_2013/2017, nested, group_in_definition: a damaged definition record silently drops its definition and the instances using it)
and materials_and_layers (all faces lost, a layer lost). Same conclusion as the bit-flip measurements: legacy files carry no integrity
field, so any silent value change is undetectable on read; a writer must never trust a legacy file it cannot verify.
