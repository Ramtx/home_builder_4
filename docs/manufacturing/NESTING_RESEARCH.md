# Sheet Nesting Research

Research was performed on 2026-06-06. Repositories were cloned under
`/tmp/hb4-research/sheet-nesting/`. No third-party source code was copied into
Home Builder. The implementation is an independent pure-Python design informed
by the techniques below and by the local canonical manufacturing model.

## rectpack

- Repository: https://github.com/secnot/rectpack
- Commit: `123d57e0ef22adb5ae5f09b435c69f0589f521d1`
- Licence: Apache License 2.0
- Source inspected:
  - `rectpack/guillotine.py`
  - `rectpack/packer.py`
  - `rectpack/pack_algo.py`
  - guillotine, collision, packing, and rotation tests under `tests/`

Useful techniques:

- Offline packing sorts rectangles before placement, with area, perimeter,
  long-side, short-side, ratio, and insertion-order variants.
- Guillotine placement selects a free rectangle by a fitness metric and then
  applies a deterministic horizontal or vertical split.
- Best-area, best-long-side, and best-short-side fitness can be combined with
  short-axis, long-axis, leftover-axis, or area-based split choices.
- Bin factories model finite stock counts, and failed placements remain
  explicit instead of being silently dropped.
- The library includes a separate validation pass for sheet containment and
  rectangle collisions.

Limitations for Home Builder:

- Rotation is global per packer, while Home Builder needs per-part permission
  and grain alignment.
- It does not model material/thickness groups, margins, kerf, remnants, shaped
  outlines, inner cut-outs, or manufacturing export formats.
- Its generic geometry and API were not copied.

## SVGnest

- Repository: https://github.com/Jack000/SVGnest
- Commit: `1248dc21efd3f90d1aa52ba5785e27e5217ed2c9`
- Licence: MIT
- Source inspected:
  - `svgnest.js`
  - `util/placementworker.js`
  - `util/geometryutil.js`
  - bundled polygon clipping integration under `util/`

Useful techniques:

- Part spacing is applied by offsetting each outer polygon by half the spacing
  and each sheet boundary inward by half the spacing.
- Inner and outer no-fit polygons identify valid containment regions and
  collision regions for arbitrary outlines.
- No-fit polygons are cached by part identity and rotation.
- Candidate placements are evaluated at no-fit-polygon vertices and scored by
  the resulting nest bounds, with deterministic secondary position checks
  inside one worker evaluation.
- Inner loops can be treated as usable holes when the moving part fits.
- Placement results preserve translation, rotation, source identity, and
  unplaced paths for SVG rendering.

Limitations for Home Builder:

- The genetic search is intentionally non-deterministic and runs through
  browser workers.
- It permits arbitrary configured rotation counts rather than Home Builder's
  panel-oriented 0/90 degree policy and grain rules.
- The implementation depends on JavaScript clipping libraries and is much
  larger than required for deterministic cabinet-panel nesting.

## OpenCutList

- Repository:
  https://github.com/lairdubois/lairdubois-opencutlist-sketchup-extension
- Commit: `d03f4548e161ed25615b2ea828214a79e0f3e07a`
- Licence: GNU GPL version 3
- Source inspected:
  - `src/ladb_opencutlist/ruby/lib/bin_packing_2d/options.rb`
  - `src/ladb_opencutlist/ruby/lib/bin_packing_2d/box.rb`
  - `src/ladb_opencutlist/ruby/lib/bin_packing_2d/leftover.rb`
  - `src/ladb_opencutlist/ruby/lib/bin_packing_2d/bin.rb`
  - `src/ladb_opencutlist/ruby/lib/bin_packing_2d/packengine.rb`
  - `src/ladb_opencutlist/ruby/worker/cutlist/cutlist_cuttingdiagram2d_worker.rb`
  - `src/ladb_opencutlist/ruby/worker/cutlist/cutlist_cuttingdiagram2d_write_worker.rb`
  - `src/ladb_opencutlist/ruby/model/cuttingdiagram/cuttingdiagram2d.rb`

Useful techniques:

- A symmetric trim is removed from all sheet edges before packing.
- Guillotine splits consume saw kerf between the placed box and each usable
  child leftover.
- Rotation is carried per box. Grained material disables global rotation,
  while an explicit part override may permit it.
- User scrap sheets are finite bins opened before standard stock.
- Results retain packed sheets, unused sheets, leftovers, cuts, unplaced
  boxes, efficiency, and aggregate statistics.
- Cutting diagrams use stable sheet numbering and separate SVG layers for
  stock, parts, labels, leftovers, and cuts.

Limitations for Home Builder:

- The two-dimensional packer is rectangle-only and tied to SketchUp internal
  units and cut-list objects.
- Its optimizer explores many heuristic combinations and stacking modes; this
  is useful for interactive optimization but is more complex than the
  deterministic first release required here.
- Its output classes and Ruby implementation were not copied.

## Selected Implementation

Home Builder uses one `NestingOptimizer` interface with
`rectangular_guillotine` and `polygon` strategies. Both consume only
`ManufacturingProject`, expand canonical quantities, group by material and
part thickness, share finite stock inventory, and return the same result
types.

The rectangular strategy:

1. Sorts parts by decreasing outline area, decreasing longest side, stable
   part ID, and quantity instance.
2. Tests 0 and 90 degree orientations only when part rotation, the selected
   rotation policy, and stock/part grain axes permit them.
3. Selects the free rectangle with the least unused area and deterministic
   sheet/position/orientation tie breakers.
4. Uses a shorter-leftover-axis guillotine split.
5. Reserves `kerf + spacing` between neighboring parts. No clearance is
   charged at the sheet boundary, where the configured symmetric margin
   already applies.

The polygon strategy:

1. Uses canonical outer and cut-out loops directly, including polygonal
   approximations of curved parts.
2. Generates deterministic bottom-left candidates from sheet limits,
   placement bounds, and concave/cut-out vertices.
3. Checks proper edge crossings, strict filled-area containment, inner
   cut-outs, and minimum segment distance before accepting a candidate.
4. Allows another part inside a cut-out when it satisfies the same clearance.

Every result receives an independent bounds, material/thickness, overlap, and
clearance validation pass. Expected stock failures are represented as
`UnplacedPart` records with stable reasons such as `no_stock`,
`stock_exhausted`, and `part_does_not_fit_stock`. JSON and CSV are
deterministically ordered; each used sheet receives an SVG diagram with the
sheet, usable margin, exact part paths, cut-outs, labels, and stock grain.

## Benchmark

Fixture:
`tests/manufacturing/fixtures/nesting_benchmark.json`

The fixture contains 132 rectangular parts representing tall and base
cabinet sides, upper parts, shelves, doors, drawer fronts, fillers, toe kicks,
and rails. It uses 2440 x 1220 mm stock and the project defaults of 3.2 mm
kerf, 10 mm margins, and 6 mm spacing.

Measured with CPython in this workspace on 2026-06-06:

- 132 of 132 parts placed
- 16 sheets used
- 72.8146% aggregate stock-area utilization
- approximately 0.05 seconds wall-clock time
- zero overlap, clearance, material, thickness, or bounds validation errors

The benchmark test permits five seconds to avoid treating local machine speed
as a product contract. Sheet count, validity, and complete placement are the
primary regression checks.

## Algorithm Limits

- Both strategies support only 0 and 90 degree rotation. This matches panel
  grain and rectangular stock but is not a general free-angle CNC optimizer.
- The rectangular result is guillotine-compatible but does not emit a
  controller-specific cut program or G-code.
- Polygon candidate placement is deterministic and validates exact outlines,
  but it is a heuristic vertex search rather than a complete no-fit-polygon
  solver. Highly interlocking organic shapes may use more sheets than a
  stochastic industrial nesting package.
- Curves are nested at the polygon resolution supplied by the canonical
  extractor. The optimizer does not refit or simplify curves.
- Polygon validation compares placement pairs and boundary segments, so
  runtime grows with part count and outline complexity. Large free-form jobs
  should be split by material or use a future spatial index.
- Kerf and spacing are intentionally additive. Kerf represents removed tool
  width and spacing represents additional separation requested by the user.
- Remnants are rectangular stock definitions. Irregular remnant outlines are
  outside schema version 1.
