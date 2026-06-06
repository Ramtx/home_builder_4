# Manufacturing Architecture

## Purpose

Home Builder remains the source of truth for room and cabinet design. The
manufacturing subsystem converts the evaluated Blender scene into one
canonical, serializable project model. Cut lists, nesting, drawings, and
Mozaik interchange must consume that model rather than walking Blender
objects independently.

The first release produces manufacturing information and neutral exchange
files. It does not generate machine-specific G-code or proprietary Mozaik
project files.

## Package Boundaries

New code belongs in a top-level `manufacturing` package:

```text
manufacturing/
  __init__.py
  model.py          # Pure-Python domain types and validation issues
  geometry.py       # 2D outlines and machining geometry
  serialization.py  # Versioned JSON import/export
  extractor.py      # Blender scene to ManufacturingProject
  cutlist.py        # Cut-list and hardware reports
  nesting.py        # Sheet-stock optimization
  drawings.py       # PDF, SVG, and panel DXF
  dxf.py            # Minimal deterministic ASCII DXF writer
  mozaik.py         # Mozaik-oriented package and mapping profiles
  operators.py      # Blender operators
  props.py          # Blender project/export settings
  ui.py             # Manufacturing panel
```

Modules other than `extractor.py`, `operators.py`, `props.py`, and `ui.py`
must remain importable and testable without Blender.

## Canonical Model

All internal lengths use millimetres regardless of Blender scene units.
Serialization is deterministic: stable ordering, UTF-8, and explicit schema
versioning.

### ManufacturingProject

- `schema_version`
- `project_id`, `name`, and optional source `.blend` path
- `units`, fixed to `mm` for version 1
- ordered cabinets, parts, materials, hardware, stock definitions, and issues
- default stock: 2440 x 1220 mm
- default kerf: 3.2 mm
- default sheet margin: 10 mm
- default part spacing: 6 mm

### Cabinet

- stable `id`
- human-readable `name`
- room/wall source and world transform where available
- ordered list of part IDs

### Part

- stable `id` and source object identity
- cabinet ID, name, category, quantity, and material ID
- finished length, width, and thickness in millimetres
- rotation permission and grain direction
- closed 2D outer outline plus zero or more inner cut-outs
- edge treatment for front, back, left, and right finished edges
- face designation
- ordered machining operations
- validation issues

Part categories include carcass side, top, bottom, back, shelf, filler, door,
drawer front, drawer part, toe kick, countertop, and custom.

### MachiningOperation

Version 1 supports:

- through hole
- blind hole
- line bore
- groove/dado
- pocket
- contour cut-out

Every operation records face, coordinates, dimensions/depth, and an optional
tool hint. Coordinates use the panel's local lower-left origin after
normalization.

### Material And Stock

Materials have stable IDs, display/export names, thickness, optional grain,
and optional supplier code. Stock definitions reference a material and
provide sheet width, sheet height, quantity, cost, and remnant status.

## Blender Extraction

The extractor discovers assembly base points marked `IS_CUTPART_BP`. It must:

- Evaluate drivers and the dependency graph before reading dimensions.
- Normalize negative assembly axes while preserving machining-face meaning.
- Expand arrayed shelves or repeated parts into quantities.
- Ignore hidden/suppressed parts.
- Resolve cabinet ancestry and produce stable IDs from object data rather
  than display order.
- Prefer explicit manufacturing metadata and fall back to material slots and
  assembly dimensions.
- Extract evaluated mesh outlines for shaped parts.
- Convert machine-token node inputs into canonical machining operations when
  supported.
- Emit validation issues instead of silently dropping uncertain data.

The extractor must not treat appliances, decorative meshes, dimensions,
walls, hardware, or countertops as sheet parts unless explicitly tagged.
Hardware is collected separately when metadata exists.

## Output Contracts

### Cut List

Generate deterministic CSV and JSON. Rows contain part and cabinet IDs,
names, category, quantity, finished dimensions, material, grain, edge
treatments, and machining summary. A second hardware report contains item,
supplier code, and quantity. Printable HTML may be generated as an
intermediate format for PDF.

### Nesting

The optimizer groups parts by material and thickness. Rectangular
guillotine placement is required first. Polygon nesting is a second strategy
behind the same interface. Results include sheets, placements, utilization,
waste, unplaced parts, and validation issues. Every result must be checked
for overlap and sheet-bound violations before export.

### Drawings

Produce an indexed PDF booklet and one SVG plus one ASCII DXF per unique
panel. Drawings show outline, dimensions, material, thickness, quantity,
grain, edge labels, face, holes, grooves, pockets, and cut-outs. Unsupported
geometry appears in the validation report and never receives a misleading
machine file.

### Mozaik Interchange

Create a directory containing one DXF per panel, optimizer-oriented CSV,
optional XML when a verified schema is available, a material mapping file,
manifest JSON, and validation report. Part IDs link every row and file.
Version 1 does not write `.moz` files.

## Research And Licensing

Each feature agent clones at least three relevant public repositories under
`/tmp/hb4-research/<feature>/` and records:

- repository URL and exact commit
- detected licence
- implementation techniques inspected
- limitations
- selected approach

Any public source may be inspected. Code may be copied only from a
GPL-compatible project, with licence notices and attribution preserved.
Ideas from incompatible or unlicensed projects must be independently
reimplemented. Research clones and downloaded artifacts are never committed.

## Testing

Pure-Python tests live under `tests/manufacturing/`. Blender integration
tests live under `tests/blender/` and run with Blender 4.x in background
mode. Fixtures must cover standard, upper, tall, drawer, stacked,
blind-corner, filler, repeated-shelf, and shaped/notched parts.

Acceptance requires:

- deterministic serialization and exports
- correct millimetre conversion and quantity expansion
- no nesting overlaps or out-of-bounds placements
- matching drawing and cut-list dimensions
- structurally valid DXF and escaped CSV/XML
- useful validation failures for incomplete or unsupported data

## Branch And Integration Rules

`integration/manufacturing` is the integration branch. Feature branches are:

- `feature/manufacturing-core`
- `feature/cut-list`
- `feature/sheet-nesting`
- `feature/panel-drawings`
- `feature/mozaik-export`

The core branch lands first. Feature branches rebase onto the core commit,
then work in parallel. Agents commit only to their assigned branch. Final
integration merges each reviewed feature into `integration/manufacturing`.
