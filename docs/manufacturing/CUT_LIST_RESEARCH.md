# Cut-List Research

Research was performed from source clones under
`/tmp/hb4-research/cut-list/`. No third-party source code was copied into
Home Builder; the implementation independently applies the design techniques
described below.

## OpenCutList

- Repository: https://github.com/lairdubois/lairdubois-opencutlist-sketchup-extension
- Commit: `d03f4548e161ed25615b2ea828214a79e0f3e07a`
- Licence: GNU GPL v3 (`LICENSE`)
- Files inspected:
  - `src/ladb_opencutlist/ruby/model/cutlist/part_def.rb`
  - `src/ladb_opencutlist/ruby/model/cutlist/group_def.rb`
  - `src/ladb_opencutlist/ruby/model/cutlist/cutlist.rb`
  - `src/ladb_opencutlist/ruby/worker/cutlist/cutlist_generate_worker.rb`
  - `src/ladb_opencutlist/ruby/worker/cutlist/cutlist_export_worker.rb`

Useful techniques:

- Part identity includes material group, finished dimensions, orientation, and
  flip state. Folding checks dimensions, edge materials, face materials, grain
  handling, tags, and other visible attributes before quantities are combined.
- Consolidated definitions retain every instance path and instance name. This
  provides quantity reduction without losing model traceability.
- Sheet goods, edge materials, veneers, and hardware are distinct material
  types. Hardware is excluded from panel cutting totals.
- Edge treatments use stable geometric sides rather than display labels.
- Material summaries and detailed rows are separate export sources. CSV output
  uses the language CSV library, supports Unicode encodings, and reports export
  failures.
- Empty models, empty selections, untyped materials, obsolete reports, and
  unplaced parts produce explicit errors or warnings.

Limitations for Home Builder:

- The implementation is tightly coupled to SketchUp entities, materials, and
  extension formula wrappers.
- Its optional folding intentionally depends on UI visibility settings. Home
  Builder needs one deterministic manufacturing identity independent of a UI.
- Cutting dimensions may include edge and material allowances. Version 1 of
  Home Builder reports canonical finished dimensions only.

## Fusion 360 Export Cutlist

- Repository: https://github.com/bluekeyes/Fusion360-ExportCutlist
- Commit: `009a7a0fc24aaaee030413d166b54706a2ec9d44`
- Licence: MIT (`LICENSE`)
- Files inspected:
  - `lib/cutlist.py`
  - `lib/format.py`
  - `lib/geometry/bodies.py`
  - `ExportCutlist.py`

Useful techniques:

- Bodies are grouped by normalized dimensions and material with an explicit
  dimensional tolerance.
- A grouped item stores all component/body paths, and formatted names are
  sorted before export.
- Output formatters are separate from cut-list collection. CSV uses
  `csv.DictWriter`, JSON uses structured serialization, and HTML escapes both
  material and part names.
- Stable multi-pass sorting makes report order predictable.

Limitations for Home Builder:

- Dimensions are inferred from bounding boxes and sorted largest-to-smallest,
  which loses explicit panel length/width and grain orientation.
- Group identity does not include grain, edge banding, face, outline, or
  machining.
- Invalid or unsupported bodies are generally skipped rather than represented
  in a validation report.

## FreeCAD Assembly4 BOM Extension

- Repository: https://github.com/Ediforce44/FreeCAD-Assembly4-BOM
- Commit: `b1656d2afbcdc856cad9209d1acb4cec961a8076`
- Detected licence: no repository-level licence file; `InfoKeys.py` identifies
  itself as LGPL and the code is derived from FreeCAD Assembly4. Concepts were
  inspected only and independently reimplemented.
- Files inspected:
  - `makeBomCmd.py`
  - `InfoKeys.py`
  - `README.md`

Useful techniques:

- Assembly traversal increments quantities for repeated linked parts.
- Missing part properties are surfaced in a user log and recalculated before
  report generation.
- Cut-list files are separated by panel thickness and use a small mapping layer
  from internal attributes to external column names.
- The export workflow asks for a directory once and writes all related files
  together.

Limitations for Home Builder:

- Material is not part of cut-list grouping, so equal thicknesses from
  different materials can be mixed.
- Thickness and orientation depend on a specific Part/Body/Pad modeling
  convention and rounded bounding boxes.
- CSV is assembled manually and does not correctly escape delimiters, quotes,
  newlines, or arbitrary Unicode.
- Parts with an empty name or thickness can be silently omitted.

## CompoundCAD FreeCAD BOM Macro

- Repository: https://github.com/CompoundCAD/FreeCAD-BOM-Macro
- Commit: `37fc9172a002647a69a12423173d7d496cb37c78`
- Licence: GNU Affero GPL v3 (`LICENSE`); source header also permits GPL v3 or
  later. Concepts were inspected only and independently reimplemented.
- Files inspected:
  - `FreeCAD-BOM.FCMacro`
  - `README.md`

Useful techniques:

- Hardware-like BOM data is represented independently from panel geometry with
  item name, quantity, material, supplier, and other optional columns.
- CSV export uses `csv.DictWriter`.
- Empty documents produce a visible message rather than an empty success.

Limitations for Home Builder:

- Quantity display is based on repeated dictionary equality while exported data
  still contains individual rows.
- It has no panel dimensions, grain, edges, machining, or material/thickness
  summary.
- Hierarchy traversal can repeat nested objects and has no structured validation
  output.

## Selected Design

1. Consume only the canonical `ManufacturingProject`; report code has no
   Blender dependency.
2. Build immutable report rows first, then render CSV, JSON, and HTML from the
   same ordered data.
3. Consolidate parts only when category, finished dimensions, material identity,
   grain, rotation allowance, four edge treatments, face, outline, and complete
   machining semantics match. Operation IDs are source identities and therefore
   do not prevent otherwise identical machining from consolidating.
4. Preserve a sorted trace entry for every source part with cabinet ID/name,
   part ID/name, source identity, and contributed quantity.
5. Consolidate hardware separately by item name and supplier code while
   retaining hardware IDs and cabinet traceability.
6. Group material summaries by material identity and finished thickness. Keep
   missing material in an explicit unassigned group.
7. Use Python's `csv` and `json` libraries and HTML escaping for all text.
   Outputs use UTF-8, stable ordering, fixed line endings, and no timestamps.
8. Include invalid parts in detailed outputs. Combine canonical model
   validation with report-specific warnings for empty jobs, missing material,
   missing names/source identities, unknown hardware cabinets, and material
   thickness mismatches.
9. Export one deterministic report bundle to a chosen directory: detailed
   parts, material summary, hardware, validation, and a printable HTML report.
