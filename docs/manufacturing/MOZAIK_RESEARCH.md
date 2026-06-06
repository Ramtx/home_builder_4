# Mozaik-Oriented Export Research

Research performed 2026-06-06. Public repositories were cloned under
`/tmp/hb4-research/mozaik-export/` and inspected at the exact commits below.
No source code was copied into Home Builder; the implementation is an
independent, small exporter over the canonical manufacturing model.

## Verified Mozaik Evidence

The public Cadmate support article
[How to import DXF files into Mozaik](https://cadmate.helpjuice.com/en_AU/faqs/how-to-import-dxf-files-into-mozaik)
states that Mozaik's Shape Editor is available from the Parts tab and offers
DXF import/export for cabinet, part, and profile shapes. This verifies a
manual panel-shape DXF trial path.

The research did **not** find a lawful public specification for:

- a native `.moz` project format;
- a Mozaik optimizer CSV schema;
- a Mozaik optimizer XML schema;
- layer names that Mozaik guarantees to interpret as machining operations;
- an automated project import that preserves all Home Builder machining.

Consequently, the exporter does not write `.moz` or XML, does not call its CSV
a native Mozaik format, and does not claim automatic machining import. The
manifest calls the CSV neutral optimizer data and requires field mapping plus
an external import trial. DXF layers and operation status are stable Home
Builder conventions, not asserted Mozaik conventions.

## Public Repositories

### OpenCutList

- URL: <https://github.com/lairdubois/lairdubois-opencutlist-sketchup-extension>
- Commit: `d03f4548e161ed25615b2ea828214a79e0f3e07a`
- Licence: GPL-3.0
- Inspected:
  - `part_def.rb` derives repeatable part keys from group, source identity,
    normalized dimensions, and orientation state.
  - `cutlist_export_worker.rb` uses a real CSV library, supports selectable
    delimiters and encodings, and reports export errors.
  - `dxf_writer_helper.rb` declares `$INSUNITS`, defines layers, and writes
    closed `LWPOLYLINE` geometry.
- Technique selected: deterministic production signatures, retained source
  links, structured CSV writing, explicit units, and named operation layers.
- Limitation: it targets SketchUp/OpenCutList, not Mozaik. Its GPL code was
  treated as design evidence only and was not reused.

### Fusion 360 Export Cutlist

- URL: <https://github.com/bluekeyes/Fusion360-ExportCutlist>
- Commit: `009a7a0fc24aaaee030413d166b54706a2ec9d44`
- Licence: MIT
- Inspected:
  - `lib/cutlist.py` groups repeated bodies by dimensions within a configured
    tolerance and optionally by material while retaining occurrence paths.
  - `lib/format.py` uses Python's `csv.DictWriter`.
  - Its Cutlist Optimizer adapter uses common fields such as `Length`,
    `Width`, `Qty`, `Material`, `Label`, and `Enabled`.
- Technique selected: aggregate duplicate quantities without discarding
  source part IDs, and use standard CSV quoting.
- Limitation: the documented Cutlist Optimizer importer is delimiter-fragile
  and the repository has no Mozaik contract. Home Builder therefore preserves
  commas and Unicode with standards-compliant quoting and labels its expanded
  schema as neutral.

### ezdxf

- URL: <https://github.com/mozman/ezdxf>
- Commit: `d218e93e298827a2be372b171fdeac3e9b946d78`
- Licence: MIT
- Inspected:
  - `src/ezdxf/units.py` defines `$INSUNITS` value `4` as millimetres.
  - `src/ezdxf/document.py` notes that document units require DXF R2000 or
    newer.
  - `src/ezdxf/graphicsfactory.py` requires DXF R2000 for `LWPOLYLINE`.
- Technique selected: deterministic ASCII R2000 (`AC1015`), `$INSUNITS=4`,
  closed lightweight polylines, circles, text, and explicit layers.
- Limitation: ezdxf validates general DXF behavior; it does not establish
  Mozaik layer semantics.

### FreeCAD Woodworking

- URL: <https://github.com/dprojects/Woodworking>
- Commit: `364a8786d59a770a4c7feac552434b915043465f`
- Licence: MIT
- Inspected:
  - `Docs/README.md` documents material fallback from
    `ShapeMaterial.Name`, then `Label2`, then a configured default.
  - The cut-list documentation distinguishes grouping by dimensions,
    material/container, visibility, and BOM inclusion.
  - It warns that occupied-space/bounding-box approximation differs for
    rotated parts.
  - `Tools/getDimensions.py` exposes unit-specific precision.
  - `Tools/sheet2export.py` constructs CSV by string concatenation.
- Technique selected: explicit material fallback policy, unit/precision
  control, and validation rather than trusting bounding boxes.
- Limitation: its raw CSV concatenation does not quote fields, so that
  technique was explicitly rejected.

## Implemented Neutral Contract

Each export directory contains:

- `panels/panel-<signature>.dxf`: one deterministic definition per unique
  production panel;
- `optimizer-parts.csv`: UTF-8 neutral optimizer data with aggregate quantity,
  material mapping, dimensions, grain, face, and DXF link;
- `manifest.json`: project, source part, panel, file hash, material, edge,
  machining status, and compatibility metadata;
- `validation.json`: all errors and warnings, including every omitted
  operation;
- `mozaik-profile.json`: the effective editable mappings used for the export.

The stable DXF layer roles are `outline`, `cut_out`, `drill`, `groove`,
`pocket`, `annotation`, and `face`. Their actual names are profile-controlled.
These names remain outside the canonical manufacturing model.

Material resolution is profile-driven. A shop may use exact material and
thickness mappings or the default identity policy. A strict profile reports
missing mappings as errors and omits affected panels rather than inventing a
material.

## External Trial Procedure

1. Open a generated panel DXF in an independent DXF viewer and confirm
   millimetre dimensions, contours, circles, and layer visibility.
2. In Mozaik, use the Parts tab Shape Editor's documented DXF import.
3. Confirm the outer shape and cut-outs against `manifest.json`.
4. Treat drill, groove, and pocket layers as reference geometry until the
   receiving Mozaik workflow has been configured and verified.
5. Map `optimizer-parts.csv` fields in the receiving optimizer workflow;
   compare imported counts, dimensions, material names, and DXF links.
6. Review `validation.json`. Do not release a job with errors or unresolved
   omitted-operation warnings.

This procedure is an interoperability trial, not a certification of native
Mozaik project or CNC compatibility.
