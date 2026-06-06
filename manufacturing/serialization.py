"""Deterministic JSON serialization for the manufacturing schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

from .geometry import Point2D, Polygon2D
from .model import (
    SCHEMA_VERSION,
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
    StockDefinition,
    Transform,
    ValidationIssue,
)


class SchemaVersionError(ValueError):
    pass


def _issue(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "source_id": issue.source_id,
        "details": dict(issue.details),
    }


def _operation(operation: MachiningOperation) -> dict[str, Any]:
    return {
        "id": operation.id,
        "operation_type": operation.operation_type.value,
        "face": operation.face.value,
        "x_mm": operation.x_mm,
        "y_mm": operation.y_mm,
        "end_x_mm": operation.end_x_mm,
        "end_y_mm": operation.end_y_mm,
        "diameter_mm": operation.diameter_mm,
        "depth_mm": operation.depth_mm,
        "width_mm": operation.width_mm,
        "spacing_mm": operation.spacing_mm,
        "path": [list(point) for point in operation.path],
        "tool_hint": operation.tool_hint,
        "parameters": dict(operation.parameters),
    }


def project_to_dict(project: ManufacturingProject) -> dict[str, Any]:
    return {
        "schema_version": project.schema_version,
        "project_id": project.project_id,
        "name": project.name,
        "source_path": project.source_path,
        "units": project.units,
        "defaults": {
            "kerf_mm": project.default_kerf_mm,
            "sheet_margin_mm": project.default_sheet_margin_mm,
            "part_spacing_mm": project.default_part_spacing_mm,
        },
        "cabinets": [
            {
                "id": cabinet.id,
                "name": cabinet.name,
                "source_id": cabinet.source_id,
                "part_ids": list(cabinet.part_ids),
                "room_name": cabinet.room_name,
                "wall_name": cabinet.wall_name,
                "transform": {
                    "translation_mm": list(cabinet.transform.translation_mm),
                    "rotation_deg": list(cabinet.transform.rotation_deg),
                    "scale": list(cabinet.transform.scale),
                },
            }
            for cabinet in project.cabinets
        ],
        "parts": [
            {
                "id": part.id,
                "source_id": part.source_id,
                "cabinet_id": part.cabinet_id,
                "name": part.name,
                "category": part.category.value,
                "quantity": part.quantity,
                "material_id": part.material_id,
                "length_mm": part.length_mm,
                "width_mm": part.width_mm,
                "thickness_mm": part.thickness_mm,
                "rotation_allowed": part.rotation_allowed,
                "grain": part.grain.value,
                "outline": {
                    "outer": [[point.x, point.y] for point in part.outline.outer],
                    "cutouts": [
                        [[point.x, point.y] for point in loop]
                        for loop in part.outline.cutouts
                    ],
                },
                "edge_banding": dict(part.edge_banding.as_tuple()),
                "face": part.face.value,
                "machining": [_operation(operation) for operation in part.machining],
                "issues": [_issue(issue) for issue in part.issues],
            }
            for part in project.parts
        ],
        "materials": [
            {
                "id": material.id,
                "name": material.name,
                "thickness_mm": material.thickness_mm,
                "grain": material.grain.value,
                "supplier_code": material.supplier_code,
                "export_name": material.export_name,
            }
            for material in project.materials
        ],
        "hardware": [
            {
                "id": item.id,
                "name": item.name,
                "quantity": item.quantity,
                "supplier_code": item.supplier_code,
                "cabinet_id": item.cabinet_id,
            }
            for item in project.hardware
        ],
        "stock": [
            {
                "id": stock.id,
                "name": stock.name,
                "width_mm": stock.width_mm,
                "height_mm": stock.height_mm,
                "material_id": stock.material_id,
                "quantity": stock.quantity,
                "cost": stock.cost,
                "is_remnant": stock.is_remnant,
            }
            for stock in project.stock
        ],
        "issues": [_issue(issue) for issue in project.issues],
    }


def _parse_issue(data: dict[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        IssueSeverity(data["severity"]),
        data["code"],
        data["message"],
        data.get("source_id", ""),
        tuple((key, value) for key, value in data.get("details", {}).items()),
    )


def _parse_operation(data: dict[str, Any]) -> MachiningOperation:
    return MachiningOperation(
        id=data["id"],
        operation_type=MachiningType(data["operation_type"]),
        face=Face(data["face"]),
        x_mm=data.get("x_mm", 0),
        y_mm=data.get("y_mm", 0),
        end_x_mm=data.get("end_x_mm"),
        end_y_mm=data.get("end_y_mm"),
        diameter_mm=data.get("diameter_mm"),
        depth_mm=data.get("depth_mm"),
        width_mm=data.get("width_mm"),
        spacing_mm=data.get("spacing_mm"),
        path=tuple(tuple(point) for point in data.get("path", [])),
        tool_hint=data.get("tool_hint"),
        parameters=tuple(data.get("parameters", {}).items()),
    )


def project_from_dict(data: dict[str, Any]) -> ManufacturingProject:
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(f"unsupported manufacturing schema version: {version!r}")

    cabinets = tuple(
        Cabinet(
            id=item["id"],
            name=item["name"],
            source_id=item["source_id"],
            part_ids=tuple(item.get("part_ids", [])),
            room_name=item.get("room_name"),
            wall_name=item.get("wall_name"),
            transform=Transform(
                tuple(item.get("transform", {}).get("translation_mm", (0, 0, 0))),
                tuple(item.get("transform", {}).get("rotation_deg", (0, 0, 0))),
                tuple(item.get("transform", {}).get("scale", (1, 1, 1))),
            ),
        )
        for item in data.get("cabinets", [])
    )
    parts = tuple(
        Part(
            id=item["id"],
            source_id=item["source_id"],
            cabinet_id=item["cabinet_id"],
            name=item["name"],
            category=PartCategory(item["category"]),
            quantity=item["quantity"],
            material_id=item.get("material_id"),
            length_mm=item["length_mm"],
            width_mm=item["width_mm"],
            thickness_mm=item["thickness_mm"],
            rotation_allowed=item.get("rotation_allowed", True),
            grain=GrainDirection(item.get("grain", "none")),
            outline=Polygon2D(
                tuple(Point2D(*point) for point in item["outline"]["outer"]),
                tuple(
                    tuple(Point2D(*point) for point in loop)
                    for loop in item["outline"].get("cutouts", [])
                ),
            ),
            edge_banding=EdgeBanding(**item.get("edge_banding", {})),
            face=Face(item.get("face", "top")),
            machining=tuple(_parse_operation(value) for value in item.get("machining", [])),
            issues=tuple(_parse_issue(value) for value in item.get("issues", [])),
        )
        for item in data.get("parts", [])
    )
    materials = tuple(
        Material(
            id=item["id"],
            name=item["name"],
            thickness_mm=item["thickness_mm"],
            grain=GrainDirection(item.get("grain", "none")),
            supplier_code=item.get("supplier_code"),
            export_name=item.get("export_name"),
        )
        for item in data.get("materials", [])
    )
    hardware = tuple(HardwareItem(**item) for item in data.get("hardware", []))
    stock = tuple(StockDefinition(**item) for item in data.get("stock", []))
    defaults = data.get("defaults", {})
    return ManufacturingProject(
        project_id=data["project_id"],
        name=data["name"],
        source_path=data.get("source_path"),
        schema_version=version,
        units=data.get("units", "mm"),
        cabinets=cabinets,
        parts=parts,
        materials=materials,
        hardware=hardware,
        stock=stock,
        issues=tuple(_parse_issue(value) for value in data.get("issues", [])),
        default_kerf_mm=defaults.get("kerf_mm", 3.2),
        default_sheet_margin_mm=defaults.get("sheet_margin_mm", 10),
        default_part_spacing_mm=defaults.get("part_spacing_mm", 6),
    )


def dumps(project: ManufacturingProject, *, indent: int = 2) -> str:
    return json.dumps(
        project_to_dict(project),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"


def loads(payload: str) -> ManufacturingProject:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("manufacturing JSON root must be an object")
    return project_from_dict(data)


def dump(project: ManufacturingProject, destination: str | Path | TextIO) -> None:
    payload = dumps(project)
    if hasattr(destination, "write"):
        destination.write(payload)
    else:
        Path(destination).write_text(payload, encoding="utf-8")


def load(source: str | Path | TextIO) -> ManufacturingProject:
    if hasattr(source, "read"):
        return loads(source.read())
    return loads(Path(source).read_text(encoding="utf-8"))
