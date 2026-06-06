"""Deterministic sheet-stock nesting and neutral result exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import csv
from html import escape
import io
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from .geometry import EPSILON_MM, Point2D, Polygon2D, point_in_loop
from .model import (
    GrainDirection,
    IssueSeverity,
    ManufacturingProject,
    Material,
    Part,
    StockDefinition,
    ValidationIssue,
    mm,
)


NESTING_SCHEMA_VERSION = 1
PLACEMENT_EPSILON_MM = 1e-4


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class NestingStrategy(StringEnum):
    RECTANGULAR_GUILLOTINE = "rectangular_guillotine"
    POLYGON = "polygon"


class RotationPolicy(StringEnum):
    RESPECT_PART = "respect_part"
    NEVER = "never"


@dataclass(frozen=True)
class StockSpec:
    """A stock option used by the optimizer.

    ``quantity=None`` means the stock may be opened as often as needed.
    ``material_id=None`` and ``thickness_mm=None`` make a stock option generic.
    """

    id: str
    name: str
    width_mm: float
    height_mm: float
    material_id: str | None = None
    thickness_mm: float | None = None
    quantity: int | None = None
    cost: float | None = None
    is_remnant: bool = False
    grain: GrainDirection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "width_mm", abs(mm(self.width_mm)))
        object.__setattr__(self, "height_mm", abs(mm(self.height_mm)))
        if self.thickness_mm is not None:
            object.__setattr__(self, "thickness_mm", abs(mm(self.thickness_mm)))
        if self.quantity is not None:
            object.__setattr__(self, "quantity", max(0, int(self.quantity)))
        if self.grain is not None:
            object.__setattr__(self, "grain", GrainDirection(self.grain))

    @classmethod
    def from_definition(
        cls,
        stock: StockDefinition,
        materials: dict[str, Material],
    ) -> "StockSpec":
        material = materials.get(stock.material_id or "")
        return cls(
            id=stock.id,
            name=stock.name,
            width_mm=stock.width_mm,
            height_mm=stock.height_mm,
            material_id=stock.material_id,
            thickness_mm=material.thickness_mm if material else None,
            quantity=stock.quantity,
            cost=stock.cost,
            is_remnant=stock.is_remnant,
            grain=material.grain if material else None,
        )

    def sort_key(self) -> tuple[int, float, str]:
        return (0 if self.is_remnant else 1, self.width_mm * self.height_mm, self.id)


@dataclass(frozen=True)
class NestingConfig:
    strategy: NestingStrategy = NestingStrategy.RECTANGULAR_GUILLOTINE
    stock: tuple[StockSpec | StockDefinition, ...] | None = None
    kerf_mm: float | None = None
    margin_mm: float | None = None
    spacing_mm: float | None = None
    rotation_policy: RotationPolicy = RotationPolicy.RESPECT_PART

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy", NestingStrategy(self.strategy))
        object.__setattr__(self, "rotation_policy", RotationPolicy(self.rotation_policy))
        if self.stock is not None:
            object.__setattr__(self, "stock", tuple(self.stock))
        for name in ("kerf_mm", "margin_mm", "spacing_mm"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, abs(mm(value)))


@dataclass(frozen=True)
class NestingPlacement:
    sheet_id: str
    part_id: str
    part_name: str
    instance: int
    material_id: str
    thickness_mm: float
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotation_deg: int
    area_mm2: float
    polygon: Polygon2D

    def sort_key(self) -> tuple[str, float, float, str, int]:
        return (self.sheet_id, self.y_mm, self.x_mm, self.part_id, self.instance)


@dataclass(frozen=True)
class NestingSheet:
    id: str
    stock_id: str
    stock_name: str
    material_id: str
    material_name: str
    thickness_mm: float
    width_mm: float
    height_mm: float
    grain: GrainDirection
    is_remnant: bool
    placements: tuple[NestingPlacement, ...]
    used_area_mm2: float
    stock_area_mm2: float
    usable_area_mm2: float
    waste_area_mm2: float
    utilization: float

    def sort_key(self) -> str:
        return self.id


@dataclass(frozen=True)
class UnplacedPart:
    part_id: str
    part_name: str
    instance: int
    material_id: str | None
    thickness_mm: float
    reason: str
    message: str

    def sort_key(self) -> tuple[str, int, str]:
        return (self.part_id, self.instance, self.reason)


@dataclass(frozen=True)
class MaterialSummary:
    material_id: str
    material_name: str
    thickness_mm: float
    placed_parts: int
    unplaced_parts: int
    sheet_count: int
    part_area_mm2: float
    stock_area_mm2: float
    waste_area_mm2: float
    utilization: float

    def sort_key(self) -> tuple[str, float]:
        return (self.material_id, self.thickness_mm)


@dataclass(frozen=True)
class NestingResult:
    project_id: str
    strategy: NestingStrategy
    kerf_mm: float
    margin_mm: float
    spacing_mm: float
    rotation_policy: RotationPolicy
    sheets: tuple[NestingSheet, ...] = ()
    unplaced_parts: tuple[UnplacedPart, ...] = ()
    summaries: tuple[MaterialSummary, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    schema_version: int = NESTING_SCHEMA_VERSION

    @property
    def clearance_mm(self) -> float:
        return mm(self.kerf_mm + self.spacing_mm)

    @property
    def placed_part_count(self) -> int:
        return sum(len(sheet.placements) for sheet in self.sheets)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == IssueSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class _ResolvedConfig:
    strategy: NestingStrategy
    stock: tuple[StockSpec, ...]
    kerf_mm: float
    margin_mm: float
    spacing_mm: float
    rotation_policy: RotationPolicy

    @property
    def clearance_mm(self) -> float:
        return mm(self.kerf_mm + self.spacing_mm)


@dataclass(frozen=True)
class _PartInstance:
    part: Part
    instance: int

    def sort_key(self) -> tuple[float, float, str, int]:
        return (
            -self.part.outline.area,
            -max(self.part.outline.width, self.part.outline.height),
            self.part.id,
            self.instance,
        )


@dataclass(frozen=True)
class _FreeRect:
    x: float
    y: float
    width: float
    height: float


@dataclass
class _WorkingSheet:
    id: str
    stock: StockSpec
    material: Material
    thickness_mm: float
    grain: GrainDirection
    placements: list[NestingPlacement] = field(default_factory=list)
    free_rects: list[_FreeRect] = field(default_factory=list)


class _StockInventory:
    def __init__(self, stock: Sequence[StockSpec]) -> None:
        self.stock = tuple(sorted(stock, key=StockSpec.sort_key))
        self.used: dict[str, int] = {}

    def available(self, stock: StockSpec) -> bool:
        return stock.quantity is None or self.used.get(stock.id, 0) < stock.quantity

    def consume(self, stock: StockSpec) -> None:
        self.used[stock.id] = self.used.get(stock.id, 0) + 1


class NestingOptimizer:
    """Optimize a canonical :class:`ManufacturingProject`.

    Strategies share stock matching, grain rules, result models, validation,
    summaries, and exporters. The optimizer never reads Blender objects.
    """

    strategies = tuple(strategy.value for strategy in NestingStrategy)

    def optimize(
        self,
        project: ManufacturingProject,
        config: NestingConfig | None = None,
    ) -> NestingResult:
        resolved = _resolve_config(project, config or NestingConfig())
        inventory = _StockInventory(resolved.stock)
        materials = {material.id: material for material in project.materials}
        working_sheets: list[_WorkingSheet] = []
        unplaced: list[UnplacedPart] = []
        groups: dict[tuple[str, float], list[_PartInstance]] = {}

        for part in project.parts:
            for instance in range(1, max(0, part.quantity) + 1):
                item = _PartInstance(part, instance)
                if not part.material_id or part.material_id not in materials:
                    unplaced.append(
                        _unplaced(item, "missing_material", "Part has no known material")
                    )
                    continue
                groups.setdefault((part.material_id, part.thickness_mm), []).append(item)

        for (material_id, thickness_mm), instances in sorted(groups.items()):
            material = materials[material_id]
            ordered = sorted(instances, key=_PartInstance.sort_key)
            if resolved.strategy == NestingStrategy.RECTANGULAR_GUILLOTINE:
                self._place_rectangular_group(
                    ordered,
                    material,
                    thickness_mm,
                    resolved,
                    inventory,
                    working_sheets,
                    unplaced,
                )
            elif resolved.strategy == NestingStrategy.POLYGON:
                self._place_polygon_group(
                    ordered,
                    material,
                    thickness_mm,
                    resolved,
                    inventory,
                    working_sheets,
                    unplaced,
                )
            else:  # pragma: no cover - enum construction rejects this.
                raise ValueError(f"unknown nesting strategy: {resolved.strategy}")

        sheets = tuple(
            _finalize_sheet(sheet, resolved.margin_mm)
            for sheet in sorted(working_sheets, key=lambda value: value.id)
        )
        preliminary = NestingResult(
            project_id=project.project_id,
            strategy=resolved.strategy,
            kerf_mm=resolved.kerf_mm,
            margin_mm=resolved.margin_mm,
            spacing_mm=resolved.spacing_mm,
            rotation_policy=resolved.rotation_policy,
            sheets=sheets,
            unplaced_parts=tuple(sorted(unplaced, key=UnplacedPart.sort_key)),
        )
        combined_issues = {
            issue.sort_key(): issue
            for issue in (*project.validate(), *validate_result(preliminary))
        }
        issues = tuple(combined_issues[key] for key in sorted(combined_issues))
        return NestingResult(
            project_id=preliminary.project_id,
            strategy=preliminary.strategy,
            kerf_mm=preliminary.kerf_mm,
            margin_mm=preliminary.margin_mm,
            spacing_mm=preliminary.spacing_mm,
            rotation_policy=preliminary.rotation_policy,
            sheets=preliminary.sheets,
            unplaced_parts=preliminary.unplaced_parts,
            summaries=_summaries(preliminary, materials),
            issues=issues,
        )

    def _place_rectangular_group(
        self,
        instances: Sequence[_PartInstance],
        material: Material,
        thickness_mm: float,
        config: _ResolvedConfig,
        inventory: _StockInventory,
        all_sheets: list[_WorkingSheet],
        unplaced: list[UnplacedPart],
    ) -> None:
        group_sheets: list[_WorkingSheet] = []
        for item in instances:
            if not _is_rectangle(item.part.outline):
                unplaced.append(
                    _unplaced(
                        item,
                        "strategy_requires_rectangle",
                        "Rectangular guillotine strategy cannot place shaped parts",
                    )
                )
                continue

            candidate = _best_rectangular_candidate(item, group_sheets, config)
            if candidate is None:
                stock, reason = _select_stock(
                    item,
                    material,
                    thickness_mm,
                    config,
                    inventory,
                    polygon=False,
                )
                if stock is None:
                    unplaced.append(_unplaced_for_stock(item, reason))
                    continue
                sheet = _open_sheet(stock, material, thickness_mm, config, all_sheets)
                inventory.consume(stock)
                group_sheets.append(sheet)
                candidate = _best_rectangular_candidate(item, (sheet,), config)
                if candidate is None:
                    unplaced.append(
                        _unplaced(
                            item,
                            "placement_failed",
                            "Part passed stock-fit checks but could not be placed",
                        )
                    )
                    continue

            sheet, free_index, rotation, width, height = candidate
            free = sheet.free_rects.pop(free_index)
            polygon = _place_polygon(
                _rotate_polygon(item.part.outline, rotation),
                free.x,
                free.y,
            )
            sheet.placements.append(
                _placement(item, sheet, polygon, rotation, free.x, free.y)
            )
            sheet.free_rects.extend(
                _split_guillotine(free, width, height, config.clearance_mm)
            )
            sheet.free_rects.sort(key=lambda value: (value.y, value.x, value.width, value.height))

    def _place_polygon_group(
        self,
        instances: Sequence[_PartInstance],
        material: Material,
        thickness_mm: float,
        config: _ResolvedConfig,
        inventory: _StockInventory,
        all_sheets: list[_WorkingSheet],
        unplaced: list[UnplacedPart],
    ) -> None:
        group_sheets: list[_WorkingSheet] = []
        for item in instances:
            candidate = _best_polygon_candidate(item, group_sheets, config)
            if candidate is None:
                stock, reason = _select_stock(
                    item,
                    material,
                    thickness_mm,
                    config,
                    inventory,
                    polygon=True,
                )
                if stock is None:
                    unplaced.append(_unplaced_for_stock(item, reason))
                    continue
                sheet = _open_sheet(stock, material, thickness_mm, config, all_sheets)
                inventory.consume(stock)
                group_sheets.append(sheet)
                candidate = _best_polygon_candidate(item, (sheet,), config)
                if candidate is None:
                    unplaced.append(
                        _unplaced(
                            item,
                            "placement_failed",
                            "Part passed stock-fit checks but could not be placed",
                        )
                    )
                    continue

            sheet, polygon, rotation, x, y = candidate
            sheet.placements.append(_placement(item, sheet, polygon, rotation, x, y))


def optimize(
    project: ManufacturingProject,
    config: NestingConfig | None = None,
) -> NestingResult:
    return NestingOptimizer().optimize(project, config)


def _resolve_config(project: ManufacturingProject, config: NestingConfig) -> _ResolvedConfig:
    materials = {material.id: material for material in project.materials}
    source_stock = project.stock if config.stock is None else config.stock
    stock: list[StockSpec] = []
    for item in source_stock:
        if isinstance(item, StockSpec):
            stock.append(item)
        elif isinstance(item, StockDefinition):
            stock.append(StockSpec.from_definition(item, materials))
        else:
            raise TypeError(f"unsupported nesting stock type: {type(item).__name__}")
    return _ResolvedConfig(
        strategy=config.strategy,
        stock=tuple(stock),
        kerf_mm=project.default_kerf_mm if config.kerf_mm is None else config.kerf_mm,
        margin_mm=(
            project.default_sheet_margin_mm
            if config.margin_mm is None
            else config.margin_mm
        ),
        spacing_mm=(
            project.default_part_spacing_mm
            if config.spacing_mm is None
            else config.spacing_mm
        ),
        rotation_policy=config.rotation_policy,
    )


def _unplaced(item: _PartInstance, reason: str, message: str) -> UnplacedPart:
    return UnplacedPart(
        part_id=item.part.id,
        part_name=item.part.name,
        instance=item.instance,
        material_id=item.part.material_id,
        thickness_mm=item.part.thickness_mm,
        reason=reason,
        message=message,
    )


def _unplaced_for_stock(item: _PartInstance, reason: str) -> UnplacedPart:
    messages = {
        "no_stock": "No stock matches the part material and thickness",
        "stock_exhausted": "All matching finite stock has been used",
        "part_does_not_fit_stock": "Part does not fit any matching stock option",
    }
    return _unplaced(item, reason, messages[reason])


def _stock_matches(
    stock: StockSpec,
    material_id: str,
    thickness_mm: float,
) -> bool:
    if stock.material_id is not None and stock.material_id != material_id:
        return False
    return (
        stock.thickness_mm is None
        or abs(stock.thickness_mm - thickness_mm) <= PLACEMENT_EPSILON_MM
    )


def _resolved_stock_grain(stock: StockSpec, material: Material) -> GrainDirection:
    return stock.grain if stock.grain is not None else material.grain


def _select_stock(
    item: _PartInstance,
    material: Material,
    thickness_mm: float,
    config: _ResolvedConfig,
    inventory: _StockInventory,
    *,
    polygon: bool,
) -> tuple[StockSpec | None, str]:
    matching = [
        stock
        for stock in inventory.stock
        if _stock_matches(stock, material.id, thickness_mm)
        and stock.width_mm > 2 * config.margin_mm
        and stock.height_mm > 2 * config.margin_mm
    ]
    if not matching:
        return None, "no_stock"

    fitting = [
        stock
        for stock in matching
        if _part_fits_empty_stock(item.part, stock, material, config, polygon=polygon)
    ]
    if not fitting:
        return None, "part_does_not_fit_stock"

    available = [stock for stock in fitting if inventory.available(stock)]
    if not available:
        return None, "stock_exhausted"
    return min(available, key=StockSpec.sort_key), ""


def _part_fits_empty_stock(
    part: Part,
    stock: StockSpec,
    material: Material,
    config: _ResolvedConfig,
    *,
    polygon: bool,
) -> bool:
    if not polygon and not _is_rectangle(part.outline):
        return False
    usable_width = stock.width_mm - (2 * config.margin_mm)
    usable_height = stock.height_mm - (2 * config.margin_mm)
    grain = _resolved_stock_grain(stock, material)
    for rotation in _allowed_rotations(part, grain, config.rotation_policy):
        shape = _rotate_polygon(part.outline, rotation)
        if (
            shape.width <= usable_width + PLACEMENT_EPSILON_MM
            and shape.height <= usable_height + PLACEMENT_EPSILON_MM
        ):
            return True
    return False


def _open_sheet(
    stock: StockSpec,
    material: Material,
    thickness_mm: float,
    config: _ResolvedConfig,
    all_sheets: list[_WorkingSheet],
) -> _WorkingSheet:
    sheet = _WorkingSheet(
        id=f"sheet-{len(all_sheets) + 1:04d}",
        stock=stock,
        material=material,
        thickness_mm=thickness_mm,
        grain=_resolved_stock_grain(stock, material),
    )
    usable_width = stock.width_mm - (2 * config.margin_mm)
    usable_height = stock.height_mm - (2 * config.margin_mm)
    if usable_width > 0 and usable_height > 0:
        sheet.free_rects.append(
            _FreeRect(config.margin_mm, config.margin_mm, usable_width, usable_height)
        )
    all_sheets.append(sheet)
    return sheet


def _allowed_rotations(
    part: Part,
    stock_grain: GrainDirection,
    policy: RotationPolicy,
) -> tuple[int, ...]:
    rotations = [0]
    if policy == RotationPolicy.RESPECT_PART and part.rotation_allowed:
        rotations.append(90)
    return tuple(
        rotation
        for rotation in rotations
        if _grain_aligned(part.grain, stock_grain, rotation)
    )


def _grain_aligned(
    part_grain: GrainDirection,
    stock_grain: GrainDirection,
    rotation: int,
) -> bool:
    if part_grain == GrainDirection.NONE or stock_grain == GrainDirection.NONE:
        return True
    part_axis = "x" if part_grain == GrainDirection.LENGTH else "y"
    if rotation % 180 == 90:
        part_axis = "y" if part_axis == "x" else "x"
    stock_axis = "x" if stock_grain == GrainDirection.LENGTH else "y"
    return part_axis == stock_axis


def _best_rectangular_candidate(
    item: _PartInstance,
    sheets: Sequence[_WorkingSheet],
    config: _ResolvedConfig,
) -> tuple[_WorkingSheet, int, int, float, float] | None:
    candidates: list[
        tuple[tuple[float, float, float, str, int, int], _WorkingSheet, int, int, float, float]
    ] = []
    for sheet in sheets:
        for rotation in _allowed_rotations(
            item.part, sheet.grain, config.rotation_policy
        ):
            width = item.part.outline.width if rotation == 0 else item.part.outline.height
            height = item.part.outline.height if rotation == 0 else item.part.outline.width
            for index, free in enumerate(sheet.free_rects):
                if (
                    width <= free.width + PLACEMENT_EPSILON_MM
                    and height <= free.height + PLACEMENT_EPSILON_MM
                ):
                    waste = (free.width * free.height) - (width * height)
                    score = (
                        waste,
                        min(free.width - width, free.height - height),
                        free.y,
                        sheet.id,
                        rotation,
                        index,
                    )
                    candidates.append(
                        (score, sheet, index, rotation, width, height)
                    )
    if not candidates:
        return None
    _, sheet, index, rotation, width, height = min(
        candidates, key=lambda value: value[0]
    )
    return sheet, index, rotation, width, height


def _split_guillotine(
    free: _FreeRect,
    width: float,
    height: float,
    clearance: float,
) -> tuple[_FreeRect, ...]:
    remaining_width = max(0.0, free.width - width)
    remaining_height = max(0.0, free.height - height)
    horizontal_first = remaining_width <= remaining_height
    result: list[_FreeRect] = []

    def add(x: float, y: float, candidate_width: float, candidate_height: float) -> None:
        if (
            candidate_width > PLACEMENT_EPSILON_MM
            and candidate_height > PLACEMENT_EPSILON_MM
        ):
            result.append(
                _FreeRect(mm(x), mm(y), mm(candidate_width), mm(candidate_height))
            )

    gap_x = clearance if remaining_width > PLACEMENT_EPSILON_MM else 0.0
    gap_y = clearance if remaining_height > PLACEMENT_EPSILON_MM else 0.0
    if horizontal_first:
        add(
            free.x,
            free.y + height + gap_y,
            free.width,
            remaining_height - gap_y,
        )
        add(
            free.x + width + gap_x,
            free.y,
            remaining_width - gap_x,
            height,
        )
    else:
        add(
            free.x + width + gap_x,
            free.y,
            remaining_width - gap_x,
            free.height,
        )
        add(
            free.x,
            free.y + height + gap_y,
            width,
            remaining_height - gap_y,
        )
    return tuple(result)


def _best_polygon_candidate(
    item: _PartInstance,
    sheets: Sequence[_WorkingSheet],
    config: _ResolvedConfig,
) -> tuple[_WorkingSheet, Polygon2D, int, float, float] | None:
    choices: list[
        tuple[tuple[float, float, str, int], _WorkingSheet, Polygon2D, int, float, float]
    ] = []
    for sheet in sheets:
        for rotation in _allowed_rotations(
            item.part, sheet.grain, config.rotation_policy
        ):
            local = _rotate_polygon(item.part.outline, rotation)
            for x, y in _candidate_translations(local, sheet, config):
                polygon = _place_polygon(local, x, y)
                if _polygon_fits_sheet(polygon, sheet, config.margin_mm) and all(
                    _polygons_clear(
                        polygon,
                        placed.polygon,
                        config.clearance_mm,
                    )
                    for placed in sheet.placements
                ):
                    choices.append(
                        ((y, x, sheet.id, rotation), sheet, polygon, rotation, x, y)
                    )
                    break
    if not choices:
        return None
    _, sheet, polygon, rotation, x, y = min(choices, key=lambda value: value[0])
    return sheet, polygon, rotation, x, y


def _candidate_translations(
    polygon: Polygon2D,
    sheet: _WorkingSheet,
    config: _ResolvedConfig,
) -> tuple[tuple[float, float], ...]:
    margin = config.margin_mm
    right = sheet.stock.width_mm - margin - polygon.width
    top = sheet.stock.height_mm - margin - polygon.height
    xs = {margin, right}
    ys = {margin, top}
    moving_x = sorted({point.x for loop in _loops(polygon) for point in loop})
    moving_y = sorted({point.y for loop in _loops(polygon) for point in loop})
    clearance = config.clearance_mm

    for placement in sheet.placements:
        placed = placement.polygon
        min_x, min_y, max_x, max_y = placed.bounds
        xs.update(
            {
                max_x + clearance,
                min_x - polygon.width - clearance,
                min_x,
                max_x - polygon.width,
            }
        )
        ys.update(
            {
                max_y + clearance,
                min_y - polygon.height - clearance,
                min_y,
                max_y - polygon.height,
            }
        )
        placed_x = sorted({point.x for loop in _loops(placed) for point in loop})
        placed_y = sorted({point.y for loop in _loops(placed) for point in loop})
        if not _is_rectangle(placed) or not _is_rectangle(polygon):
            for target in placed_x:
                for source in moving_x:
                    xs.update(
                        {
                            target - source,
                            target - source - clearance,
                            target - source + clearance,
                        }
                    )
            for target in placed_y:
                for source in moving_y:
                    ys.update(
                        {
                            target - source,
                            target - source - clearance,
                            target - source + clearance,
                        }
                    )

    candidates = {
        (mm(x), mm(y))
        for y in ys
        for x in xs
        if x >= margin - PLACEMENT_EPSILON_MM
        and y >= margin - PLACEMENT_EPSILON_MM
        and x <= right + PLACEMENT_EPSILON_MM
        and y <= top + PLACEMENT_EPSILON_MM
    }
    return tuple(sorted(candidates, key=lambda value: (value[1], value[0])))


def _rotate_polygon(polygon: Polygon2D, rotation: int) -> Polygon2D:
    if rotation % 180 == 0:
        return polygon

    def rotate(loop: Sequence[Point2D]) -> tuple[Point2D, ...]:
        return tuple(Point2D(-point.y, point.x) for point in loop)

    rotated = Polygon2D(
        rotate(polygon.outer),
        tuple(rotate(loop) for loop in polygon.cutouts),
    )
    minimum_x, minimum_y, _, _ = rotated.bounds
    return _place_polygon(rotated, -minimum_x, -minimum_y)


def _place_polygon(polygon: Polygon2D, x: float, y: float) -> Polygon2D:
    def move(loop: Sequence[Point2D]) -> tuple[Point2D, ...]:
        return tuple(Point2D(point.x + x, point.y + y) for point in loop)

    return Polygon2D(
        move(polygon.outer),
        tuple(move(loop) for loop in polygon.cutouts),
    )


def _placement(
    item: _PartInstance,
    sheet: _WorkingSheet,
    polygon: Polygon2D,
    rotation: int,
    x: float,
    y: float,
) -> NestingPlacement:
    return NestingPlacement(
        sheet_id=sheet.id,
        part_id=item.part.id,
        part_name=item.part.name,
        instance=item.instance,
        material_id=item.part.material_id or "",
        thickness_mm=item.part.thickness_mm,
        x_mm=mm(x),
        y_mm=mm(y),
        width_mm=polygon.width,
        height_mm=polygon.height,
        rotation_deg=rotation,
        area_mm2=mm(item.part.outline.area),
        polygon=polygon,
    )


def _is_rectangle(polygon: Polygon2D) -> bool:
    if polygon.cutouts or len(polygon.outer) != 4:
        return False
    minimum_x, minimum_y, maximum_x, maximum_y = polygon.bounds
    corners = {
        Point2D(minimum_x, minimum_y),
        Point2D(maximum_x, minimum_y),
        Point2D(maximum_x, maximum_y),
        Point2D(minimum_x, maximum_y),
    }
    return set(polygon.outer) == corners


def _loops(polygon: Polygon2D) -> tuple[tuple[Point2D, ...], ...]:
    return (polygon.outer,) + polygon.cutouts


def _segments(loop: Sequence[Point2D]) -> Iterable[tuple[Point2D, Point2D]]:
    for index, point in enumerate(loop):
        yield point, loop[(index + 1) % len(loop)]


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _proper_segments_intersect(
    a: Point2D,
    b: Point2D,
    c: Point2D,
    d: Point2D,
) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    return (
        ((ab_c > EPSILON_MM and ab_d < -EPSILON_MM) or (ab_c < -EPSILON_MM and ab_d > EPSILON_MM))
        and ((cd_a > EPSILON_MM and cd_b < -EPSILON_MM) or (cd_a < -EPSILON_MM and cd_b > EPSILON_MM))
    )


def _point_on_loop(point: Point2D, loop: Sequence[Point2D]) -> bool:
    for start, end in _segments(loop):
        if abs(_orientation(start, end, point)) > EPSILON_MM:
            continue
        if (
            min(start.x, end.x) - EPSILON_MM
            <= point.x
            <= max(start.x, end.x) + EPSILON_MM
            and min(start.y, end.y) - EPSILON_MM
            <= point.y
            <= max(start.y, end.y) + EPSILON_MM
        ):
            return True
    return False


def _point_in_filled_polygon(point: Point2D, polygon: Polygon2D) -> bool:
    if _point_on_loop(point, polygon.outer) or any(
        _point_on_loop(point, loop) for loop in polygon.cutouts
    ):
        return False
    return point_in_loop(point, polygon.outer) and not any(
        point_in_loop(point, loop) for loop in polygon.cutouts
    )


def _loop_samples(loop: Sequence[Point2D]) -> tuple[Point2D, ...]:
    samples = list(loop)
    samples.extend(
        Point2D((start.x + end.x) / 2, (start.y + end.y) / 2)
        for start, end in _segments(loop)
    )
    return tuple(samples)


def _polygons_overlap(first: Polygon2D, second: Polygon2D) -> bool:
    first_bounds = first.bounds
    second_bounds = second.bounds
    if (
        first_bounds[2] <= second_bounds[0] + PLACEMENT_EPSILON_MM
        or second_bounds[2] <= first_bounds[0] + PLACEMENT_EPSILON_MM
        or first_bounds[3] <= second_bounds[1] + PLACEMENT_EPSILON_MM
        or second_bounds[3] <= first_bounds[1] + PLACEMENT_EPSILON_MM
    ):
        return False
    for first_loop in _loops(first):
        for second_loop in _loops(second):
            for a, b in _segments(first_loop):
                for c, d in _segments(second_loop):
                    if _proper_segments_intersect(a, b, c, d):
                        return True
    if any(
        _point_in_filled_polygon(point, second)
        for point in _loop_samples(first.outer)
    ):
        return True
    if any(
        _point_in_filled_polygon(point, first)
        for point in _loop_samples(second.outer)
    ):
        return True
    return first.outer == second.outer


def _point_segment_distance(point: Point2D, start: Point2D, end: Point2D) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    denominator = (dx * dx) + (dy * dy)
    if denominator <= EPSILON_MM:
        return math.hypot(point.x - start.x, point.y - start.y)
    ratio = (
        ((point.x - start.x) * dx) + ((point.y - start.y) * dy)
    ) / denominator
    ratio = max(0.0, min(1.0, ratio))
    projection_x = start.x + (ratio * dx)
    projection_y = start.y + (ratio * dy)
    return math.hypot(point.x - projection_x, point.y - projection_y)


def _segment_distance(
    a: Point2D,
    b: Point2D,
    c: Point2D,
    d: Point2D,
) -> float:
    if _proper_segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _polygon_boundary_distance(first: Polygon2D, second: Polygon2D) -> float:
    distance = math.inf
    for first_loop in _loops(first):
        for second_loop in _loops(second):
            for a, b in _segments(first_loop):
                for c, d in _segments(second_loop):
                    distance = min(distance, _segment_distance(a, b, c, d))
                    if distance <= PLACEMENT_EPSILON_MM:
                        return 0.0
    return distance


def _polygons_clear(
    first: Polygon2D,
    second: Polygon2D,
    clearance: float,
) -> bool:
    if _polygons_overlap(first, second):
        return False
    return (
        clearance <= PLACEMENT_EPSILON_MM
        or _polygon_boundary_distance(first, second)
        >= clearance - PLACEMENT_EPSILON_MM
    )


def _polygon_fits_sheet(
    polygon: Polygon2D,
    sheet: _WorkingSheet,
    margin: float,
) -> bool:
    minimum_x, minimum_y, maximum_x, maximum_y = polygon.bounds
    return (
        minimum_x >= margin - PLACEMENT_EPSILON_MM
        and minimum_y >= margin - PLACEMENT_EPSILON_MM
        and maximum_x <= sheet.stock.width_mm - margin + PLACEMENT_EPSILON_MM
        and maximum_y <= sheet.stock.height_mm - margin + PLACEMENT_EPSILON_MM
    )


def _finalize_sheet(sheet: _WorkingSheet, margin: float) -> NestingSheet:
    placements = tuple(sorted(sheet.placements, key=NestingPlacement.sort_key))
    used_area = mm(sum(placement.area_mm2 for placement in placements))
    stock_area = mm(sheet.stock.width_mm * sheet.stock.height_mm)
    usable_area = mm(
        max(0.0, sheet.stock.width_mm - (2 * margin))
        * max(0.0, sheet.stock.height_mm - (2 * margin))
    )
    waste = mm(max(0.0, stock_area - used_area))
    utilization = round(used_area / stock_area, 6) if stock_area else 0.0
    return NestingSheet(
        id=sheet.id,
        stock_id=sheet.stock.id,
        stock_name=sheet.stock.name,
        material_id=sheet.material.id,
        material_name=sheet.material.name,
        thickness_mm=sheet.thickness_mm,
        width_mm=sheet.stock.width_mm,
        height_mm=sheet.stock.height_mm,
        grain=sheet.grain,
        is_remnant=sheet.stock.is_remnant,
        placements=placements,
        used_area_mm2=used_area,
        stock_area_mm2=stock_area,
        usable_area_mm2=usable_area,
        waste_area_mm2=waste,
        utilization=utilization,
    )


def validate_result(result: NestingResult) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    clearance = result.clearance_mm
    for sheet in result.sheets:
        for placement in sheet.placements:
            minimum_x, minimum_y, maximum_x, maximum_y = placement.polygon.bounds
            if (
                minimum_x < result.margin_mm - PLACEMENT_EPSILON_MM
                or minimum_y < result.margin_mm - PLACEMENT_EPSILON_MM
                or maximum_x
                > sheet.width_mm - result.margin_mm + PLACEMENT_EPSILON_MM
                or maximum_y
                > sheet.height_mm - result.margin_mm + PLACEMENT_EPSILON_MM
            ):
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "nesting.out_of_bounds",
                        "Placement lies outside the usable sheet bounds",
                        placement.part_id,
                        (("sheet_id", sheet.id), ("instance", placement.instance)),
                    )
                )
            if (
                placement.material_id != sheet.material_id
                or abs(placement.thickness_mm - sheet.thickness_mm)
                > PLACEMENT_EPSILON_MM
            ):
                issues.append(
                    ValidationIssue(
                        IssueSeverity.ERROR,
                        "nesting.stock_group_mismatch",
                        "Placement material or thickness does not match its sheet",
                        placement.part_id,
                        (("sheet_id", sheet.id), ("instance", placement.instance)),
                    )
                )
        for index, first in enumerate(sheet.placements):
            for second in sheet.placements[index + 1 :]:
                if _polygons_overlap(first.polygon, second.polygon):
                    issues.append(
                        ValidationIssue(
                            IssueSeverity.ERROR,
                            "nesting.overlap",
                            "Placements overlap",
                            first.part_id,
                            (
                                ("other_part_id", second.part_id),
                                ("sheet_id", sheet.id),
                            ),
                        )
                    )
                elif (
                    clearance > PLACEMENT_EPSILON_MM
                    and _polygon_boundary_distance(first.polygon, second.polygon)
                    < clearance - PLACEMENT_EPSILON_MM
                ):
                    issues.append(
                        ValidationIssue(
                            IssueSeverity.ERROR,
                            "nesting.insufficient_clearance",
                            "Placements do not satisfy kerf plus spacing clearance",
                            first.part_id,
                            (
                                ("other_part_id", second.part_id),
                                ("sheet_id", sheet.id),
                            ),
                        )
                    )
    unique = {issue.sort_key(): issue for issue in issues}
    return tuple(unique[key] for key in sorted(unique))


def _summaries(
    result: NestingResult,
    materials: dict[str, Material],
) -> tuple[MaterialSummary, ...]:
    keys = {
        (sheet.material_id, sheet.thickness_mm) for sheet in result.sheets
    } | {
        (item.material_id, item.thickness_mm)
        for item in result.unplaced_parts
        if item.material_id is not None
    }
    summaries = []
    for material_id, thickness in sorted(keys):
        sheets = [
            sheet
            for sheet in result.sheets
            if sheet.material_id == material_id
            and abs(sheet.thickness_mm - thickness) <= PLACEMENT_EPSILON_MM
        ]
        unplaced = [
            item
            for item in result.unplaced_parts
            if item.material_id == material_id
            and abs(item.thickness_mm - thickness) <= PLACEMENT_EPSILON_MM
        ]
        part_area = mm(sum(sheet.used_area_mm2 for sheet in sheets))
        stock_area = mm(sum(sheet.stock_area_mm2 for sheet in sheets))
        waste = mm(max(0.0, stock_area - part_area))
        summaries.append(
            MaterialSummary(
                material_id=material_id,
                material_name=materials.get(
                    material_id, Material(material_id, material_id, thickness)
                ).name,
                thickness_mm=thickness,
                placed_parts=sum(len(sheet.placements) for sheet in sheets),
                unplaced_parts=len(unplaced),
                sheet_count=len(sheets),
                part_area_mm2=part_area,
                stock_area_mm2=stock_area,
                waste_area_mm2=waste,
                utilization=round(part_area / stock_area, 6) if stock_area else 0.0,
            )
        )
    return tuple(sorted(summaries, key=MaterialSummary.sort_key))


def _point_dict(point: Point2D) -> list[float]:
    return [point.x, point.y]


def result_to_dict(result: NestingResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "project_id": result.project_id,
        "strategy": result.strategy.value,
        "settings": {
            "kerf_mm": result.kerf_mm,
            "margin_mm": result.margin_mm,
            "spacing_mm": result.spacing_mm,
            "clearance_mm": result.clearance_mm,
            "rotation_policy": result.rotation_policy.value,
        },
        "valid": result.is_valid,
        "sheets": [
            {
                "id": sheet.id,
                "stock_id": sheet.stock_id,
                "stock_name": sheet.stock_name,
                "material_id": sheet.material_id,
                "material_name": sheet.material_name,
                "thickness_mm": sheet.thickness_mm,
                "width_mm": sheet.width_mm,
                "height_mm": sheet.height_mm,
                "grain": sheet.grain.value,
                "is_remnant": sheet.is_remnant,
                "used_area_mm2": sheet.used_area_mm2,
                "stock_area_mm2": sheet.stock_area_mm2,
                "usable_area_mm2": sheet.usable_area_mm2,
                "waste_area_mm2": sheet.waste_area_mm2,
                "utilization": sheet.utilization,
                "placements": [
                    {
                        "part_id": placement.part_id,
                        "part_name": placement.part_name,
                        "instance": placement.instance,
                        "material_id": placement.material_id,
                        "thickness_mm": placement.thickness_mm,
                        "x_mm": placement.x_mm,
                        "y_mm": placement.y_mm,
                        "width_mm": placement.width_mm,
                        "height_mm": placement.height_mm,
                        "rotation_deg": placement.rotation_deg,
                        "area_mm2": placement.area_mm2,
                        "outline": {
                            "outer": [
                                _point_dict(point)
                                for point in placement.polygon.outer
                            ],
                            "cutouts": [
                                [_point_dict(point) for point in loop]
                                for loop in placement.polygon.cutouts
                            ],
                        },
                    }
                    for placement in sheet.placements
                ],
            }
            for sheet in result.sheets
        ],
        "unplaced_parts": [
            {
                "part_id": item.part_id,
                "part_name": item.part_name,
                "instance": item.instance,
                "material_id": item.material_id,
                "thickness_mm": item.thickness_mm,
                "reason": item.reason,
                "message": item.message,
            }
            for item in result.unplaced_parts
        ],
        "summaries": [
            {
                "material_id": summary.material_id,
                "material_name": summary.material_name,
                "thickness_mm": summary.thickness_mm,
                "placed_parts": summary.placed_parts,
                "unplaced_parts": summary.unplaced_parts,
                "sheet_count": summary.sheet_count,
                "part_area_mm2": summary.part_area_mm2,
                "stock_area_mm2": summary.stock_area_mm2,
                "waste_area_mm2": summary.waste_area_mm2,
                "utilization": summary.utilization,
            }
            for summary in result.summaries
        ],
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
                "source_id": issue.source_id,
                "details": dict(issue.details),
            }
            for issue in result.issues
        ],
    }


def dumps(result: NestingResult, *, indent: int = 2) -> str:
    return json.dumps(
        result_to_dict(result),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"


def write_json(result: NestingResult, destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(dumps(result), encoding="utf-8")
    return path


def csv_string(result: NestingResult) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "status",
            "sheet_id",
            "stock_id",
            "material_id",
            "thickness_mm",
            "part_id",
            "part_name",
            "instance",
            "x_mm",
            "y_mm",
            "width_mm",
            "height_mm",
            "rotation_deg",
            "area_mm2",
            "reason",
        )
    )
    for sheet in result.sheets:
        for placement in sheet.placements:
            writer.writerow(
                (
                    "placed",
                    sheet.id,
                    sheet.stock_id,
                    sheet.material_id,
                    sheet.thickness_mm,
                    placement.part_id,
                    placement.part_name,
                    placement.instance,
                    placement.x_mm,
                    placement.y_mm,
                    placement.width_mm,
                    placement.height_mm,
                    placement.rotation_deg,
                    placement.area_mm2,
                    "",
                )
            )
    for item in result.unplaced_parts:
        writer.writerow(
            (
                "unplaced",
                "",
                "",
                item.material_id or "",
                item.thickness_mm,
                item.part_id,
                item.part_name,
                item.instance,
                "",
                "",
                "",
                "",
                "",
                "",
                item.reason,
            )
        )
    return output.getvalue()


def write_csv(result: NestingResult, destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(csv_string(result), encoding="utf-8", newline="")
    return path


def _svg_number(value: float) -> str:
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.4f}".rstrip("0").rstrip(".")


def _svg_path(polygon: Polygon2D, sheet_height: float) -> str:
    commands = []
    for loop in _loops(polygon):
        first = loop[0]
        commands.append(
            f"M {_svg_number(first.x)} {_svg_number(sheet_height - first.y)}"
        )
        commands.extend(
            f"L {_svg_number(point.x)} {_svg_number(sheet_height - point.y)}"
            for point in loop[1:]
        )
        commands.append("Z")
    return " ".join(commands)


def svg_string(sheet: NestingSheet, result: NestingResult) -> str:
    width = _svg_number(sheet.width_mm)
    height = _svg_number(sheet.height_mm)
    margin = _svg_number(result.margin_mm)
    usable_width = _svg_number(max(0.0, sheet.width_mm - (2 * result.margin_mm)))
    usable_height = _svg_number(max(0.0, sheet.height_mm - (2 * result.margin_mm)))
    title = escape(
        f"{sheet.id} - {sheet.material_name} {sheet.thickness_mm:g} mm - "
        f"{sheet.utilization:.1%} utilized"
    )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            'role="img">'
        ),
        f"  <title>{title}</title>",
        "  <style>",
        "    .sheet { fill: #f7f2e7; stroke: #222; stroke-width: 2; }",
        "    .usable { fill: none; stroke: #777; stroke-width: 1; stroke-dasharray: 8 5; }",
        "    .part { fill: #9ecae1; fill-rule: evenodd; stroke: #08519c; stroke-width: 1.5; }",
        "    .label { font: 18px sans-serif; fill: #111; text-anchor: middle; dominant-baseline: middle; }",
        "    .grain { stroke: #a50f15; stroke-width: 2; }",
        "  </style>",
        f'  <rect class="sheet" x="0" y="0" width="{width}" height="{height}"/>',
        (
            f'  <rect class="usable" x="{margin}" y="{margin}" '
            f'width="{usable_width}" height="{usable_height}"/>'
        ),
    ]
    for placement in sheet.placements:
        path = escape(_svg_path(placement.polygon, sheet.height_mm), quote=True)
        label_x = placement.x_mm + (placement.width_mm / 2)
        label_y = sheet.height_mm - placement.y_mm - (placement.height_mm / 2)
        label = escape(f"{placement.part_name} #{placement.instance}")
        lines.append(
            f'  <path class="part" d="{path}" data-part-id="{escape(placement.part_id, quote=True)}"/>'
        )
        lines.append(
            f'  <text class="label" x="{_svg_number(label_x)}" y="{_svg_number(label_y)}">{label}</text>'
        )
    if sheet.grain != GrainDirection.NONE:
        center_y = sheet.height_mm / 2
        if sheet.grain == GrainDirection.LENGTH:
            lines.append(
                f'  <line class="grain" x1="{margin}" y1="{_svg_number(center_y)}" '
                f'x2="{_svg_number(sheet.width_mm - result.margin_mm)}" y2="{_svg_number(center_y)}"/>'
            )
        else:
            center_x = sheet.width_mm / 2
            lines.append(
                f'  <line class="grain" x1="{_svg_number(center_x)}" y1="{margin}" '
                f'x2="{_svg_number(center_x)}" y2="{_svg_number(sheet.height_mm - result.margin_mm)}"/>'
            )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def write_svg_diagrams(
    result: NestingResult,
    destination: str | Path,
) -> tuple[Path, ...]:
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob("sheet-*.svg"):
        path.unlink()
    paths = []
    for sheet in result.sheets:
        path = directory / f"{sheet.id}.svg"
        path.write_text(svg_string(sheet, result), encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def export_result(result: NestingResult, destination: str | Path) -> tuple[Path, ...]:
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    paths = [
        write_json(result, directory / "nesting.json"),
        write_csv(result, directory / "nesting.csv"),
    ]
    paths.extend(write_svg_diagrams(result, directory))
    return tuple(paths)


__all__ = [
    "MaterialSummary",
    "NestingConfig",
    "NestingOptimizer",
    "NestingPlacement",
    "NestingResult",
    "NestingSheet",
    "NestingStrategy",
    "RotationPolicy",
    "StockSpec",
    "UnplacedPart",
    "csv_string",
    "dumps",
    "export_result",
    "optimize",
    "result_to_dict",
    "svg_string",
    "validate_result",
    "write_csv",
    "write_json",
    "write_svg_diagrams",
]
