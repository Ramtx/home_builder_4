from __future__ import annotations

from dataclasses import replace

from manufacturing.geometry import (
    AxisNormalization,
    Point2D,
    Polygon2D,
    rectangle_outline,
    transform_polygon,
)
from manufacturing.model import (
    Cabinet,
    EdgeBanding,
    Face,
    GrainDirection,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
)


MATERIAL_ID = "material-white-18"


def operation(
    operation_id: str,
    operation_type: MachiningType,
    *,
    face: Face = Face.TOP,
    **kwargs,
) -> MachiningOperation:
    return MachiningOperation(
        id=operation_id,
        operation_type=operation_type,
        face=face,
        **kwargs,
    )


def make_part(
    part_id: str,
    name: str,
    *,
    cabinet_id: str = "cabinet-a",
    quantity: int = 1,
    length_mm: float = 500,
    width_mm: float = 300,
    outline: Polygon2D | None = None,
    grain: GrainDirection = GrainDirection.NONE,
    machining: tuple[MachiningOperation, ...] = (),
    edge_banding: EdgeBanding | None = None,
    issues=(),
) -> Part:
    return Part(
        id=part_id,
        source_id=f"source-{part_id}",
        cabinet_id=cabinet_id,
        name=name,
        category=PartCategory.CUSTOM,
        quantity=quantity,
        material_id=MATERIAL_ID,
        length_mm=length_mm,
        width_mm=width_mm,
        thickness_mm=18,
        outline=outline or rectangle_outline(length_mm, width_mm),
        grain=grain,
        edge_banding=edge_banding
        or EdgeBanding(
            front="1 mm ABS",
            back="0.4 mm ABS",
            left="1 mm ABS",
            right=None,
        ),
        machining=machining,
        issues=issues,
    )


def make_project(parts: tuple[Part, ...]) -> ManufacturingProject:
    cabinet_parts: dict[str, list[str]] = {}
    for part in parts:
        cabinet_parts.setdefault(part.cabinet_id, []).append(part.id)
    cabinets = tuple(
        Cabinet(
            cabinet_id,
            f"Cabinet {cabinet_id.rsplit('-', 1)[-1].upper()}",
            f"source-{cabinet_id}",
            tuple(part_ids),
        )
        for cabinet_id, part_ids in cabinet_parts.items()
    )
    return ManufacturingProject(
        project_id="project-panel-drawings",
        name="Panel Drawing Test Project",
        cabinets=cabinets,
        parts=parts,
        materials=(Material(MATERIAL_ID, "White Melamine", 18),),
    )


def required_panel_parts() -> tuple[Part, ...]:
    rectangular = make_part(
        "part-01-rectangular",
        "Rectangular Shelf",
        quantity=2,
    )
    duplicate = replace(
        rectangular,
        id="part-02-duplicate",
        source_id="source-part-02-duplicate",
        cabinet_id="cabinet-b",
        name="Matching Shelf",
        quantity=3,
    )
    drilled = make_part(
        "part-03-drilled",
        "Drilled Side",
        machining=(
            operation(
                "op-through",
                MachiningType.THROUGH_HOLE,
                x_mm=40,
                y_mm=40,
                diameter_mm=5,
            ),
            operation(
                "op-blind",
                MachiningType.BLIND_HOLE,
                face=Face.BOTTOM,
                x_mm=80,
                y_mm=40,
                diameter_mm=8,
                depth_mm=12,
            ),
            operation(
                "op-line-bore",
                MachiningType.LINE_BORE,
                x_mm=120,
                y_mm=50,
                end_x_mm=120,
                end_y_mm=146,
                diameter_mm=5,
                depth_mm=12,
                spacing_mm=32,
            ),
        ),
    )
    grooved = make_part(
        "part-04-grooved",
        "Grooved Back",
        machining=(
            operation(
                "op-groove",
                MachiningType.GROOVE,
                x_mm=20,
                y_mm=0,
                end_x_mm=480,
                end_y_mm=0,
                width_mm=8,
                depth_mm=6,
                parameters=(("edge", Face.BACK.value),),
            ),
        ),
    )
    pocketed = make_part(
        "part-05-pocketed",
        "Pocketed Door",
        outline=Polygon2D(
            rectangle_outline(500, 300).outer,
            (
                (
                    Point2D(400, 220),
                    Point2D(440, 220),
                    Point2D(440, 260),
                    Point2D(400, 260),
                ),
            ),
        ),
        machining=(
            operation(
                "op-pocket",
                MachiningType.POCKET,
                x_mm=180,
                y_mm=100,
                depth_mm=5,
                path=((180, 100), (320, 100), (320, 180), (180, 180)),
            ),
            operation(
                "op-contour",
                MachiningType.CONTOUR_CUTOUT,
                x_mm=40,
                y_mm=210,
                depth_mm=18,
                path=((40, 210), (100, 210), (100, 260), (40, 260)),
            ),
        ),
    )
    notched_outline = Polygon2D(
        (
            Point2D(0, 0),
            Point2D(500, 0),
            Point2D(500, 200),
            Point2D(420, 200),
            Point2D(420, 300),
            Point2D(0, 300),
        )
    )
    notched = make_part(
        "part-06-notched",
        "Notched Filler",
        outline=notched_outline,
    )
    mirrored = make_part(
        "part-07-mirrored",
        "Mirrored Notched Filler",
        outline=transform_polygon(
            notched_outline,
            AxisNormalization.from_signed_dimensions(-500, 300, 18),
        ),
    )
    curved = make_part(
        "part-08-curved",
        "Curved End Panel",
        outline=Polygon2D(
            (
                Point2D(0, 0),
                Point2D(500, 0),
                Point2D(500, 220),
                Point2D(492.4, 258.3),
                Point2D(470.7, 285.4),
                Point2D(438.3, 300),
                Point2D(0, 300),
            )
        ),
    )
    grain_sensitive = make_part(
        "part-09-grain-width",
        "Width Grain Panel",
        grain=GrainDirection.WIDTH,
    )
    return (
        rectangular,
        duplicate,
        drilled,
        grooved,
        pocketed,
        notched,
        mirrored,
        curved,
        grain_sensitive,
    )
