from manufacturing.geometry import rectangle_outline
from manufacturing.model import (
    Cabinet,
    GrainDirection,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
    StockDefinition,
)


def make_part(
    part_id,
    length=100,
    width=50,
    *,
    material_id="material-a",
    thickness=18,
    quantity=1,
    rotation_allowed=True,
    grain=GrainDirection.NONE,
    outline=None,
    name=None,
):
    outline = outline or rectangle_outline(length, width)
    return Part(
        id=part_id,
        source_id=f"source-{part_id}",
        cabinet_id="cabinet-a",
        name=name or part_id,
        category=PartCategory.CUSTOM,
        quantity=quantity,
        material_id=material_id,
        length_mm=length,
        width_mm=width,
        thickness_mm=thickness,
        outline=outline,
        rotation_allowed=rotation_allowed,
        grain=grain,
    )


def make_project(parts, *, materials=None, stock=None):
    materials = materials or (Material("material-a", "Board A", 18),)
    stock = (
        (StockDefinition("stock", "Stock", 2440, 1220),)
        if stock is None
        else tuple(stock)
    )
    return ManufacturingProject(
        project_id="project-a",
        name="Project",
        cabinets=(
            Cabinet(
                "cabinet-a",
                "Cabinet",
                "source-cabinet",
                tuple(part.id for part in parts),
            ),
        ),
        parts=tuple(parts),
        materials=tuple(materials),
        stock=stock,
    )
