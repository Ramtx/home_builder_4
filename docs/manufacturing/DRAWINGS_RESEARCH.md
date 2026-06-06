# Manufacturing Drawings Research

Research was performed from local clones under
`/tmp/hb4-research/panel-drawings/`. Those clones and their generated
artifacts are not part of this repository. No source code was copied; the
implementation is an independent standard-library implementation against the
canonical Home Builder manufacturing model.

## ezdxf

- Repository: <https://github.com/mozman/ezdxf.git>
- Commit: `d218e93e298827a2be372b171fdeac3e9b946d78`
- Licence: MIT
- Inspected:
  - `src/ezdxf/lldxf/tagwriter.py`
  - `src/ezdxf/addons/r12writer.py`
  - `src/ezdxf/sections/headervars.py`

Useful techniques:

- Treat ASCII DXF as a deterministic stream of group-code/value pairs.
- Emit explicit sections and tables before entities when downstream software
  needs declared layers rather than relying on implicit defaults.
- Set the polyline group-code `70` closed bit instead of merely repeating the
  first vertex.
- Declare drawing units with `$INSUNITS`; millimetres use value `4`.

Limitations for Home Builder:

- ezdxf is a broad CAD dependency and is not bundled with Blender.
- Its minimal R12 writer intentionally omits header data unless additional
  tables are selected, while this feature needs explicit units and stable
  operation layers.

Selected approach:

- Implement the small required DXF subset directly: `HEADER`, `TABLES`, and
  `ENTITIES`, AC1015 `LWPOLYLINE` and `CIRCLE` entities, fixed numeric
  precision, millimetre units, and sorted semantic layers.

## OpenCutList

- Repository:
  <https://github.com/lairdubois/lairdubois-opencutlist-sketchup-extension.git>
- Commit: `d03f4548e161ed25615b2ea828214a79e0f3e07a`
- Licence: GPL-3.0
- Inspected:
  - `src/ladb_opencutlist/ruby/helper/part_drawing_helper.rb`
  - `src/ladb_opencutlist/ruby/worker/common/common_drawing_projection_worker.rb`
  - `src/ladb_opencutlist/ruby/helper/svg_writer_helper.rb`
  - `src/ladb_opencutlist/ruby/helper/dxf_writer_helper.rb`

Useful techniques:

- Normalize projected geometry to a stable origin before serialization.
- Separate outer paths, holes, open paths, and depth-sensitive operations
  before writing any particular output format.
- Give SVGs physical dimensions and a matching `viewBox`.
- Keep operation meaning in stable layer identifiers and write closed DXF
  polylines with the closed flag.
- Sort depth/path layers deliberately so machining marks remain visible over
  the panel outline.

Limitations for Home Builder:

- Projection depends on SketchUp geometry and the Clipper-backed `Clippy`
  pipeline, so it cannot consume the Home Builder canonical model directly.
- Its full DXF writer includes blocks, handles, annotations, and application
  metadata beyond the panel-machine interchange required here.
- Drawing labels and dimensions are tied to OpenCutList's part model and UI.

Selected approach:

- Preserve the separation of canonical geometry from output formatting, but
  use the already-normalized `Part` outline and machining operations. Use
  operation type plus face for DXF layers, and render the same geometry into
  a page-oriented primitive list shared by SVG and PDF.

## CairoSVG

- Repository: <https://github.com/Kozea/CairoSVG.git>
- Commit: `0613641fda46cae8bb1a77b90f0c9bbf2e56094f`
- Licence: LGPL-3.0
- Inspected:
  - `cairosvg/helpers.py`
  - `cairosvg/surface.py`
  - `cairosvg/path.py`
  - `cairosvg/parser.py`

Useful techniques:

- Resolve physical output dimensions independently from SVG user-space
  coordinates.
- Fit content using a uniform scale and centred translation, equivalent to
  `preserveAspectRatio="xMidYMid meet"`.
- Use a vector PDF surface so lines and text do not become page-sized
  bitmaps.
- Finalize each output surface explicitly after drawing.

Limitations for Home Builder:

- CairoSVG requires Cairo and its Python bindings, which are not guaranteed
  in Blender's bundled Python.
- Conversion produces one PDF surface from SVG input but does not assemble
  the indexed, multi-page manufacturing document required here.
- General SVG parsing and CSS support are unnecessary for primitives created
  internally by Home Builder.

Selected approach:

- Render an internal vector-page model directly to SVG and PDF 1.4 using only
  the Python standard library and PDF base fonts. The PDF uses one content
  stream per index/panel page. The legacy assembly-view command embeds
  Blender's opaque RGB PNG renders as PDF image objects, also without
  ReportLab, Cairo, a browser, or an external service.

## Resulting Design

- Validate flattening and machining before creating an output directory.
- Group manufacturing-equivalent parts and aggregate quantity while retaining
  all stable source part IDs, names, and cabinet names.
- Generate one human-readable SVG and one machine-oriented DXF for each unique
  supported panel.
- Generate a deterministic landscape A4 PDF with index pages followed by
  panel pages.
- Reject extractor fallback outlines, mismatched bounds, unknown machining
  faces, incomplete operations, and out-of-bounds geometry instead of
  inventing plausible files.
