"""Extract the canonical manufacturing model from an evaluated Blender scene."""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

try:
    import bpy
except ModuleNotFoundError:  # pragma: no cover - exercised by non-Blender callers.
    bpy = None

from .geometry import (
    AxisNormalization,
    Point2D,
    Polygon2D,
    normalize_polygon_origin,
    polygon_from_loops,
    rectangle_outline,
)
from .model import (
    Cabinet,
    EdgeBanding,
    Face,
    GrainDirection,
    HardwareItem,
    IssueSeverity,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
    Transform,
    ValidationIssue,
    stable_id,
)


METRES_TO_MM = 1000.0
DIMENSION_EPSILON_MM = 0.001
OUTLINE_TOLERANCE_MM = 0.1

EXCLUDED_ANCESTOR_TAGS = {
    "IS_APPLIANCE_BP",
    "IS_DIMENSION",
    "IS_ANNOTATION",
    "IS_2D_ANNOTATION",
    "IS_DECORATION",
    "IS_DECORATION_BP",
    "IS_REFERENCE",
    "IS_OPENING_BP",
}

EXCLUDED_OBJECT_TAGS = EXCLUDED_ANCESTOR_TAGS | {"IS_WALL_BP"}

CABINET_TAGS = {
    "IS_CABINET_BP",
    "IS_CLOSET_BP",
    "IS_CLOSET_INSIDE_CORNER_BP",
    "IS_BASE_BP",
}

HARDWARE_TAGS = {
    "IS_HARDWARE",
    "IS_HARDWARE_BP",
    "IS_CABINET_HANDLE",
    "IS_CABINET_HANDLE_BP",
    "IS_HANGING_ROD_BP",
    "IS_WIRE_BASKET_BP",
    "IS_METAL_SHOE_SHELF_FENCE_BP",
}

FACE_INDEX = {
    1: Face.TOP,
    2: Face.BOTTOM,
    3: Face.LEFT,
    4: Face.RIGHT,
    5: Face.FRONT,
    6: Face.BACK,
}

EDGE_INDEX = {
    1: Face.LEFT,
    2: Face.RIGHT,
    3: Face.FRONT,
    4: Face.BACK,
    5: Face.TOP,
    6: Face.BOTTOM,
}

EDGE_SLOT_TO_FACE = {
    "L1": Face.BACK,
    "L2": Face.FRONT,
    "W1": Face.LEFT,
    "W2": Face.RIGHT,
}

EDGE_SLOT_TO_FLAG = {
    "L1": "ebl1",
    "L2": "ebl2",
    "W1": "ebw1",
    "W2": "ebw2",
}


def extract_scene(scene: Any | None = None) -> ManufacturingProject:
    """Extract a deterministic manufacturing project from a Blender scene."""
    if bpy is None:
        raise RuntimeError("manufacturing extraction requires Blender's bpy module")

    scene = scene or bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    depsgraph.update()

    project_source = bpy.data.filepath or f"unsaved:{scene.name}"
    project_id = stable_id("project", project_source)
    project_name = Path(bpy.data.filepath).stem if bpy.data.filepath else scene.name

    project_issues: list[ValidationIssue] = []
    materials: dict[str, Material] = {}
    cabinets: dict[str, dict[str, Any]] = {}
    parts: list[Part] = []
    hardware, hardware_cabinets = _extract_hardware(scene)

    for cabinet_id, cabinet_bp in hardware_cabinets.items():
        cabinets[cabinet_id] = _cabinet_record(
            scene,
            cabinet_bp,
            cabinet_bp,
            cabinet_id,
        )

    part_bps = sorted(
        (obj for obj in scene.objects if _tag(obj, "IS_CUTPART_BP")),
        key=_hierarchy_path,
    )
    for bp in part_bps:
        if _is_excluded(bp) or _is_suppressed(bp):
            continue
        part, material, cabinet_bp, issues = _extract_part(scene, depsgraph, bp)
        project_issues.extend(issues)
        if part is None:
            continue
        parts.append(part)
        if material is not None:
            materials[material.id] = material

        cabinet_id = part.cabinet_id
        if cabinet_id not in cabinets:
            cabinets[cabinet_id] = _cabinet_record(scene, cabinet_bp, bp, cabinet_id)
        cabinets[cabinet_id]["part_ids"].append(part.id)

    cabinet_models = tuple(
        Cabinet(
            id=cabinet_id,
            name=record["name"],
            source_id=record["source_id"],
            part_ids=tuple(record["part_ids"]),
            room_name=record["room_name"],
            wall_name=record["wall_name"],
            transform=record["transform"],
        )
        for cabinet_id, record in cabinets.items()
    )

    project = ManufacturingProject(
        project_id=project_id,
        name=project_name,
        source_path=bpy.data.filepath or None,
        cabinets=cabinet_models,
        parts=tuple(parts),
        materials=tuple(materials.values()),
        hardware=hardware,
        issues=tuple(project_issues),
    )
    return project.with_validation_issues()


def _extract_part(
    scene: Any,
    depsgraph: Any,
    bp: Any,
) -> tuple[Part | None, Material | None, Any | None, tuple[ValidationIssue, ...]]:
    source_id = _source_identity(bp)
    part_id = stable_id("part", source_id)
    issues: list[ValidationIssue] = []

    signed_dimensions = _assembly_dimensions_mm(bp, depsgraph)
    if signed_dimensions is None:
        issues.append(
            _issue(
                IssueSeverity.ERROR,
                "extractor.missing_dimensions",
                "Cut part is missing one or more PyClone dimension objects",
                source_id,
            )
        )
        return None, None, None, tuple(issues)

    normalization = AxisNormalization.from_signed_dimensions(*signed_dimensions)
    if min(normalization.length_mm, normalization.width_mm, normalization.thickness_mm) <= DIMENSION_EPSILON_MM:
        issues.append(
            _issue(
                IssueSeverity.ERROR,
                "extractor.invalid_dimensions",
                "Cut part has a zero evaluated dimension",
                source_id,
                dimensions_mm=tuple(abs(value) for value in signed_dimensions),
            )
        )
        return None, None, None, tuple(issues)

    cabinet_bp = _find_cabinet(bp)
    if cabinet_bp is None:
        cabinet_source = _source_identity(_fallback_cabinet_root(bp))
        issues.append(
            _issue(
                IssueSeverity.WARNING,
                "extractor.missing_cabinet",
                "Cut part has no tagged cabinet ancestor; a synthetic cabinet was created",
                source_id,
            )
        )
    else:
        cabinet_source = _source_identity(cabinet_bp)
    cabinet_id = stable_id("cabinet", cabinet_source)

    meshes = tuple(_iter_part_meshes(bp))
    name = _part_name(bp)
    category = _part_category(bp, name)
    quantity = _part_quantity(bp, meshes)
    grain = _grain_direction(bp)
    rotation_allowed = _rotation_allowed(bp, grain)
    material, material_issues = _part_material(scene, bp, meshes, normalization.thickness_mm)
    issues.extend(material_issues)
    edge_banding = _edge_banding(scene, bp, meshes, normalization)

    try:
        outline = _explicit_outline(bp, normalization)
    except (KeyError, TypeError, ValueError) as error:
        outline = None
        issues.append(
            _issue(
                IssueSeverity.WARNING,
                "extractor.invalid_explicit_outline",
                f"Explicit manufacturing outline could not be parsed: {error}",
                source_id,
            )
        )
    if outline is None:
        try:
            outline = _mesh_outline(bp, meshes, depsgraph, normalization)
        except ValueError as error:
            outline = None
            issues.append(
                _issue(
                    IssueSeverity.WARNING,
                    "extractor.outline_fallback",
                    f"Evaluated outline could not be extracted: {error}",
                    source_id,
                )
            )
    if outline is None:
        outline = rectangle_outline(normalization.length_mm, normalization.width_mm)
    elif (
        outline.width > normalization.length_mm + OUTLINE_TOLERANCE_MM
        or outline.height > normalization.width_mm + OUTLINE_TOLERANCE_MM
    ):
        issues.append(
            _issue(
                IssueSeverity.ERROR,
                "extractor.outline_out_of_bounds",
                "Evaluated outline exceeds the normalized assembly dimensions",
                source_id,
                outline_bounds_mm=(outline.width, outline.height),
                dimensions_mm=(normalization.length_mm, normalization.width_mm),
            )
        )

    machining, machining_issues = _machining_operations(meshes, normalization, part_id)
    issues.extend(machining_issues)

    face = _normalized_face(
        normalization,
        _parse_face(_first_property(bp, ("MANUFACTURING_FACE", "manufacturing_face")), Face.TOP),
    )
    part = Part(
        id=part_id,
        source_id=source_id,
        cabinet_id=cabinet_id,
        name=name,
        category=category,
        quantity=quantity,
        material_id=material.id if material else None,
        length_mm=normalization.length_mm,
        width_mm=normalization.width_mm,
        thickness_mm=normalization.thickness_mm,
        outline=outline,
        rotation_allowed=rotation_allowed,
        grain=grain,
        edge_banding=edge_banding,
        face=face,
        machining=machining,
        issues=tuple(issues),
    )
    return part, material, cabinet_bp, tuple(issues)


def _assembly_dimensions_mm(bp: Any, depsgraph: Any) -> tuple[float, float, float] | None:
    dimensions: list[float] = []
    evaluated_bp = bp.evaluated_get(depsgraph)
    scale = evaluated_bp.matrix_world.to_scale()
    for axis, tag_name in enumerate(("obj_x", "obj_y", "obj_z")):
        dimension_obj = next((child for child in bp.children if _tag(child, tag_name)), None)
        if dimension_obj is None:
            return None
        evaluated = dimension_obj.evaluated_get(depsgraph)
        dimensions.append(float(evaluated.location[axis]) * abs(float(scale[axis])) * METRES_TO_MM)
    return tuple(dimensions)  # type: ignore[return-value]


def _part_name(bp: Any) -> str:
    explicit = _first_property(
        bp,
        ("MANUFACTURING_NAME", "PART_NAME", "part_name", "CUTLIST_NAME"),
    )
    if explicit:
        return str(explicit).strip()
    cabinet_props = getattr(bp, "hb_cabinet", None)
    cabinet_part_name = getattr(cabinet_props, "part_name", "")
    if cabinet_part_name:
        return str(cabinet_part_name).strip()
    return bp.name


def _part_category(bp: Any, name: str) -> PartCategory:
    explicit = _first_property(bp, ("MANUFACTURING_CATEGORY", "PART_CATEGORY", "part_category"))
    if explicit:
        normalized = str(explicit).strip().lower().replace(" ", "_")
        try:
            return PartCategory(normalized)
        except ValueError:
            pass

    tag_categories = (
        (("IS_LEFT_SIDE_BP", "IS_RIGHT_SIDE_BP", "IS_PANEL_BP", "IS_CLOSET_PARTITION_BP"), PartCategory.CARCASS_SIDE),
        (("IS_TOP_BP",), PartCategory.TOP),
        (("IS_BOTTOM_BP", "IS_FIXED_L_SHELF_BP"), PartCategory.BOTTOM),
        (("IS_BACK_BP", "IS_CLOSET_BACK_BP"), PartCategory.BACK),
        (("IS_SHELF_BP", "IS_ADJ_SHELF", "IS_SLANTED_SHOE_SHELF"), PartCategory.SHELF),
        (("IS_LEFT_FILLER_BP", "IS_RIGHT_FILLER_BP"), PartCategory.FILLER),
        (("IS_DRAWER_FRONT_BP",), PartCategory.DRAWER_FRONT),
        (("IS_DRAWER_PART_BP",), PartCategory.DRAWER_PART),
        (("IS_DOOR_FRONT_BP", "IS_DOOR_BP"), PartCategory.DOOR),
        (("IS_TOE_KICK_BP",), PartCategory.TOE_KICK),
        (("IS_COUNTERTOP_BP",), PartCategory.COUNTERTOP),
    )
    for tags, category in tag_categories:
        if any(_tag(bp, tag) for tag in tags):
            return category

    lowered = name.lower()
    name_categories = (
        ("drawer front", PartCategory.DRAWER_FRONT),
        ("door", PartCategory.DOOR),
        ("shelf", PartCategory.SHELF),
        ("left side", PartCategory.CARCASS_SIDE),
        ("right side", PartCategory.CARCASS_SIDE),
        ("back", PartCategory.BACK),
        ("bottom", PartCategory.BOTTOM),
        ("top", PartCategory.TOP),
        ("filler", PartCategory.FILLER),
        ("toe kick", PartCategory.TOE_KICK),
        ("countertop", PartCategory.COUNTERTOP),
    )
    for fragment, category in name_categories:
        if fragment in lowered:
            return category
    return PartCategory.CUSTOM


def _part_quantity(bp: Any, meshes: Sequence[Any]) -> int:
    explicit = _first_property(bp, ("MANUFACTURING_QUANTITY", "manufacturing_quantity"))
    if explicit is not None:
        return max(1, int(explicit))

    quantities: dict[str, int] = {}
    prompt_names = (
        ("x", "X Quantity"),
        ("y", "Y Quantity"),
        ("z", "Z Quantity"),
        ("generic", "Quantity"),
    )
    for key, prompt_name in prompt_names:
        value = _prompt_value(bp, prompt_name)
        if value is not None:
            quantities[key] = max(1, int(value))

    modifier_quantities: dict[str, int] = {}
    for mesh in meshes:
        for modifier in mesh.modifiers:
            if modifier.type != "ARRAY" or not modifier.show_viewport:
                continue
            name_tokens = set(
                modifier.name.lower().replace("_", " ").replace("-", " ").split()
            )
            key = next(
                (axis for axis in ("x", "y", "z") if axis in name_tokens),
                "generic",
            )
            modifier_quantities[key] = max(
                modifier_quantities.get(key, 1),
                max(1, int(modifier.count)),
            )

    generic_modifier_count = modifier_quantities.pop("generic", 1)
    for key, count in modifier_quantities.items():
        quantities[key] = max(quantities.get(key, 1), count)

    # A generic Blender Array modifier commonly implements an axis-specific
    # PyClone quantity prompt. Treat it as corroborating the prompt rather than
    # as an independent array, otherwise a quantity of N becomes N squared.
    prompt_and_named_modifier_count = math.prod(quantities.values()) if quantities else 1
    return max(1, prompt_and_named_modifier_count, generic_modifier_count)


def _grain_direction(bp: Any) -> GrainDirection:
    value = _first_property(
        bp,
        ("MANUFACTURING_GRAIN", "GRAIN_DIRECTION", "grain_direction", "GRAIN"),
    )
    if value is None:
        return GrainDirection.NONE
    normalized = str(value).strip().lower()
    aliases = {
        "none": GrainDirection.NONE,
        "x": GrainDirection.NONE,
        "length": GrainDirection.LENGTH,
        "long": GrainDirection.LENGTH,
        "horizontal": GrainDirection.LENGTH,
        "width": GrainDirection.WIDTH,
        "vertical": GrainDirection.WIDTH,
    }
    return aliases.get(normalized, GrainDirection.NONE)


def _rotation_allowed(bp: Any, grain: GrainDirection) -> bool:
    value = _first_property(
        bp,
        ("MANUFACTURING_ROTATION_ALLOWED", "ROTATION_ALLOWED", "rotation_allowed"),
    )
    return bool(value) if value is not None else grain == GrainDirection.NONE


def _part_material(
    scene: Any,
    bp: Any,
    meshes: Sequence[Any],
    thickness_mm: float,
) -> tuple[Material | None, tuple[ValidationIssue, ...]]:
    source_id = _source_identity(bp)
    issues: list[ValidationIssue] = []
    explicit_name = _first_property(
        bp,
        ("MANUFACTURING_MATERIAL", "MATERIAL_NAME", "material_name"),
    )
    supplier_code = _first_property(
        bp,
        ("MANUFACTURING_SUPPLIER_CODE", "SUPPLIER_CODE", "supplier_code"),
    )
    export_name = _first_property(
        bp,
        ("MANUFACTURING_EXPORT_MATERIAL", "EXPORT_MATERIAL", "export_material"),
    )

    material_name = str(explicit_name).strip() if explicit_name else ""
    if not material_name:
        for mesh in meshes:
            pointers = _pointer_slots(mesh)
            for index, pointer in enumerate(pointers):
                role = pointer["name"].lower()
                if role not in {"top", "bottom", "interior", "surface"}:
                    continue
                material_name = _resolved_pointer_material(scene, pointer["pointer_name"])
                if not material_name and index < len(mesh.material_slots):
                    material = mesh.material_slots[index].material
                    material_name = material.name if material else ""
                if material_name:
                    break
            if not material_name:
                for slot in mesh.material_slots:
                    if slot.material:
                        material_name = slot.material.name
                        break
            if material_name:
                break

    if not material_name:
        issues.append(
            _issue(
                IssueSeverity.WARNING,
                "extractor.missing_material",
                "No manufacturing material or material slot could be resolved",
                source_id,
            )
        )
        return None, tuple(issues)

    material_id = stable_id("material", material_name, thickness_mm, supplier_code or "")
    return (
        Material(
            id=material_id,
            name=material_name,
            thickness_mm=thickness_mm,
            grain=_grain_direction(bp),
            supplier_code=str(supplier_code) if supplier_code else None,
            export_name=str(export_name) if export_name else None,
        ),
        tuple(issues),
    )


def _edge_banding(
    scene: Any,
    bp: Any,
    meshes: Sequence[Any],
    normalization: AxisNormalization,
) -> EdgeBanding:
    explicit = {
        Face.FRONT: _first_property(bp, ("EDGE_FRONT", "edge_front")),
        Face.BACK: _first_property(bp, ("EDGE_BACK", "edge_back")),
        Face.LEFT: _first_property(bp, ("EDGE_LEFT", "edge_left")),
        Face.RIGHT: _first_property(bp, ("EDGE_RIGHT", "edge_right")),
    }
    source_edges: dict[Face, str | None] = {
        face: str(value) if value not in (None, "", False) else None
        for face, value in explicit.items()
    }

    cabinet_props = getattr(bp, "hb_cabinet", None)
    for mesh in meshes:
        for pointer in _pointer_slots(mesh):
            slot_name = pointer["name"].upper()
            if slot_name not in EDGE_SLOT_TO_FACE:
                continue
            pointer_name = pointer["pointer_name"]
            resolved = _resolved_pointer_material(scene, pointer_name)
            treatment = resolved or pointer_name or None
            flag_name = EDGE_SLOT_TO_FLAG[slot_name]
            is_flagged = bool(getattr(cabinet_props, flag_name, False)) if cabinet_props else False
            pointer_indicates_edge = "edge" in pointer_name.lower() and "unfinished" not in pointer_name.lower()
            if treatment and (is_flagged or pointer_indicates_edge):
                source_edges[EDGE_SLOT_TO_FACE[slot_name]] = treatment

    normalized: dict[str, str | None] = {"front": None, "back": None, "left": None, "right": None}
    for source_face, treatment in source_edges.items():
        target = normalization.edge(source_face.value)
        if target in normalized:
            normalized[target] = treatment
    return EdgeBanding(**normalized)


def _explicit_outline(bp: Any, normalization: AxisNormalization) -> Polygon2D | None:
    value = _first_property(bp, ("MANUFACTURING_OUTLINE", "manufacturing_outline"))
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    points = tuple(normalization.point(float(point[0]), float(point[1])) for point in value)

    cutouts_value = _first_property(bp, ("MANUFACTURING_CUTOUTS", "manufacturing_cutouts")) or ()
    if isinstance(cutouts_value, str):
        cutouts_value = json.loads(cutouts_value)
    cutouts = tuple(
        tuple(normalization.point(float(point[0]), float(point[1])) for point in loop)
        for loop in cutouts_value
    )
    return normalize_polygon_origin(Polygon2D(points, cutouts))


def _mesh_outline(
    bp: Any,
    meshes: Sequence[Any],
    depsgraph: Any,
    normalization: AxisNormalization,
) -> Polygon2D | None:
    loops: list[tuple[Point2D, ...]] = []
    for mesh in meshes:
        loops.extend(_mesh_boundary_loops(bp, mesh, depsgraph, normalization))
    if not loops:
        return None
    return polygon_from_loops(loops)


def _mesh_boundary_loops(
    bp: Any,
    mesh_obj: Any,
    depsgraph: Any,
    normalization: AxisNormalization,
) -> tuple[tuple[Point2D, ...], ...]:
    with _single_part_modifiers(mesh_obj):
        depsgraph.update()
        evaluated = mesh_obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            transform = bp.matrix_world.inverted_safe() @ evaluated.matrix_world
            normal_matrix = transform.to_3x3().inverted_safe().transposed()
            plane_faces: dict[float, list[Any]] = defaultdict(list)
            plane_areas: Counter[float] = Counter()
            for polygon in mesh.polygons:
                normal = (normal_matrix @ polygon.normal).normalized()
                if abs(normal.z) < 0.9:
                    continue
                vertices = [transform @ mesh.vertices[index].co for index in polygon.vertices]
                plane = round(sum(vertex.z for vertex in vertices) / len(vertices), 6)
                area = abs(
                    sum(
                        vertices[index].x * vertices[(index + 1) % len(vertices)].y
                        - vertices[(index + 1) % len(vertices)].x * vertices[index].y
                        for index in range(len(vertices))
                    )
                    / 2
                )
                if area <= 1e-12:
                    continue
                plane_faces[plane].append(polygon)
                plane_areas[plane] += area
            if not plane_faces:
                raise ValueError(f"{mesh_obj.name} has no planar panel face")

            selected_plane = max(plane_faces, key=lambda plane: (plane_areas[plane], plane))
            edge_counts: Counter[tuple[int, int]] = Counter()
            for polygon in plane_faces[selected_plane]:
                indices = tuple(polygon.vertices)
                for index, vertex_index in enumerate(indices):
                    edge = tuple(sorted((vertex_index, indices[(index + 1) % len(indices)])))
                    edge_counts[edge] += 1

            boundary_edges = tuple(edge for edge, count in edge_counts.items() if count == 1)
            if not boundary_edges:
                raise ValueError(f"{mesh_obj.name} has no closed panel boundary")
            index_loops = _trace_boundary_loops(boundary_edges)
            result = []
            for loop in index_loops:
                points = []
                for vertex_index in loop:
                    coordinate = transform @ mesh.vertices[vertex_index].co
                    points.append(
                        normalization.signed_point(
                            coordinate.x * METRES_TO_MM,
                            coordinate.y * METRES_TO_MM,
                        )
                    )
                result.append(tuple(points))
            return tuple(result)
        finally:
            evaluated.to_mesh_clear()


def _trace_boundary_loops(edges: Sequence[tuple[int, int]]) -> tuple[tuple[int, ...], ...]:
    adjacency: dict[int, list[int]] = defaultdict(list)
    unused = {tuple(sorted(edge)) for edge in edges}
    for first, second in unused:
        adjacency[first].append(second)
        adjacency[second].append(first)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ValueError("panel boundary is non-manifold")

    loops: list[tuple[int, ...]] = []
    while unused:
        first_edge = min(unused)
        start, current = first_edge
        previous = start
        loop = [start]
        unused.remove(first_edge)
        while current != start:
            loop.append(current)
            candidates = [neighbor for neighbor in adjacency[current] if neighbor != previous]
            if not candidates:
                raise ValueError("panel boundary is open")
            next_vertex = candidates[0]
            edge = tuple(sorted((current, next_vertex)))
            if edge not in unused and next_vertex != start:
                raise ValueError("panel boundary branches or repeats")
            unused.discard(edge)
            previous, current = current, next_vertex
        loops.append(tuple(loop))
    return tuple(loops)


@contextmanager
def _single_part_modifiers(mesh_obj: Any) -> Iterator[None]:
    changed: list[tuple[Any, bool, bool]] = []
    for modifier in mesh_obj.modifiers:
        if modifier.type not in {"ARRAY", "BEVEL"}:
            continue
        changed.append((modifier, modifier.show_viewport, modifier.show_render))
        modifier.show_viewport = False
        modifier.show_render = False
    try:
        yield
    finally:
        for modifier, show_viewport, show_render in changed:
            modifier.show_viewport = show_viewport
            modifier.show_render = show_render


def _machining_operations(
    meshes: Sequence[Any],
    normalization: AxisNormalization,
    part_id: str,
) -> tuple[tuple[MachiningOperation, ...], tuple[ValidationIssue, ...]]:
    operations: list[MachiningOperation] = []
    issues: list[ValidationIssue] = []
    token_index = 0
    for mesh in meshes:
        for modifier in mesh.modifiers:
            if modifier.type != "NODES" or modifier.node_group is None:
                continue
            token_name = modifier.node_group.name
            if "PCMT_" not in token_name:
                continue
            token_type = token_name.split("PCMT_", 1)[1].split(".", 1)[0]
            inputs = _node_inputs(modifier)
            operation_id = stable_id("operation", part_id, mesh.name, modifier.name, token_index)
            token_index += 1
            converted, token_issues = _convert_token(
                token_type,
                inputs,
                normalization,
                operation_id,
                part_id,
            )
            operations.extend(converted)
            issues.extend(token_issues)
    return (
        tuple(sorted(operations, key=MachiningOperation.sort_key)),
        tuple(sorted(issues, key=ValidationIssue.sort_key)),
    )


def _convert_token(
    token_type: str,
    inputs: dict[str, Any],
    normalization: AxisNormalization,
    operation_id: str,
    part_id: str,
) -> tuple[tuple[MachiningOperation, ...], tuple[ValidationIssue, ...]]:
    issues: list[ValidationIssue] = []
    supported_tokens = {
        "Line_Bore",
        "Cutout",
        "3_Sided_Notch",
        "Corner_Notch",
        "Dado",
        "Shelf_Holes",
    }
    if token_type not in supported_tokens:
        issues.append(
            _issue(
                IssueSeverity.WARNING,
                "extractor.unsupported_machine_token",
                f"Machine token {token_type!r} is not supported by schema version 1",
                part_id,
            )
        )
        return (), tuple(issues)

    source_face = _parse_face(inputs.get("Face Name"), Face.UNKNOWN)
    face = _normalized_face(normalization, source_face)
    if source_face == Face.UNKNOWN and token_type not in {"Dado"}:
        issues.append(
            _issue(
                IssueSeverity.WARNING,
                "extractor.unknown_machining_face",
                f"{token_type} has no recognized face designation",
                part_id,
            )
        )

    if token_type == "Line_Bore":
        start = normalization.point(_mm_input(inputs, "X"), _mm_input(inputs, "Y"))
        end = normalization.point(_mm_input(inputs, "End X"), _mm_input(inputs, "End Y"))
        return (
            (
                MachiningOperation(
                    id=operation_id,
                    operation_type=MachiningType.LINE_BORE,
                    face=face,
                    x_mm=start.x,
                    y_mm=start.y,
                    end_x_mm=end.x,
                    end_y_mm=end.y,
                    diameter_mm=abs(_mm_input(inputs, "Diameter")),
                    depth_mm=abs(_mm_input(inputs, "Z")),
                    spacing_mm=abs(_mm_input(inputs, "Distance Between Holes")),
                ),
            ),
            tuple(issues),
        )

    if token_type in {"Cutout", "3_Sided_Notch"}:
        start = normalization.point(_mm_input(inputs, "X"), _mm_input(inputs, "Y"))
        end = normalization.point(_mm_input(inputs, "End X"), _mm_input(inputs, "End Y"))
        minimum_x, maximum_x = sorted((start.x, end.x))
        minimum_y, maximum_y = sorted((start.y, end.y))
        path = (
            (minimum_x, minimum_y),
            (maximum_x, minimum_y),
            (maximum_x, maximum_y),
            (minimum_x, maximum_y),
        )
        depth_name = "Route Depth" if token_type == "Cutout" else "Z"
        return (
            (
                MachiningOperation(
                    id=operation_id,
                    operation_type=MachiningType.CONTOUR_CUTOUT,
                    face=face,
                    x_mm=start.x,
                    y_mm=start.y,
                    end_x_mm=end.x,
                    end_y_mm=end.y,
                    depth_mm=abs(_mm_input(inputs, depth_name)),
                    path=path,
                    parameters=(("token_type", token_type),),
                ),
            ),
            tuple(issues),
        )

    if token_type == "Corner_Notch":
        start = normalization.point(_mm_input(inputs, "X"), _mm_input(inputs, "Y"))
        return (
            (
                MachiningOperation(
                    id=operation_id,
                    operation_type=MachiningType.CONTOUR_CUTOUT,
                    face=face,
                    x_mm=start.x,
                    y_mm=start.y,
                    depth_mm=abs(_mm_input(inputs, "Route Depth")),
                    parameters=(
                        ("corner", int(inputs.get("Corner Name", 0))),
                        ("lead_in_out_mm", abs(_mm_input(inputs, "Lead In Out"))),
                        ("token_type", token_type),
                    ),
                ),
            ),
            tuple(issues),
        )

    if token_type == "Dado":
        edge = _parse_edge(inputs.get("Edge Name"))
        if edge == Face.UNKNOWN:
            issues.append(
                _issue(
                    IssueSeverity.WARNING,
                    "extractor.unknown_machining_edge",
                    "Dado has no recognized edge designation",
                    part_id,
                )
            )
            return (), tuple(issues)
        normalized_edge = _normalized_face(normalization, edge)
        lead_in = abs(_mm_input(inputs, "Lead In"))
        lead_out = abs(_mm_input(inputs, "Lead Out"))
        if normalized_edge in {Face.FRONT, Face.BACK}:
            y = 0.0 if normalized_edge == Face.BACK else normalization.width_mm
            start = Point2D(lead_in, y)
            end = Point2D(max(lead_in, normalization.length_mm - lead_out), y)
        else:
            x = 0.0 if normalized_edge == Face.LEFT else normalization.length_mm
            start = Point2D(x, lead_in)
            end = Point2D(x, max(lead_in, normalization.width_mm - lead_out))
        return (
            (
                MachiningOperation(
                    id=operation_id,
                    operation_type=MachiningType.GROOVE,
                    face=Face.TOP,
                    x_mm=start.x,
                    y_mm=start.y,
                    end_x_mm=end.x,
                    end_y_mm=end.y,
                    depth_mm=abs(_mm_input(inputs, "Panel Penetration")),
                    width_mm=abs(_mm_input(inputs, "Dado Thickness")),
                    parameters=(
                        ("beginning_depth_mm", abs(_mm_input(inputs, "Beginning Depth"))),
                        ("edge", normalized_edge.value),
                        ("lock_joint_depths_mm", abs(_mm_input(inputs, "Lock Joint Depths"))),
                    ),
                ),
            ),
            tuple(issues),
        )

    if token_type == "Shelf_Holes":
        bottom = abs(_mm_input(inputs, "Space From Bottom"))
        top = abs(_mm_input(inputs, "Space From Top"))
        end_y = max(bottom, normalization.width_mm - top)
        rows = (
            _mm_input(inputs, "First Row Dim"),
            _mm_input(inputs, "Second Row Dim"),
        )
        result = []
        for index, row in enumerate(rows, start=1):
            start = normalization.point(row, bottom)
            end = normalization.point(row, end_y)
            result.append(
                MachiningOperation(
                    id=f"{operation_id}-{index}",
                    operation_type=MachiningType.LINE_BORE,
                    face=face,
                    x_mm=start.x,
                    y_mm=start.y,
                    end_x_mm=end.x,
                    end_y_mm=end.y,
                    diameter_mm=abs(_mm_input(inputs, "Face Bore Dia")),
                    depth_mm=abs(_mm_input(inputs, "Face Bore Depth")),
                    spacing_mm=abs(_mm_input(inputs, "Shelf Hole Space")),
                    parameters=(
                        ("reverse_direction", bool(inputs.get("Reverse Direction", False))),
                        ("row_spacing_mm", abs(_mm_input(inputs, "Row Spacing"))),
                    ),
                )
            )
        return tuple(result), tuple(issues)

    raise AssertionError(f"unhandled supported machine token: {token_type}")


def _node_inputs(modifier: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", "") != "INPUT" or item.name == "Geometry":
            continue
        values[item.name] = modifier.get(item.identifier, getattr(item, "default_value", None))
    return values


def _mm_input(inputs: dict[str, Any], name: str) -> float:
    value = inputs.get(name, 0.0)
    return float(value or 0.0) * METRES_TO_MM


def _parse_face(value: Any, default: Face = Face.UNKNOWN) -> Face:
    if isinstance(value, Face):
        return value
    if isinstance(value, str):
        try:
            return Face(value.strip().lower())
        except ValueError:
            try:
                return FACE_INDEX.get(int(value), default)
            except ValueError:
                return default
    if isinstance(value, (int, float)):
        return FACE_INDEX.get(int(value), default)
    return default


def _parse_edge(value: Any) -> Face:
    if isinstance(value, str):
        try:
            return Face(value.strip().lower())
        except ValueError:
            try:
                return EDGE_INDEX.get(int(value), Face.UNKNOWN)
            except ValueError:
                return Face.UNKNOWN
    if isinstance(value, (int, float)):
        return EDGE_INDEX.get(int(value), Face.UNKNOWN)
    return Face.UNKNOWN


def _normalized_face(normalization: AxisNormalization, face: Face) -> Face:
    return Face(normalization.face(face.value))


def _find_cabinet(obj: Any) -> Any | None:
    current = obj.parent
    while current is not None:
        if any(_tag(current, tag) for tag in CABINET_TAGS):
            return current
        current = current.parent
    return None


def _fallback_cabinet_root(obj: Any) -> Any:
    current = obj
    candidate = obj
    while current.parent is not None:
        current = current.parent
        if _tag(current, "IS_ASSEMBLY_BP") and not _tag(current, "IS_CUTPART_BP"):
            candidate = current
    return candidate


def _cabinet_record(
    scene: Any,
    cabinet_bp: Any | None,
    part_bp: Any,
    cabinet_id: str,
) -> dict[str, Any]:
    source = cabinet_bp or _fallback_cabinet_root(part_bp)
    wall = _find_ancestor(source, {"IS_WALL_BP"})
    room = _find_ancestor(source, {"IS_ROOM_BP"})
    return {
        "id": cabinet_id,
        "name": source.name,
        "source_id": _source_identity(source),
        "part_ids": [],
        "room_name": room.name if room else None,
        "wall_name": wall.name if wall else None,
        "transform": _object_transform(source),
    }


def _object_transform(obj: Any) -> Transform:
    matrix = obj.matrix_world
    translation = tuple(float(value) * METRES_TO_MM for value in matrix.to_translation())
    rotation = tuple(math.degrees(float(value)) for value in matrix.to_euler())
    scale = tuple(float(value) for value in matrix.to_scale())
    return Transform(translation, rotation, scale)


def _extract_hardware(
    scene: Any,
) -> tuple[tuple[HardwareItem, ...], dict[str, Any]]:
    hardware: list[HardwareItem] = []
    cabinets: dict[str, Any] = {}
    for obj in sorted(scene.objects, key=_hierarchy_path):
        if not any(_tag(obj, tag) for tag in HARDWARE_TAGS):
            continue
        if _is_suppressed(obj) or _is_excluded(obj):
            continue
        supplier_code = _first_property(obj, ("SUPPLIER_CODE", "supplier_code"))
        quantity = _first_property(obj, ("MANUFACTURING_QUANTITY", "QUANTITY", "quantity")) or 1
        cabinet = _find_cabinet(obj)
        cabinet_id = stable_id("cabinet", _source_identity(cabinet)) if cabinet else None
        if cabinet_id is not None:
            cabinets[cabinet_id] = cabinet
        source_id = _source_identity(obj)
        hardware.append(
            HardwareItem(
                id=stable_id("hardware", source_id),
                name=str(_first_property(obj, ("HARDWARE_NAME", "ITEM_NAME")) or obj.name),
                quantity=max(1, int(quantity)),
                supplier_code=str(supplier_code) if supplier_code else None,
                cabinet_id=cabinet_id,
            )
        )
    return tuple(hardware), cabinets


def _is_excluded(obj: Any) -> bool:
    if any(_tag(obj, tag) for tag in EXCLUDED_OBJECT_TAGS):
        return True

    current = obj.parent
    while current is not None:
        if any(_tag(current, tag) for tag in EXCLUDED_ANCESTOR_TAGS):
            return True
        current = current.parent
    return False


def _is_suppressed(bp: Any) -> bool:
    explicit = _first_property(bp, ("MANUFACTURING_SUPPRESSED", "SUPPRESS", "suppressed"))
    if explicit:
        return True
    hidden_prompt = _prompt_value(bp, "Hide")
    if hidden_prompt is not None and bool(hidden_prompt):
        return True
    if _object_hidden(bp):
        return True
    meshes = tuple(_iter_part_meshes(bp))
    return bool(meshes) and all(_object_hidden(mesh) for mesh in meshes)


def _object_hidden(obj: Any) -> bool:
    if bool(getattr(obj, "hide_render", False)) or bool(
        getattr(obj, "hide_viewport", False)
    ):
        return True
    hide_get = getattr(obj, "hide_get", None)
    return bool(hide_get()) if hide_get is not None else False


def _iter_part_meshes(bp: Any) -> Iterator[Any]:
    def visit(obj: Any) -> Iterator[Any]:
        for child in obj.children:
            if child is not bp and _tag(child, "IS_ASSEMBLY_BP"):
                continue
            if child.type == "MESH":
                yield child
            else:
                yield from visit(child)

    yield from visit(bp)


def _find_ancestor(obj: Any, tags: set[str]) -> Any | None:
    current = obj.parent
    while current is not None:
        if any(_tag(current, tag) for tag in tags):
            return current
        current = current.parent
    return None


def _prompt_value(bp: Any, name: str) -> Any | None:
    holders = [bp]
    holders.extend(child for child in bp.children if _tag(child, "obj_prompts"))
    for holder in holders:
        pyclone = getattr(holder, "pyclone", None)
        prompts = getattr(pyclone, "prompts", None)
        if prompts is not None:
            prompt = prompts.get(name)
            if prompt is not None:
                return prompt.get_value()

        raw = _id_property_dict(holder, "pyclone")
        for prompt in raw.get("prompts", ()):
            if prompt.get("name") != name:
                continue
            prompt_type = int(prompt.get("prompt_type", -1))
            value_names = {
                0: "float_value",
                1: "distance_value",
                2: "angle_value",
                3: "quantity_value",
                4: "percentage_value",
                5: "checkbox_value",
                6: "combobox_index",
                7: "text_value",
            }
            return prompt.get(value_names.get(prompt_type, ""))
    return None


def _pointer_slots(obj: Any) -> tuple[dict[str, str], ...]:
    pyclone = getattr(obj, "pyclone", None)
    pointers = getattr(pyclone, "pointers", None)
    if pointers is not None:
        return tuple(
            {
                "name": str(pointer.name),
                "pointer_name": str(pointer.pointer_name),
            }
            for pointer in pointers
        )
    raw = _id_property_dict(obj, "pyclone")
    return tuple(
        {
            "name": str(pointer.get("name", "")),
            "pointer_name": str(pointer.get("pointer_name", "")),
        }
        for pointer in raw.get("pointers", ())
    )


def _resolved_pointer_material(scene: Any, pointer_name: str) -> str:
    if not pointer_name:
        return ""
    scene_props = getattr(scene, "home_builder", None)
    pointers = getattr(scene_props, "material_pointers", None)
    if pointers is not None:
        pointer = pointers.get(pointer_name)
        if pointer is not None and pointer.material_name:
            return str(pointer.material_name)
    return ""


def _id_property_dict(obj: Any, key: str) -> dict[str, Any]:
    try:
        value = obj.get(key)
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if isinstance(value, dict):
            return value
    except (AttributeError, TypeError):
        pass
    return {}


def _first_property(obj: Any, names: Iterable[str]) -> Any | None:
    for name in names:
        try:
            if name in obj:
                return obj[name]
        except TypeError:
            pass
    return None


def _tag(obj: Any, name: str) -> bool:
    try:
        return name in obj and bool(obj[name])
    except (TypeError, AttributeError):
        return False


def _source_identity(obj: Any) -> str:
    if obj is None:
        return ""
    explicit = _first_property(
        obj,
        (
            "MANUFACTURING_ID",
            "HB_MANUFACTURING_ID",
            "SOURCE_ID",
            "ASSET_ID",
            "UUID",
        ),
    )
    if explicit:
        return str(explicit)
    blend_path = bpy.data.filepath if bpy is not None else ""
    library_path = obj.library.filepath if getattr(obj, "library", None) else ""
    return f"{blend_path or '<unsaved>'}|{library_path}|{_hierarchy_path(obj)}"


def _hierarchy_path(obj: Any) -> str:
    names = []
    current = obj
    while current is not None:
        names.append(current.name)
        current = current.parent
    return "/".join(reversed(names))


def _issue(
    severity: IssueSeverity,
    code: str,
    message: str,
    source_id: str,
    **details: Any,
) -> ValidationIssue:
    return ValidationIssue(
        severity,
        code,
        message,
        source_id,
        tuple(details.items()),
    )
