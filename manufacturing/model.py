"""Versioned manufacturing domain model."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import math
from typing import Any

from .geometry import Polygon2D, rectangle_outline


SCHEMA_VERSION = 1
MM_PRECISION = 4


def mm(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("manufacturing dimensions must be finite")
    rounded = round(value, MM_PRECISION)
    return 0.0 if rounded == -0.0 else rounded


def positive_mm(value: float) -> float:
    return abs(mm(value))


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def stable_id(kind: str, *components: object) -> str:
    """Return a deterministic readable ID from source-stable components."""
    payload = "\x1f".join(str(component).strip() for component in components)
    digest = hashlib.sha256(f"{kind}\x1e{payload}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}-{digest}"


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class IssueSeverity(StringEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PartCategory(StringEnum):
    CARCASS_SIDE = "carcass_side"
    TOP = "top"
    BOTTOM = "bottom"
    BACK = "back"
    SHELF = "shelf"
    FILLER = "filler"
    DOOR = "door"
    DRAWER_FRONT = "drawer_front"
    DRAWER_PART = "drawer_part"
    TOE_KICK = "toe_kick"
    COUNTERTOP = "countertop"
    CUSTOM = "custom"


class GrainDirection(StringEnum):
    NONE = "none"
    LENGTH = "length"
    WIDTH = "width"


class Face(StringEnum):
    TOP = "top"
    BOTTOM = "bottom"
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class MachiningType(StringEnum):
    THROUGH_HOLE = "through_hole"
    BLIND_HOLE = "blind_hole"
    LINE_BORE = "line_bore"
    GROOVE = "groove"
    POCKET = "pocket"
    CONTOUR_CUTOUT = "contour_cutout"


@dataclass(frozen=True)
class ValidationIssue:
    severity: IssueSeverity
    code: str
    message: str
    source_id: str = ""
    details: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", IssueSeverity(self.severity))
        object.__setattr__(
            self,
            "details",
            tuple(
                sorted(
                    ((str(key), _freeze_value(value)) for key, value in self.details),
                    key=lambda item: item[0],
                )
            ),
        )

    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.severity.value,
            self.code,
            self.source_id,
            self.message,
            repr(self.details),
        )


@dataclass(frozen=True)
class Transform:
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        if len(self.translation_mm) != 3 or len(self.rotation_deg) != 3 or len(self.scale) != 3:
            raise ValueError("transforms require three translation, rotation, and scale values")
        object.__setattr__(self, "translation_mm", tuple(mm(value) for value in self.translation_mm))
        object.__setattr__(self, "rotation_deg", tuple(mm(value) for value in self.rotation_deg))
        object.__setattr__(self, "scale", tuple(mm(value) for value in self.scale))


@dataclass(frozen=True)
class EdgeBanding:
    front: str | None = None
    back: str | None = None
    left: str | None = None
    right: str | None = None

    def as_tuple(self) -> tuple[tuple[str, str | None], ...]:
        return (
            ("front", self.front),
            ("back", self.back),
            ("left", self.left),
            ("right", self.right),
        )


@dataclass(frozen=True)
class MachiningOperation:
    id: str
    operation_type: MachiningType
    face: Face
    x_mm: float = 0.0
    y_mm: float = 0.0
    end_x_mm: float | None = None
    end_y_mm: float | None = None
    diameter_mm: float | None = None
    depth_mm: float | None = None
    width_mm: float | None = None
    spacing_mm: float | None = None
    path: tuple[tuple[float, float], ...] = ()
    tool_hint: str | None = None
    parameters: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_type", MachiningType(self.operation_type))
        object.__setattr__(self, "face", Face(self.face))
        for name in (
            "x_mm",
            "y_mm",
            "end_x_mm",
            "end_y_mm",
            "diameter_mm",
            "depth_mm",
            "width_mm",
            "spacing_mm",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, mm(value))
        object.__setattr__(
            self,
            "path",
            tuple((mm(point[0]), mm(point[1])) for point in self.path),
        )
        object.__setattr__(
            self,
            "parameters",
            tuple(
                sorted(
                    ((str(key), _freeze_value(value)) for key, value in self.parameters),
                    key=lambda item: item[0],
                )
            ),
        )

    def sort_key(self) -> tuple[str, str, str]:
        return (self.id, self.operation_type.value, self.face.value)

    def validate(self, source_id: str = "") -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for name in ("diameter_mm", "depth_mm", "width_mm", "spacing_mm"):
            value = getattr(self, name)
            if value is not None and value < 0:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        f"machining.invalid_{name.removesuffix('_mm')}",
                        f"Machining {name.removesuffix('_mm')} cannot be negative",
                        source_id or self.id,
                    )
                )
        return tuple(sorted(issues, key=ValidationIssue.sort_key))


@dataclass(frozen=True)
class Material:
    id: str
    name: str
    thickness_mm: float
    grain: GrainDirection = GrainDirection.NONE
    supplier_code: str | None = None
    export_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "thickness_mm", positive_mm(self.thickness_mm))
        object.__setattr__(self, "grain", GrainDirection(self.grain))

    def sort_key(self) -> tuple[str, str, float]:
        return (self.id, self.name, self.thickness_mm)


@dataclass(frozen=True)
class HardwareItem:
    id: str
    name: str
    quantity: int = 1
    supplier_code: str | None = None
    cabinet_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", int(self.quantity))

    def sort_key(self) -> tuple[str, str]:
        return (self.id, self.name)


@dataclass(frozen=True)
class StockDefinition:
    id: str
    name: str
    width_mm: float
    height_mm: float
    material_id: str | None = None
    quantity: int | None = None
    cost: float | None = None
    is_remnant: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "width_mm", positive_mm(self.width_mm))
        object.__setattr__(self, "height_mm", positive_mm(self.height_mm))

    def sort_key(self) -> tuple[str, str]:
        return (self.id, self.name)


@dataclass(frozen=True)
class Cabinet:
    id: str
    name: str
    source_id: str
    part_ids: tuple[str, ...] = ()
    room_name: str | None = None
    wall_name: str | None = None
    transform: Transform = field(default_factory=Transform)

    def __post_init__(self) -> None:
        object.__setattr__(self, "part_ids", tuple(sorted(set(self.part_ids))))

    def sort_key(self) -> tuple[str, str]:
        return (self.id, self.name)


@dataclass(frozen=True)
class Part:
    id: str
    source_id: str
    cabinet_id: str
    name: str
    category: PartCategory
    quantity: int
    material_id: str | None
    length_mm: float
    width_mm: float
    thickness_mm: float
    outline: Polygon2D
    rotation_allowed: bool = True
    grain: GrainDirection = GrainDirection.NONE
    edge_banding: EdgeBanding = field(default_factory=EdgeBanding)
    face: Face = Face.TOP
    machining: tuple[MachiningOperation, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", PartCategory(self.category))
        object.__setattr__(self, "grain", GrainDirection(self.grain))
        object.__setattr__(self, "face", Face(self.face))
        object.__setattr__(self, "quantity", int(self.quantity))
        object.__setattr__(self, "length_mm", positive_mm(self.length_mm))
        object.__setattr__(self, "width_mm", positive_mm(self.width_mm))
        object.__setattr__(self, "thickness_mm", positive_mm(self.thickness_mm))
        object.__setattr__(self, "machining", tuple(sorted(self.machining, key=MachiningOperation.sort_key)))
        object.__setattr__(self, "issues", tuple(sorted(self.issues, key=ValidationIssue.sort_key)))

    def sort_key(self) -> tuple[str, str]:
        return (self.id, self.name)

    @classmethod
    def rectangular(
        cls,
        *,
        length_mm: float,
        width_mm: float,
        **kwargs: Any,
    ) -> "Part":
        return cls(
            length_mm=length_mm,
            width_mm=width_mm,
            outline=rectangle_outline(length_mm, width_mm),
            **kwargs,
        )

    def validate(self) -> tuple[ValidationIssue, ...]:
        issues = list(self.issues)
        if self.quantity < 1:
            issues.append(
                ValidationIssue(IssueSeverity.ERROR, "part.invalid_quantity", "Part quantity must be positive", self.id)
            )
        for name, value in (
            ("length", self.length_mm),
            ("width", self.width_mm),
            ("thickness", self.thickness_mm),
        ):
            if value <= 0:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        f"part.invalid_{name}",
                        f"Part {name} must be positive",
                        self.id,
                    )
                )
        for operation in self.machining:
            issues.extend(operation.validate(self.id))
        if self.outline.width > self.length_mm + 0.01 or self.outline.height > self.width_mm + 0.01:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "part.outline_out_of_bounds",
                    "Part outline exceeds its finished dimensions",
                    self.id,
                )
            )
        return _sorted_issues(issues)


def default_stock() -> tuple[StockDefinition, ...]:
    return (
        StockDefinition(
            id="stock-default-2440x1220",
            name="Default 2440 x 1220 mm sheet",
            width_mm=2440,
            height_mm=1220,
        ),
    )


@dataclass(frozen=True)
class ManufacturingProject:
    project_id: str
    name: str
    source_path: str | None = None
    schema_version: int = SCHEMA_VERSION
    units: str = "mm"
    cabinets: tuple[Cabinet, ...] = ()
    parts: tuple[Part, ...] = ()
    materials: tuple[Material, ...] = ()
    hardware: tuple[HardwareItem, ...] = ()
    stock: tuple[StockDefinition, ...] = field(default_factory=default_stock)
    issues: tuple[ValidationIssue, ...] = ()
    default_kerf_mm: float = 3.2
    default_sheet_margin_mm: float = 10.0
    default_part_spacing_mm: float = 6.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "cabinets", tuple(sorted(self.cabinets, key=Cabinet.sort_key)))
        object.__setattr__(self, "parts", tuple(sorted(self.parts, key=Part.sort_key)))
        object.__setattr__(self, "materials", tuple(sorted(self.materials, key=Material.sort_key)))
        object.__setattr__(self, "hardware", tuple(sorted(self.hardware, key=HardwareItem.sort_key)))
        object.__setattr__(self, "stock", tuple(sorted(self.stock, key=StockDefinition.sort_key)))
        object.__setattr__(self, "issues", tuple(sorted(self.issues, key=ValidationIssue.sort_key)))
        object.__setattr__(self, "default_kerf_mm", positive_mm(self.default_kerf_mm))
        object.__setattr__(self, "default_sheet_margin_mm", positive_mm(self.default_sheet_margin_mm))
        object.__setattr__(self, "default_part_spacing_mm", positive_mm(self.default_part_spacing_mm))

    def validate(self) -> tuple[ValidationIssue, ...]:
        issues = list(self.issues)
        if self.schema_version != SCHEMA_VERSION:
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "project.unsupported_schema",
                    f"Expected schema version {SCHEMA_VERSION}, got {self.schema_version}",
                    self.project_id,
                )
            )
        if self.units != "mm":
            issues.append(
                ValidationIssue(
                    IssueSeverity.ERROR,
                    "project.invalid_units",
                    "ManufacturingProject units must be mm",
                    self.project_id,
                )
            )

        for collection_name, collection in (
            ("cabinet", self.cabinets),
            ("part", self.parts),
            ("material", self.materials),
            ("hardware", self.hardware),
            ("stock", self.stock),
        ):
            identifiers = [item.id for item in collection]
            if len(identifiers) != len(set(identifiers)):
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        f"project.duplicate_{collection_name}_id",
                        f"Duplicate {collection_name} IDs are not allowed",
                        self.project_id,
                    )
                )

        cabinet_ids = {cabinet.id for cabinet in self.cabinets}
        part_ids = {part.id for part in self.parts}
        material_ids = {material.id for material in self.materials}
        for material in self.materials:
            if material.thickness_mm <= 0:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "material.invalid_thickness",
                        "Material thickness must be positive",
                        material.id,
                    )
                )
        for item in self.hardware:
            if item.quantity < 1:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "hardware.invalid_quantity",
                        "Hardware quantity must be positive",
                        item.id,
                    )
                )
        for stock in self.stock:
            if stock.width_mm <= 0 or stock.height_mm <= 0:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "stock.invalid_dimensions",
                        "Stock dimensions must be positive",
                        stock.id,
                    )
                )
            if stock.material_id and stock.material_id not in material_ids:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "stock.missing_material",
                        "Stock references an unknown material",
                        stock.id,
                    )
                )
        for part in self.parts:
            issues.extend(part.validate())
            if part.cabinet_id not in cabinet_ids:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "part.missing_cabinet",
                        "Part references an unknown cabinet",
                        part.id,
                    )
                )
            if part.material_id and part.material_id not in material_ids:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "part.missing_material",
                        "Part references an unknown material",
                        part.id,
                    )
                )
        for cabinet in self.cabinets:
            missing = set(cabinet.part_ids) - part_ids
            if missing:
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "cabinet.missing_parts",
                        "Cabinet references unknown parts",
                        cabinet.id,
                        (("part_ids", ",".join(sorted(missing))),),
                    )
                )
        return _sorted_issues(issues)

    def with_validation_issues(self) -> "ManufacturingProject":
        return replace(self, issues=self.validate())


def _sorted_issues(issues: list[ValidationIssue] | tuple[ValidationIssue, ...]) -> tuple[ValidationIssue, ...]:
    unique = {issue.sort_key(): issue for issue in issues}
    return tuple(unique[key] for key in sorted(unique))
