# Mandatory First Step

Explore this Home Builder 4 project yourself before doing any research or
implementation. Inspect its architecture, registration flow, Blender/PyClone
types, cabinet libraries, object tags, materials, machine tokens, drawings,
and tests so you understand how the project works from end to end. Do not
delegate exploration of this project to a subagent. You personally must read
the relevant source and base your implementation on what you find.

# Agent Task: Manufacturing Drawings For Every Panel

## Branch And Workspace

- Branch: `feature/panel-drawings`
- Worktree: `/home/palm/Desktop/projects/home_builder_4-worktrees/panel-drawings`
- Shared contract: `docs/manufacturing/ARCHITECTURE.md`
- Dependency: completed `feature/manufacturing-core`

Rebase onto the approved manufacturing-core commit first. Drawing code must
consume the canonical model and remain testable without Blender.

## Objective

Generate a complete, indexed human-readable manufacturing booklet and
machine-readable vector files for every supported unique panel.

## Required Research

Clone at least three public technical-drawing, woodworking, CAD, PDF, SVG,
or DXF projects into:

```text
/tmp/hb4-research/panel-drawings/
```

Inspect source implementations for panel flattening, annotations, dimension
placement, machining symbols, PDF assembly, SVG, and DXF writing. Record
URLs, exact commits, licences, useful techniques, limitations, and selected
approach in `docs/manufacturing/DRAWINGS_RESEARCH.md`.

Public repositories may be inspected regardless of licence. Copy code only
from GPL-compatible sources with attribution.

## Implementation

Implement:

- `manufacturing/dxf.py` for deterministic ASCII DXF
- `manufacturing/drawings.py` for SVG panels and an indexed PDF booklet

Each panel drawing must include:

- stable part ID, cabinet/name, quantity, material, thickness, and face
- scaled outer outline and cut-outs
- overall dimensions
- grain arrow and four edge-band labels
- holes, line bores, grooves, pockets, and contour operations
- legend, page number, and validation notes

Generate one SVG and one DXF per unique supported panel. DXF geometry must
use millimetres, closed outlines, stable layers, and unambiguous operation
layers. Unsupported flattening must produce an error rather than a plausible
but wrong drawing.

Replace the currently unfinished PDF behavior with a Blender-compatible,
documented implementation. Avoid mandatory external services.

Add Blender operators and a Manufacturing UI section for exporting the
drawing package.

## Tests And Acceptance

Test rectangular, drilled, grooved, pocketed, notched, curved, mirrored,
grain-sensitive, and duplicate panels. Verify:

- SVG XML structure and dimensions
- required DXF sections, units, layers, and closed contours
- drawing/cut-part dimensions agree
- deterministic filenames and ordering
- PDF page count, index, and labels
- unsupported geometry is rejected

Commit implementation, tests, generated small golden fixtures, and research
notes. Do not commit large rendered artifacts.
