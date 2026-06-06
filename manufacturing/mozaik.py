"""Neutral Mozaik-oriented manufacturing package export.

The package intentionally does not create or claim to create proprietary
Mozaik project files. Publicly documented manual DXF import is the only
verified Mozaik-specific capability used by this exporter.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
from typing import Any, Iterable, Sequence

from .dxf import DxfDocument, DxfLayer, format_number
from .geometry import EPSILON_MM, Point2D, point_in_loop
from .model import (
    Face,
    IssueSeverity,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    ValidationIssue,
)


PACKAGE_FORMAT = "home-builder-neutral-mozaik-interchange"
PACKAGE_VERSION = 1
DEFAULT_PROFILE_PATH = Path(__file__).with_name("profiles") / "mozaik-default.json"
DXF_LAYER_KEYS = (
    "outline",
    "cut_out",
    "drill",
    "groove",
    "pocket",
    "annotation",
    "face",
)


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _issue_dict(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code,
        "message": issue.message,
        "source_id": issue.source_id,
        "details": dict(issue.details),
    }


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or "\n" in value or "\r" in value:
        return False
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return (
        not path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def _resolved_output_path(root: Path, relative_path: str) -> Path:
    """Resolve a configured output without permitting package-root escape."""
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    if not candidate.is_relative_to(resolved_root) or candidate == resolved_root:
        raise ValueError(
            f"configured output path escapes the package directory: {relative_path!r}"
        )
    return candidate


def _paths_collide(first: str, second: str) -> bool:
    first_path = PurePosixPath(first)
    second_path = PurePosixPath(second)
    return (
        first_path == second_path
        or first_path in second_path.parents
        or second_path in first_path.parents
    )


@dataclass(frozen=True)
class MaterialMapping:
    export_name: str
    thickness_name: str
    source_material_id: str | None = None
    source_name: str | None = None
    source_thickness_mm: float | None = None

    def matches(self, material: Material, thickness_mm: float, tolerance_mm: float) -> bool:
        if self.source_material_id and self.source_material_id != material.id:
            return False
        if self.source_name and self.source_name.casefold() != material.name.casefold():
            return False
        return self.source_thickness_mm is None or math.isclose(
            self.source_thickness_mm,
            thickness_mm,
            abs_tol=tolerance_mm,
        )


@dataclass(frozen=True)
class ResolvedMaterial:
    source_id: str
    source_name: str
    source_thickness_mm: float
    export_name: str
    thickness_name: str


@dataclass(frozen=True)
class MozaikProfile:
    profile_id: str
    description: str
    unmapped_material_policy: str
    thickness_tolerance_mm: float
    output: dict[str, str]
    layers: dict[str, str]
    material_mappings: tuple[MaterialMapping, ...]
    material_name_mappings: dict[str, str]
    thickness_name_mappings: dict[str, str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MozaikProfile":
        if data.get("profile_version") != 1:
            raise ValueError("unsupported Mozaik profile version")
        output = {str(key): str(value) for key, value in data.get("output", {}).items()}
        layers = {
            str(key): str(value)
            for key, value in data.get("dxf", {}).get("layers", {}).items()
        }
        mappings = []
        for item in data.get("material_mappings", []):
            mappings.append(
                MaterialMapping(
                    export_name=str(item["export_name"]),
                    thickness_name=str(item["thickness_name"]),
                    source_material_id=(
                        str(item["source_material_id"])
                        if item.get("source_material_id")
                        else None
                    ),
                    source_name=str(item["source_name"]) if item.get("source_name") else None,
                    source_thickness_mm=(
                        float(item["source_thickness_mm"])
                        if item.get("source_thickness_mm") is not None
                        else None
                    ),
                )
            )
        return cls(
            profile_id=str(data.get("profile_id", "")).strip(),
            description=str(data.get("description", "")).strip(),
            unmapped_material_policy=str(
                data.get("unmapped_material_policy", "error")
            ).strip(),
            thickness_tolerance_mm=abs(float(data.get("thickness_tolerance_mm", 0.05))),
            output=output,
            layers=layers,
            material_mappings=tuple(mappings),
            material_name_mappings={
                str(key).casefold(): str(value)
                for key, value in data.get("material_name_mappings", {}).items()
            },
            thickness_name_mappings={
                str(key): str(value)
                for key, value in data.get("thickness_name_mappings", {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": 1,
            "profile_id": self.profile_id,
            "description": self.description,
            "unmapped_material_policy": self.unmapped_material_policy,
            "thickness_tolerance_mm": self.thickness_tolerance_mm,
            "output": dict(sorted(self.output.items())),
            "dxf": {"layers": dict(sorted(self.layers.items()))},
            "material_mappings": [
                {
                    "source_material_id": mapping.source_material_id,
                    "source_name": mapping.source_name,
                    "source_thickness_mm": mapping.source_thickness_mm,
                    "export_name": mapping.export_name,
                    "thickness_name": mapping.thickness_name,
                }
                for mapping in self.material_mappings
            ],
            "material_name_mappings": dict(sorted(self.material_name_mappings.items())),
            "thickness_name_mappings": dict(
                sorted(self.thickness_name_mappings.items())
            ),
        }

    def validate(self) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if not self.profile_id:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.missing_profile_id",
                    "Profile ID must not be empty",
                )
            )
        if not math.isfinite(self.thickness_tolerance_mm):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.invalid_thickness_tolerance",
                    "Material thickness tolerance must be finite",
                    self.profile_id,
                )
            )
        required_outputs = {
            "panels_directory",
            "optimizer_csv",
            "manifest",
            "validation_report",
            "profile_copy",
        }
        missing_outputs = sorted(required_outputs - self.output.keys())
        if missing_outputs:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.profile_missing_output",
                    "Profile is missing required output paths",
                    self.profile_id,
                    (("keys", tuple(missing_outputs)),),
                )
            )
        invalid_paths = sorted(
            value for value in self.output.values() if not _safe_relative_path(value)
        )
        if invalid_paths:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.unsafe_output_filename",
                    "Profile output paths must be safe relative paths",
                    self.profile_id,
                    (("paths", tuple(invalid_paths)),),
                )
            )
        output_paths = [value.casefold() for value in self.output.values()]
        if len(output_paths) != len(set(output_paths)):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.duplicate_output_filename",
                    "Profile output paths must be unique, including case differences",
                    self.profile_id,
                )
            )
        output_items = sorted(self.output.items())
        collisions = sorted(
            (first_key, second_key)
            for index, (first_key, first_path) in enumerate(output_items)
            for second_key, second_path in output_items[index + 1 :]
            if _paths_collide(first_path.casefold(), second_path.casefold())
        )
        if collisions:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.output_path_collision",
                    "Output files and directories must not contain one another",
                    self.profile_id,
                    (("keys", tuple(collisions)),),
                )
            )
        missing_layers = sorted(set(DXF_LAYER_KEYS) - self.layers.keys())
        if missing_layers:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.profile_missing_layer",
                    "Profile is missing required DXF layers",
                    self.profile_id,
                    (("layers", tuple(missing_layers)),),
                )
            )
        layer_names = [name.casefold() for name in self.layers.values()]
        if len(layer_names) != len(set(layer_names)):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.duplicate_layer_name",
                    "DXF layer names must be unique, including case differences",
                    self.profile_id,
                )
            )
        invalid_layers = sorted(
            name
            for name in self.layers.values()
            if not name
            or "\n" in name
            or "\r" in name
            or not name.isascii()
        )
        if invalid_layers:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.invalid_layer_name",
                    "DXF layer names must be non-empty single-line ASCII strings",
                    self.profile_id,
                    (("layers", tuple(invalid_layers)),),
                )
            )
        if self.unmapped_material_policy not in {"error", "identity"}:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.invalid_material_policy",
                    "Unmapped material policy must be 'error' or 'identity'",
                    self.profile_id,
                )
            )
        invalid_mappings = tuple(
            index
            for index, mapping in enumerate(self.material_mappings)
            if not mapping.export_name
            or not mapping.thickness_name
            or (
                mapping.source_thickness_mm is not None
                and not math.isfinite(mapping.source_thickness_mm)
            )
        )
        if invalid_mappings:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.invalid_material_mapping",
                    "Material mappings require names and finite source thicknesses",
                    self.profile_id,
                    (("indexes", invalid_mappings),),
                )
            )
        return tuple(sorted(issues, key=ValidationIssue.sort_key))

    def resolve_material(
        self,
        material: Material | None,
        thickness_mm: float,
        source_id: str,
    ) -> tuple[ResolvedMaterial | None, ValidationIssue | None]:
        if material is None:
            return None, ValidationIssue(
                IssueSeverity.ERROR,
                "mozaik.missing_material",
                "Part has no material and cannot be mapped for export",
                source_id,
            )
        for mapping in self.material_mappings:
            if mapping.matches(material, thickness_mm, self.thickness_tolerance_mm):
                return (
                    ResolvedMaterial(
                        material.id,
                        material.name,
                        thickness_mm,
                        mapping.export_name,
                        mapping.thickness_name,
                    ),
                    None,
                )

        export_name = self.material_name_mappings.get(material.name.casefold())
        thickness_key = format_number(thickness_mm)
        thickness_name = self.thickness_name_mappings.get(thickness_key)
        if export_name and thickness_name:
            return (
                ResolvedMaterial(
                    material.id,
                    material.name,
                    thickness_mm,
                    export_name,
                    thickness_name,
                ),
                None,
            )
        if self.unmapped_material_policy == "identity":
            return (
                ResolvedMaterial(
                    material.id,
                    material.name,
                    thickness_mm,
                    material.export_name or material.name,
                    f"{format_number(thickness_mm)} mm",
                ),
                None,
            )
        return None, ValidationIssue(
            IssueSeverity.ERROR,
            "mozaik.missing_material_mapping",
            "No export material and thickness mapping matches this part",
            source_id,
            (
                ("material_id", material.id),
                ("material_name", material.name),
                ("thickness_mm", thickness_mm),
            ),
        )


def load_profile(path: str | Path | None = None) -> MozaikProfile:
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Mozaik profile root must be a JSON object")
    return MozaikProfile.from_dict(data)


@dataclass(frozen=True)
class ExportResult:
    output_directory: Path
    files: tuple[Path, ...]
    issues: tuple[ValidationIssue, ...]
    panel_count: int

    @property
    def ok(self) -> bool:
        return not any(issue.severity == IssueSeverity.ERROR for issue in self.issues)


@dataclass
class _PanelGroup:
    panel_id: str
    signature: str
    part: Part
    material: ResolvedMaterial
    part_ids: list[str]
    source_ids: list[str]
    names: list[str]
    quantity: int
    dxf_path: str
    operation_statuses: list[dict[str, Any]]
    source_operations: list[dict[str, Any]]


def _operation_signature(operation: MachiningOperation) -> dict[str, Any]:
    return {
        "type": operation.operation_type.value,
        "face": operation.face.value,
        "x": operation.x_mm,
        "y": operation.y_mm,
        "end_x": operation.end_x_mm,
        "end_y": operation.end_y_mm,
        "diameter": operation.diameter_mm,
        "depth": operation.depth_mm,
        "width": operation.width_mm,
        "spacing": operation.spacing_mm,
        "path": operation.path,
        "tool_hint": operation.tool_hint,
        "parameters": operation.parameters,
    }


def _part_signature(part: Part, material: ResolvedMaterial) -> str:
    machining = tuple(
        sorted(
            (_operation_signature(item) for item in part.machining),
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    )
    payload = {
        "material": (material.export_name, material.thickness_name),
        "dimensions": (part.length_mm, part.width_mm, part.thickness_mm),
        "outline": (
            tuple((point.x, point.y) for point in part.outline.outer),
            tuple(
                tuple((point.x, point.y) for point in loop)
                for loop in part.outline.cutouts
            ),
        ),
        "grain": part.grain.value,
        "rotation_allowed": part.rotation_allowed,
        "edge_banding": part.edge_banding.as_tuple(),
        "face": part.face.value,
        "machining": machining,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segments(points: Sequence[Point2D | Sequence[float]]) -> tuple[tuple[Point2D, Point2D], ...]:
    normalized = tuple(
        point if isinstance(point, Point2D) else Point2D(point[0], point[1])
        for point in points
    )
    return tuple(
        (point, normalized[(index + 1) % len(normalized)])
        for index, point in enumerate(normalized)
    )


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: Point2D, b: Point2D, point: Point2D) -> bool:
    return (
        min(a.x, b.x) - EPSILON_MM <= point.x <= max(a.x, b.x) + EPSILON_MM
        and min(a.y, b.y) - EPSILON_MM <= point.y <= max(a.y, b.y) + EPSILON_MM
        and abs(_orientation(a, b, point)) <= EPSILON_MM
    )


def _segments_intersect(
    first: tuple[Point2D, Point2D],
    second: tuple[Point2D, Point2D],
) -> bool:
    a, b = first
    c, d = second
    orientations = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if (
        orientations[0] * orientations[1] < -EPSILON_MM
        and orientations[2] * orientations[3] < -EPSILON_MM
    ):
        return True
    return (
        (abs(orientations[0]) <= EPSILON_MM and _on_segment(a, b, c))
        or (abs(orientations[1]) <= EPSILON_MM and _on_segment(a, b, d))
        or (abs(orientations[2]) <= EPSILON_MM and _on_segment(c, d, a))
        or (abs(orientations[3]) <= EPSILON_MM and _on_segment(c, d, b))
    )


def _self_intersects(points: Sequence[Point2D | Sequence[float]]) -> bool:
    segments = _segments(points)
    for first_index, first in enumerate(segments):
        for second_index in range(first_index + 1, len(segments)):
            if second_index in {
                first_index,
                first_index + 1,
                (first_index - 1) % len(segments),
            }:
                continue
            if first_index == 0 and second_index == len(segments) - 1:
                continue
            if _segments_intersect(first, segments[second_index]):
                return True
    return False


def _part_geometry_issues(part: Part) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if _self_intersects(part.outline.outer):
        issues.append(
            ValidationIssue(
                IssueSeverity.ERROR,
                "mozaik.self_intersecting_outline",
                "Panel outline self-intersects and is unsafe to export",
                part.id,
            )
        )
    outer_segments = _segments(part.outline.outer)
    for index, cutout in enumerate(part.outline.cutouts):
        if _self_intersects(cutout):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.self_intersecting_cutout",
                    "Panel cut-out self-intersects and is unsafe to export",
                    part.id,
                    (("cutout_index", index),),
                )
            )
        if any(
            _segments_intersect(cutout_segment, outer_segment)
            for cutout_segment in _segments(cutout)
            for outer_segment in outer_segments
        ):
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "mozaik.cutout_crosses_outline",
                    "Panel cut-out crosses the outer outline",
                    part.id,
                    (("cutout_index", index),),
                )
            )
    for first_index, first_cutout in enumerate(part.outline.cutouts):
        first_segments = _segments(first_cutout)
        for second_index in range(first_index + 1, len(part.outline.cutouts)):
            second_cutout = part.outline.cutouts[second_index]
            intersects = any(
                _segments_intersect(first_segment, second_segment)
                for first_segment in first_segments
                for second_segment in _segments(second_cutout)
            )
            nested = (
                point_in_loop(first_cutout[0], second_cutout)
                or point_in_loop(second_cutout[0], first_cutout)
            )
            if intersects or nested:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "mozaik.overlapping_cutouts",
                        "Panel cut-outs intersect or contain one another",
                        part.id,
                        (
                            ("first_cutout_index", first_index),
                            ("second_cutout_index", second_index),
                        ),
                    )
                )
    return tuple(sorted(issues, key=ValidationIssue.sort_key))


def _point_is_machinable(part: Part, point: Point2D) -> bool:
    return point_in_loop(point, part.outline.outer) and not any(
        point_in_loop(point, cutout) for cutout in part.outline.cutouts
    )


def _distance_to_segment(point: Point2D, start: Point2D, end: Point2D) -> float:
    delta_x = end.x - start.x
    delta_y = end.y - start.y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared <= EPSILON_MM:
        return math.dist((point.x, point.y), (start.x, start.y))
    projection = (
        (point.x - start.x) * delta_x + (point.y - start.y) * delta_y
    ) / length_squared
    projection = min(1.0, max(0.0, projection))
    closest = (
        start.x + projection * delta_x,
        start.y + projection * delta_y,
    )
    return math.dist((point.x, point.y), closest)


def _circle_is_machinable(part: Part, center: Point2D, radius: float) -> bool:
    if not _point_is_machinable(part, center):
        return False
    boundaries = (_segments(part.outline.outer),) + tuple(
        _segments(loop) for loop in part.outline.cutouts
    )
    return all(
        _distance_to_segment(center, start, end) + EPSILON_MM >= radius
        for boundary in boundaries
        for start, end in boundary
    )


def _path_is_machinable(part: Part, points: Sequence[Sequence[float]]) -> bool:
    converted = tuple(Point2D(point[0], point[1]) for point in points)
    if not converted or any(not _point_is_machinable(part, point) for point in converted):
        return False
    boundaries = (_segments(part.outline.outer),) + tuple(
        _segments(loop) for loop in part.outline.cutouts
    )
    path_segments = _segments(converted)
    return not any(
        _segments_intersect(path_segment, boundary_segment)
        for path_segment in path_segments
        for boundary in boundaries
        for boundary_segment in boundary
    )


def _operation_issue(
    part: Part,
    operation: MachiningOperation,
    code: str,
    message: str,
    severity: IssueSeverity = IssueSeverity.WARNING,
) -> ValidationIssue:
    return ValidationIssue(
        severity,
        code,
        message,
        part.id,
        (("operation_id", operation.id), ("operation_type", operation.operation_type.value)),
    )


def _operation_points(
    part: Part,
    operation: MachiningOperation,
) -> tuple[list[tuple[float, float]], ValidationIssue | None]:
    if operation.end_x_mm is None or operation.end_y_mm is None:
        return [], _operation_issue(
            part,
            operation,
            "mozaik.missing_operation_end",
            "Machining operation has no end point and was omitted from DXF",
        )
    return [
        (operation.x_mm, operation.y_mm),
        (operation.end_x_mm, operation.end_y_mm),
    ], None


def _add_machining(
    document: DxfDocument,
    part: Part,
    layers: dict[str, str],
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    statuses: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    for operation in part.machining:
        status = {
            "operation_id": operation.id,
            "operation_type": operation.operation_type.value,
            "face": operation.face.value,
            "status": "exported",
            "dxf_layer": None,
            "depth_mm": operation.depth_mm,
            "tool_hint": operation.tool_hint,
        }
        if operation.face not in {Face.TOP, Face.BOTTOM}:
            issue = _operation_issue(
                part,
                operation,
                "mozaik.unsupported_operation_face",
                "Only top and bottom panel-face machining can be projected to panel DXF",
            )
            issues.append(issue)
            status.update(status="omitted", reason=issue.code)
            statuses.append(status)
            continue

        if operation.operation_type in {
            MachiningType.THROUGH_HOLE,
            MachiningType.BLIND_HOLE,
        }:
            if operation.diameter_mm is None or operation.diameter_mm <= 0:
                issue = _operation_issue(
                    part,
                    operation,
                    "mozaik.missing_hole_diameter",
                    "Hole has no positive diameter and was omitted from DXF",
                )
                issues.append(issue)
                status.update(status="omitted", reason=issue.code)
            else:
                center = Point2D(operation.x_mm, operation.y_mm)
                radius = operation.diameter_mm / 2
                if not _circle_is_machinable(part, center, radius):
                    issue = _operation_issue(
                        part,
                        operation,
                        "mozaik.unsafe_hole_geometry",
                        "Hole crosses a panel boundary and was omitted from DXF",
                        IssueSeverity.ERROR,
                    )
                    issues.append(issue)
                    status.update(status="omitted", reason=issue.code)
                else:
                    document.add_circle(
                        layers["drill"],
                        (center.x, center.y),
                        radius,
                    )
                    status["dxf_layer"] = layers["drill"]
        elif operation.operation_type == MachiningType.LINE_BORE:
            line, issue = _operation_points(part, operation)
            if issue or operation.diameter_mm is None or operation.diameter_mm <= 0:
                issue = issue or _operation_issue(
                    part,
                    operation,
                    "mozaik.missing_hole_diameter",
                    "Line bore has no positive diameter and was omitted from DXF",
                )
            elif operation.spacing_mm is None or operation.spacing_mm <= 0:
                issue = _operation_issue(
                    part,
                    operation,
                    "mozaik.missing_line_bore_spacing",
                    "Line bore has no positive spacing and was omitted from DXF",
                )
            if issue:
                issues.append(issue)
                status.update(status="omitted", reason=issue.code)
            else:
                start, end = line
                distance = math.dist(start, end)
                count = int(math.floor(distance / operation.spacing_mm + EPSILON_MM)) + 1
                if count > 10000:
                    issue = _operation_issue(
                        part,
                        operation,
                        "mozaik.excessive_line_bore_count",
                        "Line bore expands to more than 10000 holes and was omitted",
                        IssueSeverity.ERROR,
                    )
                    issues.append(issue)
                    status.update(status="omitted", reason=issue.code)
                else:
                    dx = 0.0 if distance == 0 else (end[0] - start[0]) / distance
                    dy = 0.0 if distance == 0 else (end[1] - start[1]) / distance
                    centers = [
                        Point2D(
                            start[0] + dx * operation.spacing_mm * index,
                            start[1] + dy * operation.spacing_mm * index,
                        )
                        for index in range(count)
                    ]
                    radius = operation.diameter_mm / 2
                    if any(
                        not _circle_is_machinable(part, center, radius)
                        for center in centers
                    ):
                        issue = _operation_issue(
                            part,
                            operation,
                            "mozaik.unsafe_line_bore_geometry",
                            "Line bore leaves the panel boundary and was omitted from DXF",
                            IssueSeverity.ERROR,
                        )
                        issues.append(issue)
                        status.update(status="omitted", reason=issue.code)
                    else:
                        for center in centers:
                            document.add_circle(
                                layers["drill"],
                                (center.x, center.y),
                                radius,
                            )
                        status["dxf_layer"] = layers["drill"]
                        status["entity_count"] = len(centers)
        elif operation.operation_type == MachiningType.GROOVE:
            line, issue = _operation_points(part, operation)
            if issue or operation.width_mm is None or operation.width_mm <= 0:
                issue = issue or _operation_issue(
                    part,
                    operation,
                    "mozaik.missing_groove_width",
                    "Groove has no positive width and was omitted from DXF",
                )
            if issue:
                issues.append(issue)
                status.update(status="omitted", reason=issue.code)
            else:
                start, end = line
                distance = math.dist(start, end)
                if distance <= EPSILON_MM:
                    issue = _operation_issue(
                        part,
                        operation,
                        "mozaik.zero_length_groove",
                        "Zero-length groove was omitted from DXF",
                    )
                    issues.append(issue)
                    status.update(status="omitted", reason=issue.code)
                else:
                    offset_x = -(end[1] - start[1]) * operation.width_mm / (2 * distance)
                    offset_y = (end[0] - start[0]) * operation.width_mm / (2 * distance)
                    path = (
                        (start[0] + offset_x, start[1] + offset_y),
                        (end[0] + offset_x, end[1] + offset_y),
                        (end[0] - offset_x, end[1] - offset_y),
                        (start[0] - offset_x, start[1] - offset_y),
                    )
                    if not _path_is_machinable(part, path):
                        issue = _operation_issue(
                            part,
                            operation,
                            "mozaik.unsafe_groove_geometry",
                            "Groove crosses a panel boundary and was omitted from DXF",
                            IssueSeverity.ERROR,
                        )
                        issues.append(issue)
                        status.update(status="omitted", reason=issue.code)
                    else:
                        document.add_lwpolyline(layers["groove"], path)
                        status["dxf_layer"] = layers["groove"]
        elif operation.operation_type in {
            MachiningType.POCKET,
            MachiningType.CONTOUR_CUTOUT,
        }:
            layer_key = (
                "pocket"
                if operation.operation_type == MachiningType.POCKET
                else "cut_out"
            )
            if len(operation.path) < 3:
                issue = _operation_issue(
                    part,
                    operation,
                    "mozaik.missing_operation_path",
                    "Machining operation has no closed path and was omitted from DXF",
                )
                issues.append(issue)
                status.update(status="omitted", reason=issue.code)
            elif _self_intersects(operation.path) or not _path_is_machinable(
                part, operation.path
            ):
                issue = _operation_issue(
                    part,
                    operation,
                    "mozaik.unsafe_operation_path",
                    "Machining path is self-intersecting or leaves the panel and was omitted",
                    IssueSeverity.ERROR,
                )
                issues.append(issue)
                status.update(status="omitted", reason=issue.code)
            else:
                document.add_lwpolyline(layers[layer_key], operation.path)
                status["dxf_layer"] = layers[layer_key]
        else:
            issue = _operation_issue(
                part,
                operation,
                "mozaik.unsupported_machining",
                "Machining type is unsupported and was omitted from DXF",
            )
            issues.append(issue)
            status.update(status="omitted", reason=issue.code)
        statuses.append(status)
    return statuses, issues


def _new_dxf(profile: MozaikProfile) -> DxfDocument:
    colors = {
        "outline": 7,
        "cut_out": 1,
        "drill": 3,
        "groove": 5,
        "pocket": 6,
        "annotation": 2,
        "face": 4,
    }
    return DxfDocument(
        DxfLayer(profile.layers[key], colors[key]) for key in DXF_LAYER_KEYS
    )


def _write_panel_dxf(
    path: Path,
    group: _PanelGroup,
    profile: MozaikProfile,
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    document = _new_dxf(profile)
    part = group.part
    document.add_lwpolyline(
        profile.layers["outline"],
        tuple((point.x, point.y) for point in part.outline.outer),
    )
    for cutout in part.outline.cutouts:
        document.add_lwpolyline(
            profile.layers["cut_out"],
            tuple((point.x, point.y) for point in cutout),
        )
    text_x = min(2.0, part.length_mm / 10.0)
    document.add_text(
        profile.layers["face"],
        f"PANEL FACE: {part.face.value.upper()}",
        (text_x, min(2.0, part.width_mm / 4.0)),
        min(5.0, max(1.0, min(part.length_mm, part.width_mm) / 30.0)),
    )
    machining_faces = ",".join(
        sorted({operation.face.value.upper() for operation in part.machining})
    ) or "NONE"
    document.add_text(
        profile.layers["face"],
        f"MACHINING FACES: {machining_faces}",
        (text_x, min(9.0, part.width_mm / 2.0)),
        min(4.0, max(1.0, min(part.length_mm, part.width_mm) / 35.0)),
    )
    document.add_text(
        profile.layers["annotation"],
        group.panel_id,
        (text_x, max(0.0, part.width_mm - min(7.0, part.width_mm / 4.0))),
        min(5.0, max(1.0, min(part.length_mm, part.width_mm) / 30.0)),
    )
    statuses, issues = _add_machining(document, part, profile.layers)
    document.write(path)
    return statuses, issues


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_record(root: Path, path: Path, kind: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _deduplicate_issues(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    unique = {
        (
            issue.severity.value,
            issue.code,
            issue.message,
            issue.source_id,
            repr(issue.details),
        ): issue
        for issue in issues
    }
    return tuple(sorted(unique.values(), key=ValidationIssue.sort_key))


def export_package(
    project: ManufacturingProject,
    output_directory: str | Path,
    profile: MozaikProfile | None = None,
) -> ExportResult:
    """Write a complete neutral interchange directory and validation report."""
    profile = profile or load_profile()
    root = Path(output_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    issues: list[ValidationIssue] = list(project.validate())
    profile_issues = profile.validate()
    issues.extend(profile_issues)

    if any(issue.severity == IssueSeverity.ERROR for issue in profile_issues):
        validation_path = root / "validation.json"
        final_issues = _deduplicate_issues(issues)
        validation_path.write_text(
            _json_text(
                {
                    "package_format": PACKAGE_FORMAT,
                    "valid": False,
                    "issues": [_issue_dict(issue) for issue in final_issues],
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        return ExportResult(root, (validation_path,), final_issues, 0)

    output_paths = {
        key: _resolved_output_path(root, value)
        for key, value in profile.output.items()
    }
    panels_directory = output_paths["panels_directory"]
    if panels_directory.exists():
        shutil.rmtree(panels_directory)
    panels_directory.mkdir(parents=True)

    materials = {material.id: material for material in project.materials}
    groups: dict[str, _PanelGroup] = {}
    part_records: list[dict[str, Any]] = []
    for part in project.parts:
        material, mapping_issue = profile.resolve_material(
            materials.get(part.material_id or ""),
            part.thickness_mm,
            part.id,
        )
        geometry_issues = _part_geometry_issues(part)
        part_errors = tuple(
            issue
            for issue in part.validate()
            if issue.severity == IssueSeverity.ERROR
        )
        issues.extend(geometry_issues)
        if mapping_issue:
            issues.append(mapping_issue)
        if material is None or any(
            issue.severity == IssueSeverity.ERROR for issue in geometry_issues
        ) or part_errors:
            part_records.append(
                {
                    "part_id": part.id,
                    "source_id": part.source_id,
                    "name": part.name,
                    "cabinet_id": part.cabinet_id,
                    "category": part.category.value,
                    "material_id": part.material_id,
                    "quantity": part.quantity,
                    "status": "omitted",
                    "panel_id": None,
                }
            )
            continue
        signature = _part_signature(part, material)
        panel_id = f"panel-{signature[:16]}"
        dxf_path = (
            PurePosixPath(profile.output["panels_directory"])
            / f"panel-{signature}.dxf"
        ).as_posix()
        group = groups.get(signature)
        if group is None:
            group = _PanelGroup(
                panel_id=panel_id,
                signature=signature,
                part=part,
                material=material,
                part_ids=[],
                source_ids=[],
                names=[],
                quantity=0,
                dxf_path=dxf_path,
                operation_statuses=[],
                source_operations=[],
            )
            groups[signature] = group
        group.part_ids.append(part.id)
        group.source_ids.append(part.source_id)
        group.names.append(part.name)
        group.quantity += part.quantity
        group.source_operations.append(
            {
                "part_id": part.id,
                "operations": [
                    {
                        "operation_id": operation.id,
                        "operation_type": operation.operation_type.value,
                        "face": operation.face.value,
                    }
                    for operation in part.machining
                ],
            }
        )
        part_records.append(
            {
                "part_id": part.id,
                "source_id": part.source_id,
                "name": part.name,
                "cabinet_id": part.cabinet_id,
                "category": part.category.value,
                "material_id": part.material_id,
                "quantity": part.quantity,
                "status": "exported",
                "panel_id": panel_id,
            }
        )

    panel_groups = sorted(groups.values(), key=lambda group: group.panel_id)
    dxf_paths: list[Path] = []
    for group in panel_groups:
        path = _resolved_output_path(root, group.dxf_path)
        statuses, operation_issues = _write_panel_dxf(path, group, profile)
        group.operation_statuses.extend(statuses)
        issues.extend(operation_issues)
        dxf_paths.append(path)

    optimizer_path = output_paths["optimizer_csv"]
    optimizer_path.parent.mkdir(parents=True, exist_ok=True)
    with optimizer_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "Panel ID",
                "Part IDs",
                "Label",
                "Length",
                "Width",
                "Thickness",
                "Qty",
                "Material",
                "Thickness Name",
                "DXF File",
                "Grain",
                "Rotation Allowed",
                "Face",
                "Enabled",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for group in panel_groups:
            part = group.part
            writer.writerow(
                {
                    "Panel ID": group.panel_id,
                    "Part IDs": "|".join(sorted(group.part_ids)),
                    "Label": " | ".join(sorted(set(group.names))),
                    "Length": format_number(part.length_mm),
                    "Width": format_number(part.width_mm),
                    "Thickness": format_number(part.thickness_mm),
                    "Qty": group.quantity,
                    "Material": group.material.export_name,
                    "Thickness Name": group.material.thickness_name,
                    "DXF File": group.dxf_path,
                    "Grain": part.grain.value,
                    "Rotation Allowed": "TRUE" if part.rotation_allowed else "FALSE",
                    "Face": part.face.value,
                    "Enabled": "TRUE",
                }
            )

    profile_path = output_paths["profile_copy"]
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        _json_text(profile.to_dict()),
        encoding="utf-8",
        newline="\n",
    )

    final_issues = _deduplicate_issues(issues)
    validation_path = output_paths["validation_report"]
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text(
        _json_text(
            {
                "package_format": PACKAGE_FORMAT,
                "package_version": PACKAGE_VERSION,
                "valid": not any(
                    issue.severity == IssueSeverity.ERROR for issue in final_issues
                ),
                "summary": {
                    severity.value: sum(
                        issue.severity == severity for issue in final_issues
                    )
                    for severity in IssueSeverity
                },
                "issues": [_issue_dict(issue) for issue in final_issues],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    generated_records = [
        *(_file_record(root, path, "panel_dxf") for path in dxf_paths),
        _file_record(root, optimizer_path, "neutral_optimizer_csv"),
        _file_record(root, profile_path, "export_profile"),
        _file_record(root, validation_path, "validation_report"),
    ]
    manifest_path = output_paths["manifest"]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "package_format": PACKAGE_FORMAT,
        "package_version": PACKAGE_VERSION,
        "profile_id": profile.profile_id,
        "units": "mm",
        "compatibility": {
            "native_moz": False,
            "proprietary_project_file": False,
            "xml_emitted": False,
            "verified_mozaik_capability": "Manual panel-shape DXF import through the Shape Editor",
            "optimizer_csv_schema": "Home Builder neutral interchange; field mapping and an external import trial are required",
        },
        "project": {
            "project_id": project.project_id,
            "name": project.name,
            "source_path": project.source_path,
            "canonical_schema_version": project.schema_version,
        },
        "cabinets": [
            {
                "cabinet_id": cabinet.id,
                "source_id": cabinet.source_id,
                "name": cabinet.name,
                "part_ids": list(cabinet.part_ids),
                "room_name": cabinet.room_name,
                "wall_name": cabinet.wall_name,
            }
            for cabinet in project.cabinets
        ],
        "materials": [
            {
                "material_id": material.id,
                "name": material.name,
                "thickness_mm": material.thickness_mm,
                "grain": material.grain.value,
                "supplier_code": material.supplier_code,
                "canonical_export_name": material.export_name,
            }
            for material in project.materials
        ],
        "hardware": [
            {
                "hardware_id": item.id,
                "name": item.name,
                "quantity": item.quantity,
                "supplier_code": item.supplier_code,
                "cabinet_id": item.cabinet_id,
                "status": "manifest_only",
            }
            for item in project.hardware
        ],
        "stock": [
            {
                "stock_id": stock.id,
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
        "outputs": {
            "manifest": profile.output["manifest"],
            "optimizer_csv": profile.output["optimizer_csv"],
            "validation_report": profile.output["validation_report"],
            "profile": profile.output["profile_copy"],
            "panels_directory": profile.output["panels_directory"],
        },
        "panels": [
            {
                "panel_id": group.panel_id,
                "signature_sha256": group.signature,
                "dxf_file": group.dxf_path,
                "part_ids": sorted(group.part_ids),
                "source_ids": sorted(group.source_ids),
                "names": sorted(set(group.names)),
                "quantity": group.quantity,
                "length_mm": group.part.length_mm,
                "width_mm": group.part.width_mm,
                "thickness_mm": group.part.thickness_mm,
                "material": {
                    "source_id": group.material.source_id,
                    "source_name": group.material.source_name,
                    "export_name": group.material.export_name,
                    "thickness_name": group.material.thickness_name,
                },
                "grain": group.part.grain.value,
                "rotation_allowed": group.part.rotation_allowed,
                "face": group.part.face.value,
                "edge_banding": dict(group.part.edge_banding.as_tuple()),
                "machining": group.operation_statuses,
                "source_operations": sorted(
                    group.source_operations,
                    key=lambda item: item["part_id"],
                ),
            }
            for group in panel_groups
        ],
        "parts": sorted(part_records, key=lambda item: (item["part_id"], item["source_id"])),
        "files": sorted(generated_records, key=lambda item: item["path"]),
        "validation": {
            "valid": not any(
                issue.severity == IssueSeverity.ERROR for issue in final_issues
            ),
            "report": profile.output["validation_report"],
            "issue_count": len(final_issues),
        },
    }
    manifest_path.write_text(
        _json_text(manifest),
        encoding="utf-8",
        newline="\n",
    )

    files = tuple(
        sorted(
            (*dxf_paths, optimizer_path, profile_path, validation_path, manifest_path),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    return ExportResult(root, files, final_issues, len(panel_groups))


__all__ = [
    "DEFAULT_PROFILE_PATH",
    "DXF_LAYER_KEYS",
    "ExportResult",
    "MaterialMapping",
    "MozaikProfile",
    "PACKAGE_FORMAT",
    "PACKAGE_VERSION",
    "ResolvedMaterial",
    "export_package",
    "load_profile",
]
