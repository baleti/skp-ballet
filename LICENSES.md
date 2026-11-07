# Licenses of everything used

| Item | Use | License |
|---|---|---|
| skp-ballet code | this repo | MIT |
| Python standard library (zipfile, struct, xml, http.server) | runtime | PSF |
| three.js (+ OrbitControls, GLTFLoader), loaded at run time from the sibling rvt-ballet front-end, not copied here | viewer | MIT |
| OpenSKP (github.com/iamahsanmehmood/openskp), Copyright (c) 2024-2026 Ahsan Mehmood | its public BINARY_FORMAT.md notes were read as a format reference; code is NOT copied; its 4 small test fixtures `tests/data/*_2021.skp` (synthetic, "no private content") are redistributed; also `tests/data/annotation_layers_vff.skp` and the legacy-format (2013-2020) fixtures in `tests/data/legacy/` (small synthetic files from its repo, MIT) | MIT |
| pytest | tests only | MIT |

Not used: the SketchUp C SDK (proprietary Trimble API terms; redistribution and attribution
conditions; no SDK bytes, headers or libraries are in this repo and none are needed).
Format knowledge comes from public notes plus own inspection of files.
