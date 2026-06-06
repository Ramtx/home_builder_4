# Mandatory First Step

Explore this Home Builder 4 project yourself before doing any research or
implementation. Inspect its architecture, registration flow, Blender/PyClone
types, cabinet libraries, object tags, materials, machine tokens, drawings,
and tests so you understand how the project works from end to end. Do not
delegate exploration of this project to a subagent. You personally must read
the relevant source and base your implementation on what you find.

# Agent Task: Manufacturing Core

## Branch And Workspace

- Branch: `feature/manufacturing-core`
- Worktree: `/home/palm/Desktop/projects/home_builder_4-worktrees/manufacturing-core`
- Shared contract: `docs/manufacturing/ARCHITECTURE.md`

Commit all completed work to this branch. Do not modify another worktree.

## Objective

Build the canonical, versioned manufacturing model and the Blender extractor
that every downstream manufacturing feature will use. This is the critical
dependency for cut lists, nesting, panel drawings, and Mozaik interchange.

## Required Research

Before implementing, clone at least three relevant public cabinet,
woodworking, CAD, or manufacturing projects into:

```text
/tmp/hb4-research/manufacturing-core/
```

Inspect their source code for part identification, evaluated dimensions,
materials, edge banding, array quantities, shaped panel outlines, and
machining operations. Do not rely only on README files.

Create `docs/manufacturing/CORE_RESEARCH.md` recording repository URLs,
exact commits, licences, useful techniques, limitations, and the selected
approach. Public repositories without a compatible licence may be inspected
but their code must be independently reimplemented. Copy code only from
GPL-compatible sources and preserve attribution.

## Implementation

Create the pure-Python domain modules described in the shared architecture:

- `manufacturing/model.py`
- `manufacturing/geometry.py`
- `manufacturing/serialization.py`

Create `manufacturing/extractor.py` for Blender integration. It must:

- Discover evaluated `IS_CUTPART_BP` assemblies.
- Normalize dimensions to positive millimetres.
- Resolve stable part and cabinet IDs.
- Expand repeated/arrayed parts into quantities.
- Resolve names, categories, materials, thickness, grain, and edge data.
- Extract rectangular and shaped panel outlines.
- Translate supported machine tokens into canonical machining operations.
- Exclude suppressed, decorative, wall, appliance, and dimension objects.
- Return structured validation issues for missing or unsupported metadata.

Register only the minimum package hooks needed by downstream modules. Do not
implement cut-list, nesting, drawing, or Mozaik-specific output.

## Tests And Acceptance

Add pure-Python tests under `tests/manufacturing/` for:

- model validation and deterministic ordering
- geometry normalization
- JSON round trips and schema-version rejection
- stable IDs

Add Blender-headless tests under `tests/blender/` for representative
rectangular, repeated, and shaped parts. Tests must skip clearly when
Blender is unavailable and run under Blender 4.x when supplied.

Acceptance requires deterministic JSON, millimetre-only internal values,
positive normalized dimensions, preserved machining-face orientation,
expanded quantities, and useful validation failures. Run all available
tests and commit the implementation plus research notes.
