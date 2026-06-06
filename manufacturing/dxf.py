"""Deterministic ASCII DXF output for canonical manufacturing panels."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Sequence

from .geometry import Point2D
from .model import Face, MachiningOperation, MachiningType, Part


DXF_VERSION = "AC1015"
DXF_INSUNITS_MILLIMETRES = 4
DXF_PRECISION = 4
GEOMETRY_TOLERANCE_MM = 0.01

BASE_LAYERS = ("OUTLINE", "CUTOUT")
OPERATION_LAYER_PREFIX = {
    MachiningType.THROUGH_HOLE: "THROUGH_HOLE",
    MachiningType.BLIND_HOLE: "BLIND_HOLE",
    MachiningType.LINE_BORE: "LINE_BORE",
    MachiningType.GROOVE: "GROOVE",
    MachiningType.POCKET: "POCKET",
    MachiningType.CONTOUR_CUTOUT: "CONTOUR_CUTOUT",
}
LAYER_COLORS = {
    "OUTLINE": 7,
    "CUTOUT": 1,
    "THROUGH_HOLE": 3,
    "BLIND_HOLE": 4,
    "LINE_BORE": 5,
    "GROOVE": 30,
    "POCKET": 6,
    "CONTOUR_CUTOUT": 2,
}


class UnsupportedPanelGeometry(ValueError):
    """Raised when a panel cannot be represented without inventing geometry."""

    def __init__(self, part_id: str, reason: str):
        super().__init__(f"{part_id}: {reason}")
        self.part_id = part_id
        self.reason = reason


@dataclass(frozen=True)
class DxfEntity:
    kind: str
    layer: str
    points: tuple[Point2D, ...] = ()
    center: Point2D | None = None
    radius: float | None = None
    closed: bool = False


def _number(value: float) -> str:
    rounded = round(float(value), DXF_PRECISION)
    if rounded == -0.0:
        rounded = 0.0
    text = f"{rounded:.{DXF_PRECISION}f}".rstrip("0").rstrip(".")
    return text or "0"


def _layer_name(operation: MachiningOperation) -> str:
    prefix = OPERATION_LAYER_PREFIX[operation.operation_type]
    return f"{prefix}_{operation.face.value.upper()}"


def _point_in_panel(point: Point2D, part: Part) -> bool:
    return (
        -GEOMETRY_TOLERANCE_MM
        <= point.x
        <= part.length_mm + GEOMETRY_TOLERANCE_MM
        and -GEOMETRY_TOLERANCE_MM
        <= point.y
        <= part.width_mm + GEOMETRY_TOLERANCE_MM
    )


def _operation_path(operation: MachiningOperation) -> tuple[Point2D, ...]:
    return tuple(Point2D(x, y) for x, y in operation.path)


def line_bore_centres(operation: MachiningOperation) -> tuple[Point2D, ...]:
    """Expand a canonical line-bore operation into deterministic hole centres."""
    if operation.end_x_mm is None or operation.end_y_mm is None:
        return ()
    start = Point2D(operation.x_mm, operation.y_mm)
    end = Point2D(operation.end_x_mm, operation.end_y_mm)
    distance = math.hypot(end.x - start.x, end.y - start.y)
    if distance <= GEOMETRY_TOLERANCE_MM:
        return (start,)
    spacing = float(operation.spacing_mm or 0)
    if spacing <= 0:
        return ()
    count = int(math.floor((distance + GEOMETRY_TOLERANCE_MM) / spacing)) + 1
    dx = (end.x - start.x) / distance
    dy = (end.y - start.y) / distance
    return tuple(
        Point2D(start.x + dx * spacing * index, start.y + dy * spacing * index)
        for index in range(count)
    )


def groove_polygon(operation: MachiningOperation) -> tuple[Point2D, ...]:
    """Return the closed rectangular footprint of a straight groove."""
    if operation.end_x_mm is None or operation.end_y_mm is None:
        return ()
    width = float(operation.width_mm or 0)
    if width <= 0:
        return ()
    start = Point2D(operation.x_mm, operation.y_mm)
    end = Point2D(operation.end_x_mm, operation.end_y_mm)
    distance = math.hypot(end.x - start.x, end.y - start.y)
    if distance <= GEOMETRY_TOLERANCE_MM:
        return ()
    parameters = dict(operation.parameters)
    edge = parameters.get("edge")
    if edge == Face.BACK.value:
        return (
            start,
            end,
            Point2D(end.x, end.y + width),
            Point2D(start.x, start.y + width),
        )
    if edge == Face.FRONT.value:
        return (
            Point2D(start.x, start.y - width),
            Point2D(end.x, end.y - width),
            end,
            start,
        )
    if edge == Face.LEFT.value:
        return (
            start,
            Point2D(start.x + width, start.y),
            Point2D(end.x + width, end.y),
            end,
        )
    if edge == Face.RIGHT.value:
        return (
            Point2D(start.x - width, start.y),
            start,
            end,
            Point2D(end.x - width, end.y),
        )
    offset_x = -(end.y - start.y) * width / (distance * 2)
    offset_y = (end.x - start.x) * width / (distance * 2)
    return (
        Point2D(start.x + offset_x, start.y + offset_y),
        Point2D(end.x + offset_x, end.y + offset_y),
        Point2D(end.x - offset_x, end.y - offset_y),
        Point2D(start.x - offset_x, start.y - offset_y),
    )


def validate_part_geometry(part: Part) -> None:
    """Reject model data that cannot produce an unambiguous flattened panel."""
    unsafe_issue_codes = {
        "extractor.outline_fallback",
        "extractor.rectangular_outline_fallback",
        "extractor.unknown_machining_edge",
        "extractor.unsupported_machine_token",
    }
    unsafe_issue = next(
        (issue for issue in part.issues if issue.code in unsafe_issue_codes),
        None,
    )
    if unsafe_issue:
        raise UnsupportedPanelGeometry(
            part.id,
            f"extractor reported unsafe manufacturing data ({unsafe_issue.message})",
        )

    minimum_x, minimum_y, maximum_x, maximum_y = part.outline.bounds
    if (
        abs(minimum_x) > GEOMETRY_TOLERANCE_MM
        or abs(minimum_y) > GEOMETRY_TOLERANCE_MM
        or abs(maximum_x - part.length_mm) > GEOMETRY_TOLERANCE_MM
        or abs(maximum_y - part.width_mm) > GEOMETRY_TOLERANCE_MM
    ):
        raise UnsupportedPanelGeometry(
            part.id,
            "outline bounds do not match the finished length and width",
        )

    for loop in (part.outline.outer, *part.outline.cutouts):
        if len(loop) < 3 or any(not _point_in_panel(point, part) for point in loop):
            raise UnsupportedPanelGeometry(
                part.id,
                "outline contains an invalid or out-of-bounds closed loop",
            )

    for operation in part.machining:
        if operation.face == Face.UNKNOWN:
            raise UnsupportedPanelGeometry(
                part.id,
                f"machining operation {operation.id} has an unknown face",
            )
        layer = _layer_name(operation)
        if not layer:
            raise UnsupportedPanelGeometry(
                part.id,
                f"machining operation {operation.id} has no semantic layer",
            )

        if operation.operation_type in {
            MachiningType.THROUGH_HOLE,
            MachiningType.BLIND_HOLE,
        }:
            if not operation.diameter_mm or operation.diameter_mm <= 0:
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"hole operation {operation.id} has no positive diameter",
                )
            radius = float(operation.diameter_mm) / 2
            centre = Point2D(operation.x_mm, operation.y_mm)
            if (
                centre.x - radius < -GEOMETRY_TOLERANCE_MM
                or centre.y - radius < -GEOMETRY_TOLERANCE_MM
                or centre.x + radius > part.length_mm + GEOMETRY_TOLERANCE_MM
                or centre.y + radius > part.width_mm + GEOMETRY_TOLERANCE_MM
            ):
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"hole operation {operation.id} extends outside the panel",
                )
            if (
                operation.operation_type == MachiningType.BLIND_HOLE
                and (operation.depth_mm is None or operation.depth_mm <= 0)
            ):
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"blind-hole operation {operation.id} has no positive depth",
                )
        elif operation.operation_type == MachiningType.LINE_BORE:
            centres = line_bore_centres(operation)
            radius = float(operation.diameter_mm or 0) / 2
            if (
                not operation.diameter_mm
                or operation.diameter_mm <= 0
                or operation.depth_mm is None
                or operation.depth_mm <= 0
                or not centres
                or any(
                    point.x - radius < -GEOMETRY_TOLERANCE_MM
                    or point.y - radius < -GEOMETRY_TOLERANCE_MM
                    or point.x + radius
                    > part.length_mm + GEOMETRY_TOLERANCE_MM
                    or point.y + radius
                    > part.width_mm + GEOMETRY_TOLERANCE_MM
                    for point in centres
                )
            ):
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"line-bore operation {operation.id} is incomplete or out of bounds",
                )
        elif operation.operation_type == MachiningType.GROOVE:
            polygon = groove_polygon(operation)
            if (
                operation.depth_mm is None
                or operation.depth_mm <= 0
                or not polygon
                or any(not _point_in_panel(point, part) for point in polygon)
            ):
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"groove operation {operation.id} is not a supported straight groove",
                )
        elif operation.operation_type in {
            MachiningType.POCKET,
            MachiningType.CONTOUR_CUTOUT,
        }:
            path = _operation_path(operation)
            if (
                operation.depth_mm is None
                or operation.depth_mm <= 0
                or len(path) < 3
                or any(not _point_in_panel(point, part) for point in path)
            ):
                raise UnsupportedPanelGeometry(
                    part.id,
                    f"{operation.operation_type.value} operation {operation.id} "
                    "requires a closed in-bounds path",
                )
        else:  # pragma: no cover - enum construction prevents this today.
            raise UnsupportedPanelGeometry(
                part.id,
                f"unsupported machining type {operation.operation_type}",
            )


def part_entities(part: Part) -> tuple[DxfEntity, ...]:
    validate_part_geometry(part)
    entities: list[DxfEntity] = [
        DxfEntity("polyline", "OUTLINE", part.outline.outer, closed=True)
    ]
    entities.extend(
        DxfEntity("polyline", "CUTOUT", loop, closed=True)
        for loop in part.outline.cutouts
    )
    for operation in part.machining:
        layer = _layer_name(operation)
        if operation.operation_type in {
            MachiningType.THROUGH_HOLE,
            MachiningType.BLIND_HOLE,
        }:
            entities.append(
                DxfEntity(
                    "circle",
                    layer,
                    center=Point2D(operation.x_mm, operation.y_mm),
                    radius=float(operation.diameter_mm) / 2,
                )
            )
        elif operation.operation_type == MachiningType.LINE_BORE:
            entities.extend(
                DxfEntity(
                    "circle",
                    layer,
                    center=centre,
                    radius=float(operation.diameter_mm) / 2,
                )
                for centre in line_bore_centres(operation)
            )
        elif operation.operation_type == MachiningType.GROOVE:
            entities.append(
                DxfEntity(
                    "polyline",
                    layer,
                    groove_polygon(operation),
                    closed=True,
                )
            )
        else:
            entities.append(
                DxfEntity(
                    "polyline",
                    layer,
                    _operation_path(operation),
                    closed=True,
                )
            )
    return tuple(entities)


def _tags(*items: object) -> str:
    if len(items) % 2:
        raise ValueError("DXF tags require code/value pairs")
    return "".join(
        f"{items[index]}\n{items[index + 1]}\n"
        for index in range(0, len(items), 2)
    )


def _layer_color(layer: str) -> int:
    prefix = layer.rsplit("_", 1)[0]
    return LAYER_COLORS.get(layer, LAYER_COLORS.get(prefix, 7))


def _header(part: Part) -> str:
    return (
        _tags(999, "Home Builder 4 deterministic panel DXF")
        + _tags(999, f"Part ID: {part.id}")
        + _tags(0, "SECTION", 2, "HEADER")
        + _tags(9, "$ACADVER", 1, DXF_VERSION)
        + _tags(9, "$INSUNITS", 70, DXF_INSUNITS_MILLIMETRES)
        + _tags(9, "$MEASUREMENT", 70, 1)
        + _tags(9, "$EXTMIN", 10, "0", 20, "0", 30, "0")
        + _tags(
            9,
            "$EXTMAX",
            10,
            _number(part.length_mm),
            20,
            _number(part.width_mm),
            30,
            "0",
        )
        + _tags(0, "ENDSEC")
    )


def _tables(layers: Sequence[str]) -> str:
    chunks = [
        _tags(0, "SECTION", 2, "TABLES"),
        _tags(0, "TABLE", 2, "LTYPE", 70, 1),
        _tags(
            0,
            "LTYPE",
            2,
            "CONTINUOUS",
            70,
            0,
            3,
            "Solid line",
            72,
            65,
            73,
            0,
            40,
            "0",
        ),
        _tags(0, "ENDTAB"),
        _tags(0, "TABLE", 2, "LAYER", 70, len(layers)),
    ]
    for layer in layers:
        chunks.append(
            _tags(
                0,
                "LAYER",
                2,
                layer,
                70,
                0,
                62,
                _layer_color(layer),
                6,
                "CONTINUOUS",
            )
        )
    chunks.extend((_tags(0, "ENDTAB"), _tags(0, "ENDSEC")))
    return "".join(chunks)


def _polyline(entity: DxfEntity) -> str:
    chunks = [
        _tags(
            0,
            "LWPOLYLINE",
            100,
            "AcDbEntity",
            8,
            entity.layer,
            100,
            "AcDbPolyline",
            90,
            len(entity.points),
            70,
            1 if entity.closed else 0,
        )
    ]
    for point in entity.points:
        chunks.append(_tags(10, _number(point.x), 20, _number(point.y)))
    return "".join(chunks)


def _circle(entity: DxfEntity) -> str:
    assert entity.center is not None and entity.radius is not None
    return _tags(
        0,
        "CIRCLE",
        100,
        "AcDbEntity",
        8,
        entity.layer,
        100,
        "AcDbCircle",
        10,
        _number(entity.center.x),
        20,
        _number(entity.center.y),
        30,
        "0",
        40,
        _number(entity.radius),
    )


def render_part_dxf(part: Part) -> str:
    """Return one deterministic, millimetre-based ASCII DXF panel."""
    entities = part_entities(part)
    used_layers = {entity.layer for entity in entities}
    ordered_layers = tuple(
        layer
        for layer in BASE_LAYERS
        if layer in used_layers
    ) + tuple(sorted(used_layers - set(BASE_LAYERS)))
    body = "".join(
        _polyline(entity) if entity.kind == "polyline" else _circle(entity)
        for entity in entities
    )
    return (
        _header(part)
        + _tables(ordered_layers)
        + _tags(0, "SECTION", 2, "ENTITIES")
        + body
        + _tags(0, "ENDSEC", 0, "EOF")
    )


def write_part_dxf(part: Part, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_part_dxf(part), encoding="ascii", newline="\n")
    return path


__all__ = [
    "DXF_INSUNITS_MILLIMETRES",
    "DXF_VERSION",
    "DxfEntity",
    "UnsupportedPanelGeometry",
    "groove_polygon",
    "line_bore_centres",
    "part_entities",
    "render_part_dxf",
    "validate_part_geometry",
    "write_part_dxf",
]
