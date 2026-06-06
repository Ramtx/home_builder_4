"""Deterministic cut-list, material, hardware, and validation reports."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import html
import io
import json
from pathlib import Path
from typing import Any, Iterable

from .model import (
    MM_PRECISION,
    HardwareItem,
    IssueSeverity,
    MachiningOperation,
    ManufacturingProject,
    Material,
    Part,
    ValidationIssue,
    mm,
    stable_id,
)


REPORT_SCHEMA_VERSION = 1

PART_CSV_FIELDS = (
    "row_id",
    "project_id",
    "project_name",
    "cabinet_ids",
    "cabinet_names",
    "part_ids",
    "part_names",
    "category",
    "quantity",
    "finished_length_mm",
    "finished_width_mm",
    "finished_thickness_mm",
    "material_id",
    "material_name",
    "material_export_name",
    "material_supplier_code",
    "grain",
    "rotation_allowed",
    "edge_front",
    "edge_back",
    "edge_left",
    "edge_right",
    "face",
    "machining_summary",
    "source_identities",
    "validation_codes",
)

MATERIAL_CSV_FIELDS = (
    "project_id",
    "project_name",
    "material_id",
    "material_name",
    "material_export_name",
    "material_supplier_code",
    "thickness_mm",
    "part_row_count",
    "quantity",
    "finished_area_m2",
)

HARDWARE_CSV_FIELDS = (
    "row_id",
    "project_id",
    "project_name",
    "hardware_ids",
    "item_name",
    "supplier_code",
    "quantity",
    "cabinet_ids",
    "cabinet_names",
)

VALIDATION_CSV_FIELDS = (
    "severity",
    "code",
    "message",
    "source_id",
    "details",
)


@dataclass(frozen=True)
class PartTrace:
    cabinet_id: str
    cabinet_name: str
    part_id: str
    part_name: str
    source_identity: str
    quantity: int

    def sort_key(self) -> tuple[str, str, str, str, str, int]:
        return (
            self.cabinet_id,
            self.part_id,
            self.source_identity,
            self.cabinet_name,
            self.part_name,
            self.quantity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cabinet_id": self.cabinet_id,
            "cabinet_name": self.cabinet_name,
            "part_id": self.part_id,
            "part_name": self.part_name,
            "source_identity": self.source_identity,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class PartRow:
    row_id: str
    project_id: str
    project_name: str
    cabinet_ids: tuple[str, ...]
    cabinet_names: tuple[str, ...]
    part_ids: tuple[str, ...]
    part_names: tuple[str, ...]
    category: str
    quantity: int
    finished_length_mm: float
    finished_width_mm: float
    finished_thickness_mm: float
    material_id: str
    material_name: str
    material_export_name: str
    material_supplier_code: str
    grain: str
    rotation_allowed: bool
    edge_front: str
    edge_back: str
    edge_left: str
    edge_right: str
    face: str
    machining_summary: str
    machining: tuple[dict[str, Any], ...]
    outline: dict[str, Any]
    source_identities: tuple[str, ...]
    validation_codes: tuple[str, ...]
    trace: tuple[PartTrace, ...]

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.material_name.casefold(),
            self.finished_thickness_mm,
            self.category,
            -self.finished_length_mm,
            -self.finished_width_mm,
            self.grain,
            self.part_names,
            self.part_ids,
            self.row_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "cabinet_ids": list(self.cabinet_ids),
            "cabinet_names": list(self.cabinet_names),
            "part_ids": list(self.part_ids),
            "part_names": list(self.part_names),
            "category": self.category,
            "quantity": self.quantity,
            "finished_dimensions_mm": {
                "length": self.finished_length_mm,
                "width": self.finished_width_mm,
                "thickness": self.finished_thickness_mm,
            },
            "material": {
                "id": self.material_id,
                "name": self.material_name,
                "export_name": self.material_export_name or None,
                "supplier_code": self.material_supplier_code or None,
            },
            "grain": self.grain,
            "rotation_allowed": self.rotation_allowed,
            "edges": {
                "front": self.edge_front or None,
                "back": self.edge_back or None,
                "left": self.edge_left or None,
                "right": self.edge_right or None,
            },
            "face": self.face,
            "machining_summary": self.machining_summary,
            "machining": list(self.machining),
            "outline": self.outline,
            "source_identities": list(self.source_identities),
            "validation_codes": list(self.validation_codes),
            "trace": [item.to_dict() for item in self.trace],
        }

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "cabinet_ids": _join(self.cabinet_ids),
            "cabinet_names": _join(self.cabinet_names),
            "part_ids": _join(self.part_ids),
            "part_names": _join(self.part_names),
            "category": self.category,
            "quantity": self.quantity,
            "finished_length_mm": format_mm(self.finished_length_mm),
            "finished_width_mm": format_mm(self.finished_width_mm),
            "finished_thickness_mm": format_mm(self.finished_thickness_mm),
            "material_id": self.material_id,
            "material_name": self.material_name,
            "material_export_name": self.material_export_name,
            "material_supplier_code": self.material_supplier_code,
            "grain": self.grain,
            "rotation_allowed": "yes" if self.rotation_allowed else "no",
            "edge_front": self.edge_front,
            "edge_back": self.edge_back,
            "edge_left": self.edge_left,
            "edge_right": self.edge_right,
            "face": self.face,
            "machining_summary": self.machining_summary,
            "source_identities": _join(self.source_identities),
            "validation_codes": _join(self.validation_codes),
        }


@dataclass(frozen=True)
class MaterialSummaryRow:
    project_id: str
    project_name: str
    material_id: str
    material_name: str
    material_export_name: str
    material_supplier_code: str
    thickness_mm: float
    part_row_count: int
    quantity: int
    finished_area_m2: float

    def sort_key(self) -> tuple[str, float, str]:
        return (self.material_name.casefold(), self.thickness_mm, self.material_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "material_export_name": self.material_export_name or None,
            "material_supplier_code": self.material_supplier_code or None,
            "thickness_mm": self.thickness_mm,
            "part_row_count": self.part_row_count,
            "quantity": self.quantity,
            "finished_area_m2": self.finished_area_m2,
        }

    def to_csv_dict(self) -> dict[str, Any]:
        result = self.to_dict()
        result["material_export_name"] = self.material_export_name
        result["material_supplier_code"] = self.material_supplier_code
        result["thickness_mm"] = format_mm(self.thickness_mm)
        result["finished_area_m2"] = format_number(self.finished_area_m2)
        return result


@dataclass(frozen=True)
class HardwareTrace:
    hardware_id: str
    cabinet_id: str
    cabinet_name: str
    quantity: int

    def sort_key(self) -> tuple[str, str, str, int]:
        return (self.cabinet_id, self.hardware_id, self.cabinet_name, self.quantity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hardware_id": self.hardware_id,
            "cabinet_id": self.cabinet_id or None,
            "cabinet_name": self.cabinet_name or None,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class HardwareRow:
    row_id: str
    project_id: str
    project_name: str
    hardware_ids: tuple[str, ...]
    item_name: str
    supplier_code: str
    quantity: int
    cabinet_ids: tuple[str, ...]
    cabinet_names: tuple[str, ...]
    trace: tuple[HardwareTrace, ...]

    def sort_key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.item_name.casefold(), self.supplier_code, self.hardware_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "hardware_ids": list(self.hardware_ids),
            "item_name": self.item_name,
            "supplier_code": self.supplier_code or None,
            "quantity": self.quantity,
            "cabinet_ids": list(self.cabinet_ids),
            "cabinet_names": list(self.cabinet_names),
            "trace": [item.to_dict() for item in self.trace],
        }

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "hardware_ids": _join(self.hardware_ids),
            "item_name": self.item_name,
            "supplier_code": self.supplier_code,
            "quantity": self.quantity,
            "cabinet_ids": _join(self.cabinet_ids),
            "cabinet_names": _join(self.cabinet_names),
        }


@dataclass(frozen=True)
class CutListReport:
    project_id: str
    project_name: str
    source_path: str | None
    units: str
    parts: tuple[PartRow, ...]
    materials: tuple[MaterialSummaryRow, ...]
    hardware: tuple[HardwareRow, ...]
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class ExportedCutList:
    directory: Path
    parts_csv: Path
    parts_json: Path
    materials_csv: Path
    materials_json: Path
    hardware_csv: Path
    hardware_json: Path
    validation_csv: Path
    validation_json: Path
    html_report: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.parts_csv,
            self.parts_json,
            self.materials_csv,
            self.materials_json,
            self.hardware_csv,
            self.hardware_json,
            self.validation_csv,
            self.validation_json,
            self.html_report,
        )


def format_mm(value: float) -> str:
    return format_number(mm(value))


def format_number(value: float, precision: int = MM_PRECISION) -> str:
    formatted = f"{float(value):.{precision}f}".rstrip("0").rstrip(".")
    return "0" if formatted in {"", "-0"} else formatted


def build_cut_list(project: ManufacturingProject) -> CutListReport:
    cabinets = {cabinet.id: cabinet for cabinet in project.cabinets}
    materials = {material.id: material for material in project.materials}
    issues = list(project.validate())

    if not project.project_id.strip():
        issues.append(_warning("cutlist.missing_project_id", "Project ID is empty"))
    if not project.name.strip():
        issues.append(
            _warning(
                "cutlist.missing_project_name",
                "Project name is empty",
                project.project_id,
            )
        )
    if not project.parts:
        issues.append(
            _warning(
                "cutlist.no_parts",
                "The manufacturing project contains no cut parts",
                project.project_id,
            )
        )
    if not project.parts and not project.hardware:
        issues.append(
            _warning(
                "cutlist.empty_job",
                "The manufacturing project contains no cut parts or hardware",
                project.project_id,
            )
        )

    part_groups: dict[tuple[Any, ...], list[Part]] = {}
    for part in project.parts:
        material = materials.get(part.material_id or "")
        if not part.name.strip():
            issues.append(
                _warning(
                    "cutlist.part_missing_name",
                    "Part name is empty",
                    part.id,
                )
            )
        if not part.source_id.strip():
            issues.append(
                _warning(
                    "cutlist.part_missing_source_identity",
                    "Part source identity is empty",
                    part.id,
                )
            )
        if not part.material_id:
            issues.append(
                _warning(
                    "cutlist.part_missing_material",
                    "Part has no assigned material",
                    part.id,
                )
            )
        if material and abs(part.thickness_mm - material.thickness_mm) > 0.01:
            issues.append(
                _warning(
                    "cutlist.material_thickness_mismatch",
                    "Part thickness does not match its material thickness",
                    part.id,
                    part_thickness_mm=part.thickness_mm,
                    material_thickness_mm=material.thickness_mm,
                    material_id=material.id,
                )
            )
        part_groups.setdefault(_part_identity(part, material), []).append(part)

    for item in project.hardware:
        if not item.name.strip():
            issues.append(
                _warning(
                    "cutlist.hardware_missing_name",
                    "Hardware item name is empty",
                    item.id,
                )
            )
        if item.cabinet_id and item.cabinet_id not in cabinets:
            issues.append(
                _warning(
                    "cutlist.hardware_unknown_cabinet",
                    "Hardware item references an unknown cabinet",
                    item.id,
                    cabinet_id=item.cabinet_id,
                )
            )

    sorted_issues = _sorted_issues(issues)
    part_rows = tuple(
        sorted(
            (
                _part_row(project, grouped_parts, cabinets, materials, sorted_issues)
                for grouped_parts in part_groups.values()
            ),
            key=PartRow.sort_key,
        )
    )
    material_rows = _material_rows(project, part_rows)
    hardware_rows = _hardware_rows(project, cabinets)

    return CutListReport(
        project_id=project.project_id,
        project_name=project.name,
        source_path=project.source_path,
        units=project.units,
        parts=part_rows,
        materials=material_rows,
        hardware=hardware_rows,
        issues=sorted_issues,
    )


def render_parts_csv(report: CutListReport) -> str:
    return _render_csv(PART_CSV_FIELDS, (row.to_csv_dict() for row in report.parts))


def render_parts_json(report: CutListReport) -> str:
    return _render_json(
        {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "project": _project_dict(report),
            "row_count": len(report.parts),
            "total_quantity": sum(row.quantity for row in report.parts),
            "parts": [row.to_dict() for row in report.parts],
        }
    )


def render_materials_csv(report: CutListReport) -> str:
    return _render_csv(
        MATERIAL_CSV_FIELDS,
        (row.to_csv_dict() for row in report.materials),
    )


def render_materials_json(report: CutListReport) -> str:
    return _render_json(
        {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "project": _project_dict(report),
            "row_count": len(report.materials),
            "materials": [row.to_dict() for row in report.materials],
        }
    )


def render_hardware_csv(report: CutListReport) -> str:
    return _render_csv(
        HARDWARE_CSV_FIELDS,
        (row.to_csv_dict() for row in report.hardware),
    )


def render_hardware_json(report: CutListReport) -> str:
    return _render_json(
        {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "project": _project_dict(report),
            "row_count": len(report.hardware),
            "total_quantity": sum(row.quantity for row in report.hardware),
            "hardware": [row.to_dict() for row in report.hardware],
        }
    )


def render_validation_csv(report: CutListReport) -> str:
    rows = (
        {
            "severity": issue.severity.value,
            "code": issue.code,
            "message": issue.message,
            "source_id": issue.source_id,
            "details": json.dumps(
                dict(issue.details),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for issue in report.issues
    )
    return _render_csv(VALIDATION_CSV_FIELDS, rows)


def render_validation_json(report: CutListReport) -> str:
    counts = {
        severity.value: sum(
            issue.severity == severity for issue in report.issues
        )
        for severity in IssueSeverity
    }
    return _render_json(
        {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "project": _project_dict(report),
            "counts": counts,
            "issues": [_issue_dict(issue) for issue in report.issues],
        }
    )


def render_html(report: CutListReport) -> str:
    issue_counts = {
        severity.value: sum(
            issue.severity == severity for issue in report.issues
        )
        for severity in IssueSeverity
    }
    part_rows = "".join(
        "<tr>"
        f"<td>{_h(_join(row.part_names))}</td>"
        f"<td>{_h(_join(row.cabinet_names))}</td>"
        f"<td>{_h(row.category)}</td>"
        f"<td class=\"number\">{row.quantity}</td>"
        f"<td class=\"number\">{_h(format_mm(row.finished_length_mm))}</td>"
        f"<td class=\"number\">{_h(format_mm(row.finished_width_mm))}</td>"
        f"<td class=\"number\">{_h(format_mm(row.finished_thickness_mm))}</td>"
        f"<td>{_h(row.material_name or 'Unassigned')}</td>"
        f"<td>{_h(row.grain)}</td>"
        f"<td>{_h(_edge_summary(row))}</td>"
        f"<td>{_h(row.face)}</td>"
        f"<td>{_h(row.machining_summary)}</td>"
        f"<td>{_h(_join(row.validation_codes))}</td>"
        "</tr>"
        for row in report.parts
    )
    material_rows = "".join(
        "<tr>"
        f"<td>{_h(row.material_name or 'Unassigned')}</td>"
        f"<td>{_h(format_mm(row.thickness_mm))}</td>"
        f"<td class=\"number\">{row.part_row_count}</td>"
        f"<td class=\"number\">{row.quantity}</td>"
        f"<td class=\"number\">{_h(format_number(row.finished_area_m2))}</td>"
        "</tr>"
        for row in report.materials
    )
    hardware_rows = "".join(
        "<tr>"
        f"<td>{_h(row.item_name or 'Unnamed item')}</td>"
        f"<td>{_h(row.supplier_code)}</td>"
        f"<td class=\"number\">{row.quantity}</td>"
        f"<td>{_h(_join(row.cabinet_names))}</td>"
        "</tr>"
        for row in report.hardware
    )
    validation_rows = "".join(
        "<tr>"
        f"<td class=\"severity-{_h(issue.severity.value)}\">{_h(issue.severity.value)}</td>"
        f"<td>{_h(issue.code)}</td>"
        f"<td>{_h(issue.message)}</td>"
        f"<td>{_h(issue.source_id)}</td>"
        "</tr>"
        for issue in report.issues
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_h(report.project_name)} Cut List</title>
<style>
@page {{ size: landscape; margin: 10mm; }}
body {{ color: #111; font: 12px/1.35 Arial, sans-serif; margin: 24px; }}
h1, h2 {{ margin: 0 0 10px; }}
h2 {{ border-bottom: 2px solid #333; margin-top: 24px; padding-bottom: 4px; }}
.summary {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0 18px; }}
.summary span {{ border: 1px solid #bbb; padding: 6px 10px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 4px 6px; text-align: left; vertical-align: top; }}
th {{ background: #e9e9e9; }}
.number {{ text-align: right; white-space: nowrap; }}
.severity-error {{ color: #a00000; font-weight: bold; }}
.severity-warning {{ color: #8a5800; font-weight: bold; }}
.severity-info {{ color: #315b7d; }}
.empty {{ color: #666; font-style: italic; }}
@media print {{
  body {{ margin: 0; font-size: 9px; }}
  h2 {{ break-before: page; }}
  h2:first-of-type {{ break-before: auto; }}
  thead {{ display: table-header-group; }}
  tr {{ break-inside: avoid; }}
}}
</style>
</head>
<body>
<h1>{_h(report.project_name or "Unnamed Project")} - Manufacturing Report</h1>
<div>Project ID: {_h(report.project_id)} | Units: {_h(report.units)}</div>
<div class="summary">
<span>Cut-list rows: {len(report.parts)}</span>
<span>Part quantity: {sum(row.quantity for row in report.parts)}</span>
<span>Hardware quantity: {sum(row.quantity for row in report.hardware)}</span>
<span>Errors: {issue_counts["error"]}</span>
<span>Warnings: {issue_counts["warning"]}</span>
</div>
<h2>Cut List</h2>
<table>
<thead><tr><th>Part</th><th>Cabinet</th><th>Category</th><th>Qty</th><th>Length mm</th><th>Width mm</th><th>Thickness mm</th><th>Material</th><th>Grain</th><th>Edges</th><th>Face</th><th>Machining</th><th>Validation</th></tr></thead>
<tbody>{part_rows or '<tr><td class="empty" colspan="13">No cut parts</td></tr>'}</tbody>
</table>
<h2>Material / Thickness Summary</h2>
<table>
<thead><tr><th>Material</th><th>Thickness mm</th><th>Rows</th><th>Qty</th><th>Finished area m2</th></tr></thead>
<tbody>{material_rows or '<tr><td class="empty" colspan="5">No panel materials</td></tr>'}</tbody>
</table>
<h2>Hardware / Accessories</h2>
<table>
<thead><tr><th>Item</th><th>Supplier code</th><th>Qty</th><th>Cabinets</th></tr></thead>
<tbody>{hardware_rows or '<tr><td class="empty" colspan="4">No hardware</td></tr>'}</tbody>
</table>
<h2>Validation</h2>
<table>
<thead><tr><th>Severity</th><th>Code</th><th>Message</th><th>Source</th></tr></thead>
<tbody>{validation_rows or '<tr><td class="empty" colspan="4">No validation issues</td></tr>'}</tbody>
</table>
</body>
</html>
"""


def export_cut_list(
    project: ManufacturingProject,
    directory: str | Path,
) -> ExportedCutList:
    destination = Path(directory).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise NotADirectoryError(destination)

    report = build_cut_list(project)
    exported = ExportedCutList(
        directory=destination,
        parts_csv=destination / "cut_list.csv",
        parts_json=destination / "cut_list.json",
        materials_csv=destination / "material_summary.csv",
        materials_json=destination / "material_summary.json",
        hardware_csv=destination / "hardware.csv",
        hardware_json=destination / "hardware.json",
        validation_csv=destination / "validation.csv",
        validation_json=destination / "validation.json",
        html_report=destination / "cut_list.html",
    )
    payloads = (
        (exported.parts_csv, render_parts_csv(report)),
        (exported.parts_json, render_parts_json(report)),
        (exported.materials_csv, render_materials_csv(report)),
        (exported.materials_json, render_materials_json(report)),
        (exported.hardware_csv, render_hardware_csv(report)),
        (exported.hardware_json, render_hardware_json(report)),
        (exported.validation_csv, render_validation_csv(report)),
        (exported.validation_json, render_validation_json(report)),
        (exported.html_report, render_html(report)),
    )
    for path, payload in payloads:
        _write_text(path, payload)
    return exported


def _part_identity(part: Part, material: Material | None) -> tuple[Any, ...]:
    return (
        part.category.value,
        part.length_mm,
        part.width_mm,
        part.thickness_mm,
        _material_identity(part.material_id, material),
        part.grain.value,
        part.rotation_allowed,
        part.edge_banding.as_tuple(),
        part.face.value,
        _outline_identity(part),
        tuple(
            _operation_identity(operation)
            for operation in _semantic_operations(part.machining)
        ),
    )


def _material_identity(
    material_id: str | None,
    material: Material | None,
) -> tuple[Any, ...]:
    if material is None:
        return (material_id or "", "", "", "", None, "")
    return (
        material.id,
        material.name,
        material.export_name or "",
        material.supplier_code or "",
        material.thickness_mm,
        material.grain.value,
    )


def _outline_identity(part: Part) -> tuple[Any, ...]:
    return (
        tuple((point.x, point.y) for point in part.outline.outer),
        tuple(
            tuple((point.x, point.y) for point in loop)
            for loop in part.outline.cutouts
        ),
    )


def _operation_identity(operation: MachiningOperation) -> tuple[Any, ...]:
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
        operation.tool_hint or "",
        operation.parameters,
    )


def _semantic_operations(
    operations: tuple[MachiningOperation, ...],
) -> tuple[MachiningOperation, ...]:
    return tuple(
        sorted(
            operations,
            key=lambda operation: repr(_operation_identity(operation)),
        )
    )


def _operation_dict(operation: MachiningOperation) -> dict[str, Any]:
    return {
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


def _outline_dict(part: Part) -> dict[str, Any]:
    return {
        "outer": [[point.x, point.y] for point in part.outline.outer],
        "cutouts": [
            [[point.x, point.y] for point in loop]
            for loop in part.outline.cutouts
        ],
    }


def _part_row(
    project: ManufacturingProject,
    parts: list[Part],
    cabinets: dict[str, Any],
    materials: dict[str, Material],
    issues: tuple[ValidationIssue, ...],
) -> PartRow:
    ordered_parts = sorted(parts, key=Part.sort_key)
    representative = ordered_parts[0]
    material = materials.get(representative.material_id or "")
    trace = tuple(
        sorted(
            (
                PartTrace(
                    cabinet_id=part.cabinet_id,
                    cabinet_name=getattr(cabinets.get(part.cabinet_id), "name", ""),
                    part_id=part.id,
                    part_name=part.name,
                    source_identity=part.source_id,
                    quantity=part.quantity,
                )
                for part in ordered_parts
            ),
            key=PartTrace.sort_key,
        )
    )
    source_keys = {
        key
        for part in ordered_parts
        for key in (part.id, part.source_id)
        if key
    }
    validation_codes = tuple(
        sorted(
            {
                issue.code
                for issue in issues
                if issue.source_id in source_keys
            }
        )
    )
    identity = _part_identity(representative, material)
    semantic_operations = _semantic_operations(representative.machining)
    operations = tuple(_operation_dict(item) for item in semantic_operations)
    return PartRow(
        row_id=stable_id("cutlist-row", project.project_id, repr(identity)),
        project_id=project.project_id,
        project_name=project.name,
        cabinet_ids=_unique(item.cabinet_id for item in trace),
        cabinet_names=_unique(item.cabinet_name for item in trace),
        part_ids=_unique(item.part_id for item in trace),
        part_names=_unique(item.part_name for item in trace),
        category=representative.category.value,
        quantity=sum(part.quantity for part in ordered_parts),
        finished_length_mm=representative.length_mm,
        finished_width_mm=representative.width_mm,
        finished_thickness_mm=representative.thickness_mm,
        material_id=representative.material_id or "",
        material_name=material.name if material else "",
        material_export_name=(material.export_name or "") if material else "",
        material_supplier_code=(material.supplier_code or "") if material else "",
        grain=representative.grain.value,
        rotation_allowed=representative.rotation_allowed,
        edge_front=representative.edge_banding.front or "",
        edge_back=representative.edge_banding.back or "",
        edge_left=representative.edge_banding.left or "",
        edge_right=representative.edge_banding.right or "",
        face=representative.face.value,
        machining_summary=_machining_summary(semantic_operations),
        machining=operations,
        outline=_outline_dict(representative),
        source_identities=_unique(item.source_identity for item in trace),
        validation_codes=validation_codes,
        trace=trace,
    )


def _material_rows(
    project: ManufacturingProject,
    parts: tuple[PartRow, ...],
) -> tuple[MaterialSummaryRow, ...]:
    groups: dict[tuple[Any, ...], list[PartRow]] = {}
    for row in parts:
        key = (
            row.material_id,
            row.material_name,
            row.material_export_name,
            row.material_supplier_code,
            row.finished_thickness_mm,
        )
        groups.setdefault(key, []).append(row)

    rows = []
    for key, grouped_rows in groups.items():
        (
            material_id,
            material_name,
            export_name,
            supplier_code,
            thickness_mm,
        ) = key
        rows.append(
            MaterialSummaryRow(
                project_id=project.project_id,
                project_name=project.name,
                material_id=material_id,
                material_name=material_name,
                material_export_name=export_name,
                material_supplier_code=supplier_code,
                thickness_mm=thickness_mm,
                part_row_count=len(grouped_rows),
                quantity=sum(row.quantity for row in grouped_rows),
                finished_area_m2=round(
                    sum(
                        row.finished_length_mm
                        * row.finished_width_mm
                        * row.quantity
                        for row in grouped_rows
                    )
                    / 1_000_000,
                    MM_PRECISION,
                ),
            )
        )
    return tuple(sorted(rows, key=MaterialSummaryRow.sort_key))


def _hardware_rows(
    project: ManufacturingProject,
    cabinets: dict[str, Any],
) -> tuple[HardwareRow, ...]:
    groups: dict[tuple[str, str], list[HardwareItem]] = {}
    for item in project.hardware:
        groups.setdefault((item.name, item.supplier_code or ""), []).append(item)

    rows = []
    for key, items in groups.items():
        item_name, supplier_code = key
        trace = tuple(
            sorted(
                (
                    HardwareTrace(
                        hardware_id=item.id,
                        cabinet_id=item.cabinet_id or "",
                        cabinet_name=getattr(
                            cabinets.get(item.cabinet_id or ""),
                            "name",
                            "",
                        ),
                        quantity=item.quantity,
                    )
                    for item in items
                ),
                key=HardwareTrace.sort_key,
            )
        )
        rows.append(
            HardwareRow(
                row_id=stable_id(
                    "hardware-row",
                    project.project_id,
                    item_name,
                    supplier_code,
                ),
                project_id=project.project_id,
                project_name=project.name,
                hardware_ids=_unique(item.hardware_id for item in trace),
                item_name=item_name,
                supplier_code=supplier_code,
                quantity=sum(item.quantity for item in items),
                cabinet_ids=_unique(item.cabinet_id for item in trace),
                cabinet_names=_unique(item.cabinet_name for item in trace),
                trace=trace,
            )
        )
    return tuple(sorted(rows, key=HardwareRow.sort_key))


def _machining_summary(operations: tuple[MachiningOperation, ...]) -> str:
    summaries = []
    for operation in operations:
        values = [
            f"x={format_mm(operation.x_mm)}",
            f"y={format_mm(operation.y_mm)}",
        ]
        for label, value in (
            ("end_x", operation.end_x_mm),
            ("end_y", operation.end_y_mm),
            ("diameter", operation.diameter_mm),
            ("depth", operation.depth_mm),
            ("width", operation.width_mm),
            ("spacing", operation.spacing_mm),
        ):
            if value is not None:
                values.append(f"{label}={format_mm(value)}")
        if operation.path:
            values.append(
                "path="
                + ";".join(
                    f"{format_mm(point[0])}:{format_mm(point[1])}"
                    for point in operation.path
                )
            )
        if operation.tool_hint:
            values.append(f"tool={operation.tool_hint}")
        if operation.parameters:
            values.append(
                "parameters="
                + json.dumps(
                    dict(operation.parameters),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        summaries.append(
            f"{operation.operation_type.value}[{operation.face.value}]"
            f"({','.join(values)})"
        )
    return " | ".join(summaries)


def _render_csv(
    fieldnames: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        dialect="excel",
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _render_json(data: dict[str, Any]) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"


def _project_dict(report: CutListReport) -> dict[str, Any]:
    return {
        "id": report.project_id,
        "name": report.project_name,
        "source_path": report.source_path,
        "units": report.units,
    }


def _issue_dict(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "source_id": issue.source_id,
        "details": dict(issue.details),
    }


def _warning(
    code: str,
    message: str,
    source_id: str = "",
    **details: Any,
) -> ValidationIssue:
    return ValidationIssue(
        IssueSeverity.WARNING,
        code,
        message,
        source_id,
        tuple(details.items()),
    )


def _sorted_issues(
    issues: Iterable[ValidationIssue],
) -> tuple[ValidationIssue, ...]:
    unique = {issue.sort_key(): issue for issue in issues}
    return tuple(unique[key] for key in sorted(unique))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


def _join(values: Iterable[str]) -> str:
    return " | ".join(values)


def _edge_summary(row: PartRow) -> str:
    return ", ".join(
        f"{name}: {value}"
        for name, value in (
            ("front", row.edge_front),
            ("back", row.edge_back),
            ("left", row.edge_left),
            ("right", row.edge_right),
        )
        if value
    )


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _write_text(path: Path, payload: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        stream.write(payload)
    temporary.replace(path)


__all__ = [
    "CutListReport",
    "ExportedCutList",
    "HardwareRow",
    "MaterialSummaryRow",
    "PartRow",
    "PartTrace",
    "REPORT_SCHEMA_VERSION",
    "build_cut_list",
    "export_cut_list",
    "format_mm",
    "render_hardware_csv",
    "render_hardware_json",
    "render_html",
    "render_materials_csv",
    "render_materials_json",
    "render_parts_csv",
    "render_parts_json",
    "render_validation_csv",
    "render_validation_json",
]
