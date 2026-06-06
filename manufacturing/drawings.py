"""Human-readable panel SVGs and a deterministic indexed PDF booklet.

The PDF writer uses only the Python standard library and PDF base fonts. This
keeps manufacturing export available in Blender's bundled Python without
ReportLab, Cairo, a browser, or an external conversion service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import struct
import unicodedata
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

from .dxf import (
    UnsupportedPanelGeometry,
    groove_polygon,
    line_bore_centres,
    validate_part_geometry,
    write_part_dxf,
)
from .geometry import Point2D
from .model import (
    Cabinet,
    GrainDirection,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
)


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NAMESPACE)

PAGE_WIDTH_MM = 297.0
PAGE_HEIGHT_MM = 210.0
PDF_POINTS_PER_MM = 72.0 / 25.4
INDEX_ROWS_PER_PAGE = 20
PACKAGE_MANIFEST_NAME = ".home_builder_drawings.json"
PACKAGE_MANIFEST_VERSION = 1


@dataclass(frozen=True)
class PanelDrawing:
    part: Part
    part_ids: tuple[str, ...]
    part_names: tuple[str, ...]
    cabinet_names: tuple[str, ...]
    quantity: int
    material_name: str
    filename_stem: str
    validation_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DrawingPackage:
    output_directory: Path
    booklet_path: Path
    svg_paths: tuple[Path, ...]
    dxf_paths: tuple[Path, ...]
    panels: tuple[PanelDrawing, ...]
    page_count: int


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: str = "#222222"
    width: float = 0.35
    dash: tuple[float, ...] = ()
    css_class: str = ""


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[float, float], ...]
    closed: bool = False
    stroke: str = "#222222"
    fill: str = "none"
    width: float = 0.35
    dash: tuple[float, ...] = ()
    css_class: str = ""
    element_id: str = ""


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    radius: float
    stroke: str = "#222222"
    fill: str = "none"
    width: float = 0.35
    css_class: str = ""
    element_id: str = ""


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    stroke: str = "#222222"
    fill: str = "none"
    line_width: float = 0.35
    css_class: str = ""


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    value: str
    size: float = 3.2
    color: str = "#222222"
    anchor: str = "start"
    bold: bool = False
    rotation: float = 0.0
    css_class: str = ""


Primitive = Line | Polyline | Circle | Rect | Text


@dataclass
class VectorPage:
    title: str
    primitives: list[Primitive] = field(default_factory=list)

    def line(self, *args, **kwargs) -> None:
        self.primitives.append(Line(*args, **kwargs))

    def polyline(self, *args, **kwargs) -> None:
        self.primitives.append(Polyline(*args, **kwargs))

    def circle(self, *args, **kwargs) -> None:
        self.primitives.append(Circle(*args, **kwargs))

    def rect(self, *args, **kwargs) -> None:
        self.primitives.append(Rect(*args, **kwargs))

    def text(self, *args, **kwargs) -> None:
        self.primitives.append(Text(*args, **kwargs))


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", ascii_value).strip("-._").lower()
    return slug or "panel"


def _operation_key(operation: MachiningOperation) -> tuple[object, ...]:
    return (
        operation.operation_type.value,
        operation.face.value,
        operation.x_mm,
        operation.y_mm,
        operation.end_x_mm,
        operation.end_y_mm,
        operation.diameter_mm,
        operation.depth_mm,
        operation.width_mm,
        operation.spacing_mm,
        operation.path,
        operation.tool_hint,
        operation.parameters,
    )


def _part_key(part: Part) -> tuple[object, ...]:
    return (
        part.length_mm,
        part.width_mm,
        part.thickness_mm,
        part.material_id,
        part.rotation_allowed,
        part.grain.value,
        tuple((point.x, point.y) for point in part.outline.outer),
        tuple(
            tuple((point.x, point.y) for point in loop)
            for loop in part.outline.cutouts
        ),
        part.edge_banding.as_tuple(),
        part.face.value,
        tuple(sorted((_operation_key(operation) for operation in part.machining))),
    )


def collect_unique_panels(project: ManufacturingProject) -> tuple[PanelDrawing, ...]:
    """Group manufacturing-equivalent panels and aggregate their quantities."""
    if project.units != "mm":
        raise ValueError("drawing export requires ManufacturingProject units in mm")

    materials: dict[str, Material] = {material.id: material for material in project.materials}
    cabinets: dict[str, Cabinet] = {cabinet.id: cabinet for cabinet in project.cabinets}
    grouped: dict[tuple[object, ...], list[Part]] = {}
    for part in project.parts:
        validate_part_geometry(part)
        grouped.setdefault(_part_key(part), []).append(part)

    panels: list[PanelDrawing] = []
    for parts in grouped.values():
        ordered_parts = tuple(sorted(parts, key=Part.sort_key))
        representative = ordered_parts[0]
        material = materials.get(representative.material_id or "")
        cabinet_names = tuple(
            sorted(
                {
                    cabinets[part.cabinet_id].name
                    if part.cabinet_id in cabinets
                    else part.cabinet_id
                    for part in ordered_parts
                }
            )
        )
        notes = tuple(
            sorted(
                {
                    f"{issue.severity.value.upper()}: {issue.message}"
                    for part in ordered_parts
                    for issue in part.issues
                }
            )
        )
        panels.append(
            PanelDrawing(
                part=representative,
                part_ids=tuple(part.id for part in ordered_parts),
                part_names=tuple(sorted({part.name for part in ordered_parts})),
                cabinet_names=cabinet_names,
                quantity=sum(part.quantity for part in ordered_parts),
                material_name=material.name if material else "Unspecified",
                filename_stem=(
                    f"{_slug(representative.name)}__{_slug(representative.id)}"
                ),
                validation_notes=notes,
            )
        )
    return tuple(sorted(panels, key=lambda panel: panel.part.id))


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(1, limit - 3)] + "..."


def _format_mm(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text} mm"


def _map_points(
    points: Iterable[Point2D],
    origin_x: float,
    origin_y: float,
    scale: float,
    panel_width: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (origin_x + point.x * scale, origin_y + (panel_width - point.y) * scale)
        for point in points
    )


def _edge_label(value: str | None) -> str:
    return value if value else "None"


def _add_arrow(
    page: VectorPage,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str,
    css_class: str,
) -> None:
    page.line(*start, *end, stroke=color, width=0.6, css_class=css_class)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy) or 1.0
    ux, uy = dx / distance, dy / distance
    px, py = -uy, ux
    tip = end
    left = (end[0] - ux * 3 + px * 1.3, end[1] - uy * 3 + py * 1.3)
    right = (end[0] - ux * 3 - px * 1.3, end[1] - uy * 3 - py * 1.3)
    page.polyline(
        (tip, left, right),
        closed=True,
        stroke=color,
        fill=color,
        width=0.3,
        css_class=css_class,
    )


def _panel_page(
    panel: PanelDrawing,
    page_number: int,
    total_pages: int,
) -> VectorPage:
    part = panel.part
    page = VectorPage(f"{part.id} - {part.name}")
    page.rect(4, 4, PAGE_WIDTH_MM - 8, PAGE_HEIGHT_MM - 8, line_width=0.45)
    page.text(10, 12, "HOME BUILDER 4 - MANUFACTURING PANEL", 5.0, bold=True)
    page.text(10, 19, f"Part ID: {part.id}", 3.1, css_class="part-id")
    page.text(
        10,
        25,
        f"Cabinet: {_truncate('; '.join(panel.cabinet_names), 75)}",
        3.1,
        css_class="cabinet-name",
    )
    page.text(
        10,
        31,
        f"Name: {_truncate('; '.join(panel.part_names), 75)}",
        3.1,
        css_class="part-name",
    )
    page.text(158, 19, f"Quantity: {panel.quantity}", 3.1, css_class="quantity")
    page.text(
        158,
        25,
        f"Material: {_truncate(panel.material_name, 42)}",
        3.1,
        css_class="material",
    )
    page.text(
        158,
        31,
        f"Thickness: {_format_mm(part.thickness_mm)}    Face: {part.face.value}",
        3.1,
        css_class="thickness-face",
    )
    page.line(8, 36, 289, 36, width=0.45)

    draw_x, draw_y, draw_width, draw_height = 35.0, 51.0, 176.0, 105.0
    scale = min(draw_width / part.length_mm, draw_height / part.width_mm)
    actual_width = part.length_mm * scale
    actual_height = part.width_mm * scale
    origin_x = draw_x + (draw_width - actual_width) / 2
    origin_y = draw_y + (draw_height - actual_height) / 2

    page.polyline(
        _map_points(part.outline.outer, origin_x, origin_y, scale, part.width_mm),
        closed=True,
        stroke="#111111",
        fill="#f7f7f7",
        width=0.65,
        css_class="panel-outline",
        element_id="panel-outline",
    )
    for index, loop in enumerate(part.outline.cutouts, start=1):
        page.polyline(
            _map_points(loop, origin_x, origin_y, scale, part.width_mm),
            closed=True,
            stroke="#c62828",
            fill="#ffffff",
            width=0.55,
            css_class="panel-cutout",
            element_id=f"panel-cutout-{index}",
        )

    def mapped(point: Point2D) -> tuple[float, float]:
        return (
            origin_x + point.x * scale,
            origin_y + (part.width_mm - point.y) * scale,
        )

    operation_colors = {
        MachiningType.THROUGH_HOLE: "#00897b",
        MachiningType.BLIND_HOLE: "#1565c0",
        MachiningType.LINE_BORE: "#6a1b9a",
        MachiningType.GROOVE: "#ef6c00",
        MachiningType.POCKET: "#ad1457",
        MachiningType.CONTOUR_CUTOUT: "#c62828",
    }
    for operation in part.machining:
        color = operation_colors[operation.operation_type]
        css_class = f"operation operation-{operation.operation_type.value}"
        if operation.operation_type in {
            MachiningType.THROUGH_HOLE,
            MachiningType.BLIND_HOLE,
        }:
            cx, cy = mapped(Point2D(operation.x_mm, operation.y_mm))
            page.circle(
                cx,
                cy,
                max(0.9, float(operation.diameter_mm) * scale / 2),
                stroke=color,
                width=0.5,
                css_class=css_class,
                element_id=operation.id,
            )
        elif operation.operation_type == MachiningType.LINE_BORE:
            centres = line_bore_centres(operation)
            if len(centres) > 1:
                page.polyline(
                    tuple(mapped(point) for point in centres),
                    stroke=color,
                    width=0.3,
                    dash=(1.5, 1.2),
                    css_class=css_class,
                )
            for index, centre in enumerate(centres, start=1):
                cx, cy = mapped(centre)
                page.circle(
                    cx,
                    cy,
                    max(0.75, float(operation.diameter_mm) * scale / 2),
                    stroke=color,
                    width=0.4,
                    css_class=css_class,
                    element_id=f"{operation.id}-{index}",
                )
        else:
            path = (
                groove_polygon(operation)
                if operation.operation_type == MachiningType.GROOVE
                else tuple(Point2D(x, y) for x, y in operation.path)
            )
            page.polyline(
                tuple(mapped(point) for point in path),
                closed=True,
                stroke=color,
                fill="none",
                width=0.55,
                dash=(2, 1) if operation.operation_type == MachiningType.POCKET else (),
                css_class=css_class,
                element_id=operation.id,
            )

    dimension_y = origin_y - 7
    page.line(origin_x, dimension_y, origin_x + actual_width, dimension_y, width=0.3)
    page.line(origin_x, dimension_y - 2, origin_x, origin_y, width=0.25)
    page.line(
        origin_x + actual_width,
        dimension_y - 2,
        origin_x + actual_width,
        origin_y,
        width=0.25,
    )
    page.text(
        origin_x + actual_width / 2,
        dimension_y - 1.5,
        _format_mm(part.length_mm),
        3.0,
        anchor="middle",
        bold=True,
        css_class="overall-dimension length-dimension",
    )
    dimension_x = origin_x - 9
    page.line(dimension_x, origin_y, dimension_x, origin_y + actual_height, width=0.3)
    page.line(dimension_x - 2, origin_y, origin_x, origin_y, width=0.25)
    page.line(
        dimension_x - 2,
        origin_y + actual_height,
        origin_x,
        origin_y + actual_height,
        width=0.25,
    )
    page.text(
        dimension_x - 2,
        origin_y + actual_height / 2,
        _format_mm(part.width_mm),
        3.0,
        anchor="middle",
        bold=True,
        rotation=-90,
        css_class="overall-dimension width-dimension",
    )

    centre_x = origin_x + actual_width / 2
    centre_y = origin_y + actual_height / 2
    if part.grain == GrainDirection.WIDTH:
        grain_start = (centre_x, centre_y + min(18, actual_height * 0.3))
        grain_end = (centre_x, centre_y - min(18, actual_height * 0.3))
        grain_text = "GRAIN - WIDTH"
    else:
        grain_start = (centre_x - min(24, actual_width * 0.3), centre_y)
        grain_end = (centre_x + min(24, actual_width * 0.3), centre_y)
        grain_text = (
            "GRAIN - LENGTH"
            if part.grain == GrainDirection.LENGTH
            else "NO GRAIN DIRECTION"
        )
    _add_arrow(
        page,
        grain_start,
        grain_end,
        color="#455a64",
        css_class="grain-arrow",
    )
    page.text(
        centre_x,
        centre_y - 3,
        grain_text,
        2.5,
        color="#455a64",
        anchor="middle",
        bold=True,
        css_class="grain-label",
    )

    page.text(
        centre_x,
        origin_y - 11.5,
        f"BACK EDGE: {_truncate(_edge_label(part.edge_banding.back), 34)}",
        2.5,
        anchor="middle",
        css_class="edge-band edge-back",
    )
    page.text(
        centre_x,
        origin_y + actual_height + 8,
        f"FRONT EDGE: {_truncate(_edge_label(part.edge_banding.front), 34)}",
        2.5,
        anchor="middle",
        css_class="edge-band edge-front",
    )
    page.text(
        origin_x - 15,
        centre_y,
        f"LEFT: {_truncate(_edge_label(part.edge_banding.left), 24)}",
        2.5,
        anchor="middle",
        rotation=-90,
        css_class="edge-band edge-left",
    )
    page.text(
        origin_x + actual_width + 6,
        centre_y,
        f"RIGHT: {_truncate(_edge_label(part.edge_banding.right), 24)}",
        2.5,
        anchor="middle",
        rotation=90,
        css_class="edge-band edge-right",
    )

    legend_x = 222.0
    page.text(legend_x, 47, "LEGEND", 3.6, bold=True, css_class="legend-title")
    legend = (
        ("Outline", "#111111"),
        ("Cut-out / contour", "#c62828"),
        ("Through hole", "#00897b"),
        ("Blind hole", "#1565c0"),
        ("Line bore", "#6a1b9a"),
        ("Groove / dado", "#ef6c00"),
        ("Pocket", "#ad1457"),
    )
    for index, (label, color) in enumerate(legend):
        y = 55 + index * 7
        page.line(legend_x, y, legend_x + 9, y, stroke=color, width=0.7)
        page.text(legend_x + 12, y + 1, label, 2.7, css_class="legend-entry")
    page.text(legend_x, 108, "MACHINING", 3.6, bold=True)
    if part.machining:
        for index, operation in enumerate(part.machining[:7]):
            details = operation.operation_type.value.replace("_", " ")
            if operation.depth_mm is not None:
                details += f", depth {_format_mm(operation.depth_mm)}"
            page.text(
                legend_x,
                115 + index * 6,
                _truncate(f"{operation.face.value}: {details}", 40),
                2.45,
                css_class="operation-label",
            )
    else:
        page.text(legend_x, 115, "None", 2.7)

    notes_y = 174.0
    page.line(8, notes_y - 5, 289, notes_y - 5, width=0.4)
    page.text(10, notes_y, "VALIDATION NOTES", 3.2, bold=True)
    notes = panel.validation_notes or ("None",)
    for index, note in enumerate(notes[:4]):
        page.text(
            10,
            notes_y + 6 + index * 5,
            _truncate(note, 125),
            2.55,
            color="#b71c1c" if note != "None" else "#333333",
            css_class="validation-note",
        )
    page.text(
        287,
        202,
        f"Page {page_number} of {total_pages}",
        2.8,
        anchor="end",
        css_class="page-number",
    )
    return page


def _index_pages(
    project: ManufacturingProject,
    panels: Sequence[PanelDrawing],
    panel_page_numbers: Sequence[int],
    total_pages: int,
) -> list[VectorPage]:
    chunks = [
        panels[index : index + INDEX_ROWS_PER_PAGE]
        for index in range(0, len(panels), INDEX_ROWS_PER_PAGE)
    ] or [()]
    number_chunks = [
        panel_page_numbers[index : index + INDEX_ROWS_PER_PAGE]
        for index in range(0, len(panel_page_numbers), INDEX_ROWS_PER_PAGE)
    ] or [()]
    pages: list[VectorPage] = []
    for page_index, (panel_chunk, number_chunk) in enumerate(
        zip(chunks, number_chunks),
        start=1,
    ):
        page = VectorPage(f"{project.name} - Drawing Index")
        page.rect(4, 4, PAGE_WIDTH_MM - 8, PAGE_HEIGHT_MM - 8, line_width=0.45)
        page.text(10, 14, "HOME BUILDER 4 - MANUFACTURING DRAWING INDEX", 5.2, bold=True)
        page.text(10, 22, f"Project: {project.name}", 3.4)
        page.text(287, 22, f"Unique panels: {len(panels)}", 3.4, anchor="end")
        columns = (10, 72, 130, 164, 224, 279)
        headers = ("Part ID", "Cabinet / Name", "Qty", "Material", "Finished Size", "Page")
        page.rect(8, 29, 281, 9, fill="#e8edf1", line_width=0.3)
        for x, header in zip(columns, headers):
            page.text(x, 35, header, 2.8, bold=True)
        row_y = 38.0
        for panel, target_page in zip(panel_chunk, number_chunk):
            row_y += 7.7
            part = panel.part
            page.line(8, row_y + 2, 289, row_y + 2, stroke="#b0bec5", width=0.2)
            values = (
                _truncate(part.id, 31),
                _truncate(
                    f"{'; '.join(panel.cabinet_names)} / {'; '.join(panel.part_names)}",
                    34,
                ),
                str(panel.quantity),
                _truncate(panel.material_name, 27),
                f"{part.length_mm:g} x {part.width_mm:g} x {part.thickness_mm:g} mm",
                str(target_page),
            )
            for x, value in zip(columns, values):
                page.text(x, row_y, value, 2.5)
        page.text(
            287,
            202,
            f"Page {page_index} of {total_pages}",
            2.8,
            anchor="end",
        )
        pages.append(page)
    return pages


def _svg_tag(name: str) -> str:
    return f"{{{SVG_NAMESPACE}}}{name}"


def _svg_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def render_panel_svg(
    panel: PanelDrawing,
    *,
    page_number: int = 1,
    total_pages: int = 1,
) -> str:
    """Render a complete human-readable SVG drawing for one unique panel."""
    page = _panel_page(panel, page_number, total_pages)
    root = ET.Element(
        _svg_tag("svg"),
        {
            "width": f"{_svg_number(PAGE_WIDTH_MM)}mm",
            "height": f"{_svg_number(PAGE_HEIGHT_MM)}mm",
            "viewBox": f"0 0 {_svg_number(PAGE_WIDTH_MM)} {_svg_number(PAGE_HEIGHT_MM)}",
            "version": "1.1",
            "data-part-id": panel.part.id,
            "data-length-mm": _svg_number(panel.part.length_mm),
            "data-width-mm": _svg_number(panel.part.width_mm),
            "data-thickness-mm": _svg_number(panel.part.thickness_mm),
        },
    )
    ET.SubElement(root, _svg_tag("title")).text = page.title
    ET.SubElement(root, _svg_tag("desc")).text = (
        "Deterministic manufacturing panel drawing generated from the "
        "Home Builder canonical manufacturing model."
    )
    for primitive in page.primitives:
        attributes: dict[str, str]
        if isinstance(primitive, Line):
            attributes = {
                "x1": _svg_number(primitive.x1),
                "y1": _svg_number(primitive.y1),
                "x2": _svg_number(primitive.x2),
                "y2": _svg_number(primitive.y2),
                "stroke": primitive.stroke,
                "stroke-width": _svg_number(primitive.width),
            }
            if primitive.dash:
                attributes["stroke-dasharray"] = " ".join(
                    _svg_number(value) for value in primitive.dash
                )
            if primitive.css_class:
                attributes["class"] = primitive.css_class
            ET.SubElement(root, _svg_tag("line"), attributes)
        elif isinstance(primitive, Polyline):
            attributes = {
                "points": " ".join(
                    f"{_svg_number(x)},{_svg_number(y)}"
                    for x, y in primitive.points
                ),
                "stroke": primitive.stroke,
                "fill": primitive.fill,
                "stroke-width": _svg_number(primitive.width),
                "stroke-linejoin": "round",
            }
            if primitive.dash:
                attributes["stroke-dasharray"] = " ".join(
                    _svg_number(value) for value in primitive.dash
                )
            if primitive.css_class:
                attributes["class"] = primitive.css_class
            if primitive.element_id:
                attributes["id"] = primitive.element_id
            tag = "polygon" if primitive.closed else "polyline"
            ET.SubElement(root, _svg_tag(tag), attributes)
        elif isinstance(primitive, Circle):
            attributes = {
                "cx": _svg_number(primitive.cx),
                "cy": _svg_number(primitive.cy),
                "r": _svg_number(primitive.radius),
                "stroke": primitive.stroke,
                "fill": primitive.fill,
                "stroke-width": _svg_number(primitive.width),
            }
            if primitive.css_class:
                attributes["class"] = primitive.css_class
            if primitive.element_id:
                attributes["id"] = primitive.element_id
            ET.SubElement(root, _svg_tag("circle"), attributes)
        elif isinstance(primitive, Rect):
            attributes = {
                "x": _svg_number(primitive.x),
                "y": _svg_number(primitive.y),
                "width": _svg_number(primitive.width),
                "height": _svg_number(primitive.height),
                "stroke": primitive.stroke,
                "fill": primitive.fill,
                "stroke-width": _svg_number(primitive.line_width),
            }
            if primitive.css_class:
                attributes["class"] = primitive.css_class
            ET.SubElement(root, _svg_tag("rect"), attributes)
        else:
            attributes = {
                "x": _svg_number(primitive.x),
                "y": _svg_number(primitive.y),
                "fill": primitive.color,
                "font-family": "Arial, Helvetica, sans-serif",
                "font-size": _svg_number(primitive.size),
                "text-anchor": primitive.anchor,
            }
            if primitive.bold:
                attributes["font-weight"] = "bold"
            if primitive.rotation:
                attributes["transform"] = (
                    f"rotate({_svg_number(primitive.rotation)} "
                    f"{_svg_number(primitive.x)} {_svg_number(primitive.y)})"
                )
            if primitive.css_class:
                attributes["class"] = primitive.css_class
            ET.SubElement(root, _svg_tag("text"), attributes).text = primitive.value

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root,
        encoding="unicode",
        short_empty_elements=True,
    ) + "\n"


def write_panel_svg(
    panel: PanelDrawing,
    destination: str | Path,
    *,
    page_number: int = 1,
    total_pages: int = 1,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_panel_svg(
            panel,
            page_number=page_number,
            total_pages=total_pages,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _pdf_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _pdf_color(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _pdf_escape(value: str) -> str:
    data = value.encode("cp1252", "replace")
    chunks: list[str] = []
    for byte in data:
        char = chr(byte)
        if char in "\\()":
            chunks.append("\\" + char)
        elif byte < 32 or byte > 126:
            chunks.append(f"\\{byte:03o}")
        else:
            chunks.append(char)
    return "".join(chunks)


def _pdf_xy(x: float, y: float) -> tuple[float, float]:
    return x * PDF_POINTS_PER_MM, (PAGE_HEIGHT_MM - y) * PDF_POINTS_PER_MM


def _pdf_path(points: Sequence[tuple[float, float]], closed: bool) -> str:
    commands: list[str] = []
    for index, (x, y) in enumerate(points):
        px, py = _pdf_xy(x, y)
        commands.append(
            f"{_pdf_number(px)} {_pdf_number(py)} {'m' if index == 0 else 'l'}"
        )
    if closed:
        commands.append("h")
    return "\n".join(commands)


def _pdf_page_stream(page: VectorPage) -> bytes:
    commands = ["1 J", "1 j"]
    for primitive in page.primitives:
        if isinstance(primitive, Text):
            r, g, b = _pdf_color(primitive.color)
            size = primitive.size * PDF_POINTS_PER_MM
            x, y = _pdf_xy(primitive.x, primitive.y)
            approximate_width = len(primitive.value) * size * 0.5
            if primitive.anchor == "middle":
                x -= approximate_width / 2
            elif primitive.anchor == "end":
                x -= approximate_width
            angle = math.radians(-primitive.rotation)
            cosine, sine = math.cos(angle), math.sin(angle)
            commands.extend(
                (
                    "BT",
                    f"/{'F2' if primitive.bold else 'F1'} {_pdf_number(size)} Tf",
                    f"{_pdf_number(r)} {_pdf_number(g)} {_pdf_number(b)} rg",
                    (
                        f"{_pdf_number(cosine)} {_pdf_number(sine)} "
                        f"{_pdf_number(-sine)} {_pdf_number(cosine)} "
                        f"{_pdf_number(x)} {_pdf_number(y)} Tm"
                    ),
                    f"({_pdf_escape(primitive.value)}) Tj",
                    "ET",
                )
            )
            continue

        stroke = primitive.stroke
        fill = primitive.fill if hasattr(primitive, "fill") else "none"
        line_width = (
            primitive.line_width
            if isinstance(primitive, Rect)
            else primitive.width
        )
        r, g, b = _pdf_color(stroke)
        commands.append(f"{_pdf_number(r)} {_pdf_number(g)} {_pdf_number(b)} RG")
        commands.append(f"{_pdf_number(line_width * PDF_POINTS_PER_MM)} w")
        dash = primitive.dash if hasattr(primitive, "dash") else ()
        if dash:
            commands.append(
                "["
                + " ".join(
                    _pdf_number(value * PDF_POINTS_PER_MM) for value in dash
                )
                + "] 0 d"
            )
        else:
            commands.append("[] 0 d")
        if fill != "none":
            fr, fg, fb = _pdf_color(fill)
            commands.append(
                f"{_pdf_number(fr)} {_pdf_number(fg)} {_pdf_number(fb)} rg"
            )

        if isinstance(primitive, Line):
            commands.append(
                _pdf_path(
                    ((primitive.x1, primitive.y1), (primitive.x2, primitive.y2)),
                    False,
                )
            )
        elif isinstance(primitive, Polyline):
            commands.append(_pdf_path(primitive.points, primitive.closed))
        elif isinstance(primitive, Rect):
            x, y = _pdf_xy(primitive.x, primitive.y + primitive.height)
            commands.append(
                f"{_pdf_number(x)} {_pdf_number(y)} "
                f"{_pdf_number(primitive.width * PDF_POINTS_PER_MM)} "
                f"{_pdf_number(primitive.height * PDF_POINTS_PER_MM)} re"
            )
        else:
            cx, cy = _pdf_xy(primitive.cx, primitive.cy)
            radius = primitive.radius * PDF_POINTS_PER_MM
            kappa = radius * 0.5522847498
            commands.extend(
                (
                    f"{_pdf_number(cx + radius)} {_pdf_number(cy)} m",
                    (
                        f"{_pdf_number(cx + radius)} {_pdf_number(cy + kappa)} "
                        f"{_pdf_number(cx + kappa)} {_pdf_number(cy + radius)} "
                        f"{_pdf_number(cx)} {_pdf_number(cy + radius)} c"
                    ),
                    (
                        f"{_pdf_number(cx - kappa)} {_pdf_number(cy + radius)} "
                        f"{_pdf_number(cx - radius)} {_pdf_number(cy + kappa)} "
                        f"{_pdf_number(cx - radius)} {_pdf_number(cy)} c"
                    ),
                    (
                        f"{_pdf_number(cx - radius)} {_pdf_number(cy - kappa)} "
                        f"{_pdf_number(cx - kappa)} {_pdf_number(cy - radius)} "
                        f"{_pdf_number(cx)} {_pdf_number(cy - radius)} c"
                    ),
                    (
                        f"{_pdf_number(cx + kappa)} {_pdf_number(cy - radius)} "
                        f"{_pdf_number(cx + radius)} {_pdf_number(cy - kappa)} "
                        f"{_pdf_number(cx + radius)} {_pdf_number(cy)} c"
                    ),
                    "h",
                )
            )
        commands.append("B" if fill != "none" else "S")
    return ("\n".join(commands) + "\n").encode("ascii")


def render_pdf(pages: Sequence[VectorPage], title: str) -> bytes:
    """Create a deterministic, uncompressed PDF 1.4 document."""
    if not pages:
        raise ValueError("PDF booklet requires at least one page")
    objects: dict[int, bytes] = {}
    page_ids = tuple(5 + index * 2 for index in range(len(pages)))
    content_ids = tuple(page_id + 1 for page_id in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids "
        f"[{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] >>"
    ).encode("ascii")
    objects[3] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    objects[4] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>"
    )
    media_width = PAGE_WIDTH_MM * PDF_POINTS_PER_MM
    media_height = PAGE_HEIGHT_MM * PDF_POINTS_PER_MM
    for page_id, content_id, page in zip(page_ids, content_ids, pages):
        stream = _pdf_page_stream(page)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {_pdf_number(media_width)} {_pdf_number(media_height)}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
    info_id = max(objects) + 1
    objects[info_id] = (
        f"<< /Title ({_pdf_escape(title)}) "
        "/Creator (Home Builder 4 Manufacturing) "
        "/Producer (Home Builder 4 deterministic PDF writer) >>"
    ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, info_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {info_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {info_id + 1} /Root 1 0 R "
            f"/Info {info_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def write_pdf(
    pages: Sequence[VectorPage],
    destination: str | Path,
    *,
    title: str,
) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_pdf(pages, title))
    return path


@dataclass(frozen=True)
class _PngImage:
    width: int
    height: int
    colors: int
    color_space: str
    compressed_pixels: bytes


def _read_pdf_png(source: str | Path) -> _PngImage:
    """Read the subset of PNG that Blender emits for opaque RGB renders."""
    data = Path(source).read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{source}: expected a PNG image")

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed_pixels = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        if len(chunk_data) != length:
            raise ValueError(f"{source}: truncated PNG chunk")
        offset += 12 + length
        if chunk_type == b"IHDR":
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filtering,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if compression != 0 or filtering != 0:
                raise ValueError(f"{source}: unsupported PNG compression or filter method")
        elif chunk_type == b"IDAT":
            compressed_pixels.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    color_spaces = {
        0: (1, "/DeviceGray"),
        2: (3, "/DeviceRGB"),
    }
    if (
        not width
        or not height
        or bit_depth != 8
        or color_type not in color_spaces
        or interlace != 0
        or not compressed_pixels
    ):
        raise ValueError(
            f"{source}: PDF export supports non-interlaced 8-bit grayscale or RGB PNG"
        )
    colors, color_space = color_spaces[color_type]
    return _PngImage(
        width,
        height,
        colors,
        color_space,
        bytes(compressed_pixels),
    )


def write_png_pdf(
    images: Sequence[str | Path],
    destination: str | Path,
    *,
    title: str,
    page_width_points: float,
    page_height_points: float,
) -> Path:
    """Write opaque Blender PNG renders to a dependency-free PDF booklet."""
    if not images:
        raise ValueError("PNG PDF requires at least one image")
    if page_width_points <= 0 or page_height_points <= 0:
        raise ValueError("PDF page dimensions must be positive")
    pngs = tuple(_read_pdf_png(image) for image in images)

    objects: dict[int, bytes] = {}
    page_ids = tuple(3 + index * 3 for index in range(len(pngs)))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = (
        f"<< /Type /Pages /Count {len(pngs)} /Kids "
        f"[{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] >>"
    ).encode("ascii")
    for page_id, image in zip(page_ids, pngs):
        content_id = page_id + 1
        image_id = page_id + 2
        scale = min(
            page_width_points / image.width,
            page_height_points / image.height,
        )
        draw_width = image.width * scale
        draw_height = image.height * scale
        draw_x = (page_width_points - draw_width) / 2
        draw_y = (page_height_points - draw_height) / 2
        stream = (
            "q\n"
            f"{_pdf_number(draw_width)} 0 0 {_pdf_number(draw_height)} "
            f"{_pdf_number(draw_x)} {_pdf_number(draw_y)} cm\n"
            "/Im0 Do\nQ\n"
        ).encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {_pdf_number(page_width_points)} "
            f"{_pdf_number(page_height_points)}] "
            f"/Resources << /XObject << /Im0 {image_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
        image_header = (
            f"<< /Type /XObject /Subtype /Image /Width {image.width} "
            f"/Height {image.height} /ColorSpace {image.color_space} "
            "/BitsPerComponent 8 /Filter /FlateDecode "
            f"/DecodeParms << /Predictor 15 /Colors {image.colors} "
            f"/BitsPerComponent 8 /Columns {image.width} >> "
            f"/Length {len(image.compressed_pixels)} >>\nstream\n"
        ).encode("ascii")
        objects[image_id] = (
            image_header + image.compressed_pixels + b"\nendstream"
        )

    info_id = max(objects) + 1
    objects[info_id] = (
        f"<< /Title ({_pdf_escape(title)}) "
        "/Creator (Home Builder 4) "
        "/Producer (Home Builder 4 deterministic PNG PDF writer) >>"
    ).encode("ascii")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, info_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {info_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {info_id + 1} /Root 1 0 R "
            f"/Info {info_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    return path


def _owned_package_paths(root: Path) -> tuple[Path, ...]:
    manifest_path = root / PACKAGE_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ()
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != PACKAGE_MANIFEST_VERSION
        or not isinstance(manifest.get("files"), list)
    ):
        return ()

    paths: list[Path] = []
    resolved_root = root.resolve()
    for value in manifest["files"]:
        if not isinstance(value, str):
            continue
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        is_booklet = relative == Path("manufacturing_booklet.pdf")
        is_svg = (
            len(relative.parts) == 2
            and relative.parts[0] == "svg"
            and relative.suffix.lower() == ".svg"
        )
        is_dxf = (
            len(relative.parts) == 2
            and relative.parts[0] == "dxf"
            and relative.suffix.lower() == ".dxf"
        )
        if not (is_booklet or is_svg or is_dxf):
            continue
        path = root / relative
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError:
            continue
        paths.append(path)
    return tuple(paths)


def _write_package_manifest(root: Path, paths: Sequence[Path]) -> Path:
    manifest_path = root / PACKAGE_MANIFEST_NAME
    relative_paths = sorted(
        path.relative_to(root).as_posix()
        for path in paths
    )
    payload = json.dumps(
        {
            "files": relative_paths,
            "version": PACKAGE_MANIFEST_VERSION,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary_path = manifest_path.with_suffix(".tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(manifest_path)
    return manifest_path


def export_drawing_package(
    project: ManufacturingProject,
    output_directory: str | Path,
) -> DrawingPackage:
    """Export one SVG and DXF per unique panel plus an indexed PDF booklet."""
    panels = collect_unique_panels(project)
    index_page_count = max(1, math.ceil(len(panels) / INDEX_ROWS_PER_PAGE))
    total_pages = index_page_count + len(panels)
    panel_page_numbers = tuple(
        index_page_count + index for index in range(1, len(panels) + 1)
    )

    # Build every page before touching the destination so unsupported geometry
    # cannot leave a plausible but incomplete package behind.
    panel_pages = [
        _panel_page(panel, page_number, total_pages)
        for panel, page_number in zip(panels, panel_page_numbers)
    ]
    index_pages = _index_pages(
        project,
        panels,
        panel_page_numbers,
        total_pages,
    )

    root = Path(output_directory)
    svg_directory = root / "svg"
    dxf_directory = root / "dxf"
    svg_directory.mkdir(parents=True, exist_ok=True)
    dxf_directory.mkdir(parents=True, exist_ok=True)
    for path in _owned_package_paths(root):
        if path.is_file():
            path.unlink()

    svg_paths: list[Path] = []
    dxf_paths: list[Path] = []
    for panel, page_number in zip(panels, panel_page_numbers):
        svg_paths.append(
            write_panel_svg(
                panel,
                svg_directory / f"{panel.filename_stem}.svg",
                page_number=page_number,
                total_pages=total_pages,
            )
        )
        dxf_paths.append(
            write_part_dxf(
                panel.part,
                dxf_directory / f"{panel.filename_stem}.dxf",
            )
        )

    booklet_path = write_pdf(
        (*index_pages, *panel_pages),
        root / "manufacturing_booklet.pdf",
        title=f"{project.name} Manufacturing Drawings",
    )
    _write_package_manifest(root, (*svg_paths, *dxf_paths, booklet_path))
    return DrawingPackage(
        output_directory=root,
        booklet_path=booklet_path,
        svg_paths=tuple(svg_paths),
        dxf_paths=tuple(dxf_paths),
        panels=panels,
        page_count=total_pages,
    )


__all__ = [
    "DrawingPackage",
    "INDEX_ROWS_PER_PAGE",
    "PACKAGE_MANIFEST_NAME",
    "PAGE_HEIGHT_MM",
    "PAGE_WIDTH_MM",
    "PanelDrawing",
    "UnsupportedPanelGeometry",
    "VectorPage",
    "collect_unique_panels",
    "export_drawing_package",
    "render_panel_svg",
    "render_pdf",
    "write_panel_svg",
    "write_pdf",
    "write_png_pdf",
]
