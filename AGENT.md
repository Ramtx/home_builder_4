# Mandatory First Step

Explore this Home Builder 4 project yourself before doing any research or
implementation. Inspect its architecture, registration flow, Blender/PyClone
types, cabinet libraries, object tags, materials, machine tokens, drawings,
and tests so you understand how the project works from end to end. Do not
delegate exploration of this project to a subagent. You personally must read
the relevant source and base your implementation on what you find.

# Agent Task: Direct Mozaik Interchange Export

## Branch And Workspace

- Branch: `feature/mozaik-export`
- Worktree: `/home/palm/Desktop/projects/home_builder_4-worktrees/mozaik-export`
- Shared contract: `docs/manufacturing/ARCHITECTURE.md`
- Dependency: completed `feature/manufacturing-core`

Rebase onto the approved manufacturing-core commit first. Build on the
canonical model and shared DXF writer when that dependency is integrated.

## Objective

Export a self-contained Mozaik-oriented manufacturing package using neutral,
documentable interchange: per-panel DXF plus optimizer part data and a
manifest. Do not claim to create native editable `.moz` projects.

## Required Research

Clone at least three relevant public cabinet exporters, DXF/CAM tools,
optimizer interchange implementations, or comparable commercial-CAD bridge
projects into:

```text
/tmp/hb4-research/mozaik-export/
```

Inspect implementation source for material mapping, part identifiers,
operation layers, CSV/XML profiles, manifests, and validation. Public
repositories without compatible licences may be inspected, but their code
must be independently reimplemented.

Record URLs, exact commits, licences, techniques, limitations, and all
verified Mozaik format evidence in
`docs/manufacturing/MOZAIK_RESEARCH.md`. Clearly separate verified behavior
from inference.

## Implementation

Implement `manufacturing/mozaik.py` with:

- configurable material/thickness name mappings
- one deterministic DXF per unique panel
- optimizer-oriented CSV
- XML only when a schema is verified from lawful public documentation or
  user-owned sample exports
- manifest JSON linking part IDs, quantities, material mappings, and files
- validation report for unsupported machining, missing mappings, duplicate
  filenames, and unsafe geometry
- profile JSON that users can edit without changing source code

Use stable, documented DXF layers for outline, cut-out, drill, groove,
pocket, annotation, and face. Keep Mozaik-specific naming separate from the
canonical domain model.

Do not download or execute cracked, leaked, or unofficial Mozaik binaries.
Do not reverse-engineer credentials, licensing, or copy protection. Any
future native-project research must be clean-room work based on files the
user is lawfully entitled to create.

Add a Blender operator and Manufacturing UI section that exports a complete
Mozaik package directory.

## Tests And Acceptance

Test:

- deterministic filenames and manifest links
- material mapping and missing-map failures
- CSV quoting, Unicode, and locale-independent decimals
- verified XML shape if XML is implemented
- DXF layer and unit requirements
- duplicate parts and quantities
- unsupported operation warnings

Acceptance requires a complete package usable for external import trials,
with no proprietary `.moz` claim and no silent data loss. Commit
implementation and research notes.
