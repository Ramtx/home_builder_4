# Manufacturing Core Research

Research was performed on 2026-06-06. All repositories were cloned under
`/tmp/hb4-research/manufacturing-core/`. No third-party source code was copied
into Home Builder; the implementation is an independent Python design based
on the project conventions and the techniques summarized below.

## OpenCutList

- Repository: https://github.com/lairdubois/lairdubois-opencutlist-sketchup-extension
- Commit: `d03f4548e161ed25615b2ea828214a79e0f3e07a`
- Licence: GNU GPL version 3
- Source inspected:
  - `ruby/model/cutlist/part_def.rb`
  - `ruby/model/cutlist/instance_info.rb`
  - `ruby/worker/cutlist/cutlist_generate_worker.rb`
  - drawing and DXF helpers under `ruby/helper/`

Useful techniques:

- Part identity combines source definition identity, evaluated dimensions,
  scale, and flipped state instead of relying on display order.
- Definition identity and instance paths are retained separately, allowing
  repeated instances to be grouped without losing source traceability.
- Finished size, cutting size, material, grain constraints, edge materials,
  face materials, and quantities are distinct fields.
- Edge data is stored by normalized axis side (`xmin`, `xmax`, `ymin`,
  `ymax`), which avoids tying manufacturing meaning to UI labels.
- Deterministic secondary ordering is applied when user-selected sort fields
  compare equal.

Limitations for Home Builder:

- It targets SketchUp components and attributes rather than evaluated Blender
  dependency-graph objects.
- Its part grouping rules are broader than the canonical one-record-per-source
  model needed by downstream Home Builder features.
- Its drawing decomposition cannot be reused directly for Blender meshes.

## FreeCAD Woodworking Workbench

- Repository: https://github.com/dprojects/Woodworking
- Commit: `364a8786d59a770a4c7feac552434b915043465f`
- Licence: MIT
- Source inspected:
  - `Tools/MagicPanels.py`
  - `Tools/getDimensions.py`
  - `Tools/grainH.py`, `Tools/grainV.py`, and `Tools/grainX.py`
  - `Tools/magicDriller.py` and `Tools/edge2drillbit.py`

Useful techniques:

- Dimension extraction prefers explicit object-type dimensions, then custom
  woodworking dimensions, then shape vertices or bounds.
- Negative extrusion lengths are normalized before reporting.
- Material/group identity and grain direction are explicit metadata rather
  than inferred only from object names.
- Drill geometry is associated with selected faces/edges and transformed into
  object coordinates before use.

Limitations for Home Builder:

- Some fallback paths return placeholder dimensions instead of structured
  failures.
- Bounding boxes are sufficient for cut-list dimensions but not for shaped
  panel contours.
- FreeCAD object types and placement semantics do not map directly to
  PyClone assembly empties.

## PyCAM

- Repository: https://github.com/SebKuzminsky/pycam
- Commit: `55e3129f518e470040e79bb00515b4bfcf36c172`
- Licence: GNU GPL version 3 or later
- Source inspected:
  - `pycam/Geometry/Polygon.py`
  - `pycam/Geometry/PolygonExtractor.py`
  - `pycam/workspace/data_models.py`
  - `pycam/Plugins/PathParameters.py`

Useful techniques:

- Polygon objects require connected, non-zero segments and explicitly track
  closed state, direction, bounds, and cached area.
- Collinear points are removed as loops are assembled.
- Inner polygons are modeled separately from outer contours.
- Machining processes retain semantic parameters such as strategy, tool size,
  depth step, overlap, and direction before toolpaths are generated.

Limitations for Home Builder:

- PyCAM is a toolpath generator; schema version 1 must stop at neutral
  machining operations and must not generate G-code.
- Its scanline polygon reconstruction is unnecessary for Blender's connected
  evaluated mesh topology.

## FreeCAD Core

- Repository: https://github.com/FreeCAD/FreeCAD
- Commit: `768e237091ff3a0af19b36aa8d15d0b867a49578`
- Licence: GNU LGPL version 2.1
- Sparse source inspected:
  - `src/Mod/Part/App/TopoShape.cpp`
  - `src/Mod/Part/App/TopoShape.h`
  - `src/Mod/Part/App/PartFeature.cpp`

Useful techniques:

- Stable source tags and element maps are kept separate from transformed
  geometry.
- Linked-object transforms are resolved before dimensions or bounds are read.
- Shape bounds are calculated with zero artificial gap and failures return an
  explicit empty result.
- Topological history is propagated when shapes are copied or transformed.

Limitations for Home Builder:

- OpenCascade topology and element-history APIs are not available in Blender.
- Home Builder needs stable assembly-level IDs, not persistent IDs for every
  mesh edge and face.

## Selected Approach

The Home Builder extractor follows the local PyClone data model first:

1. Discover evaluated base points tagged `IS_CUTPART_BP`.
2. Use source metadata or stable hierarchy paths for source IDs; hash those
   paths into typed project, cabinet, part, material, hardware, and operation
   IDs.
3. Read signed evaluated X/Y/Z dimension empties, convert metres to
   millimetres, and normalize face, edge, and coordinate orientation.
4. Prefer explicit manufacturing metadata, then Home Builder material
   pointers and edge flags, then Blender material slots.
5. Collapse prompt-driven and modifier-driven arrays into a canonical part
   quantity while extracting one un-arrayed panel contour.
6. Recover shaped outlines from the boundary edges of evaluated planar mesh
   faces, with deterministic winding and lower-left origin. Fall back to a
   rectangle only with a validation issue when evaluated geometry is unusable.
7. Translate machine tokens only when their semantic meaning is clear.
   Unsupported compound tokens remain structured warnings instead of being
   converted into misleading machine instructions.
8. Keep the model, geometry, and JSON modules free of Blender imports.
