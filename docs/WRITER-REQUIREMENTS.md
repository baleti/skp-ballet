# Gate list for any future skp-ballet writer

No writer exists: skp-ballet only reads and refuses .skp output paths (tests/test_readonly.py). If one is ever added, these
conditions come from measurements on the public fixtures (details in FORMAT.md and the progress log) and must all hold.

## Never trust "reads back clean"
- 2021+ model.dat has no checksum; only the top record length (stream size minus 6) and the zip member CRC32 exist. A flip in
  the decompressed stream changed the decoded output silently in 17 percent of 1500 trials (261), legacy 1.9 percent.
- Oracle = `tools/model_diff.py` (decoded content; saw 315 of 315 GLB-changing flips on 2021+ and 33 of 33 on legacy, plus
  more) AND `tools/skp_bytes_diff.py` (untouched byte ranges and zip members identical). A no-edit load then save must give
  model_diff identical and, ideally, a byte-identical decompressed model.dat.
- The final judge is the real SketchUp opening the saved file; not available here (no SketchUp VM), so no writer ships on
  reader evidence alone.

## Legacy (2013-2020) files: read-only
- No end marker, no integrity field. Tail cuts of 1 to 16 bytes are mostly undetectable (4 to 19 of 29 flagged), appended bytes
  mostly silent. Only the first entity list and a heuristic definition tree are decoded; unknown classes are skipped.
- Writer rule: refuse legacy files (or copy bytes verbatim, never re-emit).

## 2021+ container rules a writer must keep
- Pre-zip 69-byte header (version string, 4 per-file bytes of unknown meaning), meta/meta.dat (same version), materials/*,
  styles/*, model.dat. Keep member order, names (zip names are stored as written, non-ASCII looks like mojibake in listings),
  and the unknown 4 header bytes unchanged. Reader warns on: missing meta.dat or styles, CRC failure, duplicate names,
  bytes after the zip, zip comment, header/meta version mismatch, malformed material/style xml, model.dat length mismatch.
- A writer must emit none of these warnings: run the reader with `--strict` (exit 3 on any) on every output.
- Unknown TLV records and tags must be copied verbatim (the reader decodes only a subset: unread tags warn).

## Process
- Original is never opened for writing; write to a temp file next to it, verify (reader --strict, model_diff, bytes diff, then
  the real app), keep a backup, rename atomically. Same rules as the savegate library for DWG/RVT.
- Every failure becomes a permanent regression file (private files stay local, public repos get only synthetic or public
  fixtures).
