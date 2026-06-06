"""Pure-Python panel geometry and signed-axis normalization."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


GEOMETRY_PRECISION = 4
EPSILON_MM = 1e-5


def _number(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("geometry coordinates must be finite")
    rounded = round(value, GEOMETRY_PRECISION)
    return 0.0 if rounded == -0.0 else rounded


@dataclass(frozen=True, order=True)
class Point2D:
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _number(self.x))
        object.__setattr__(self, "y", _number(self.y))


def signed_area(points: Sequence[Point2D]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        point.x * points[(index + 1) % len(points)].y
        - points[(index + 1) % len(points)].x * point.y
        for index, point in enumerate(points)
    )


def is_clockwise(points: Sequence[Point2D]) -> bool:
    return signed_area(points) < 0


def point_in_loop(point: Point2D, loop: Sequence[Point2D]) -> bool:
    """Return whether a point lies inside or on a closed loop."""
    inside = False
    previous = loop[-1]
    for current in loop:
        cross = (
            (point.y - previous.y) * (current.x - previous.x)
            - (point.x - previous.x) * (current.y - previous.y)
        )
        if abs(cross) <= EPSILON_MM and (
            min(previous.x, current.x) - EPSILON_MM
            <= point.x
            <= max(previous.x, current.x) + EPSILON_MM
            and min(previous.y, current.y) - EPSILON_MM
            <= point.y
            <= max(previous.y, current.y) + EPSILON_MM
        ):
            return True
        if (current.y > point.y) != (previous.y > point.y):
            intersect_x = (
                (previous.x - current.x)
                * (point.y - current.y)
                / (previous.y - current.y)
                + current.x
            )
            if point.x < intersect_x:
                inside = not inside
        previous = current
    return inside


def _point_on_segment(
    point: Point2D,
    start: Point2D,
    end: Point2D,
) -> bool:
    cross = (
        (point.y - start.y) * (end.x - start.x)
        - (point.x - start.x) * (end.y - start.y)
    )
    return abs(cross) <= EPSILON_MM and (
        min(start.x, end.x) - EPSILON_MM
        <= point.x
        <= max(start.x, end.x) + EPSILON_MM
        and min(start.y, end.y) - EPSILON_MM
        <= point.y
        <= max(start.y, end.y) + EPSILON_MM
    )


def _point_on_loop(point: Point2D, loop: Sequence[Point2D]) -> bool:
    return any(
        _point_on_segment(point, loop[index - 1], current)
        for index, current in enumerate(loop)
    )


def _orientation(start: Point2D, end: Point2D, point: Point2D) -> float:
    return (
        (end.x - start.x) * (point.y - start.y)
        - (end.y - start.y) * (point.x - start.x)
    )


def _opposite_sides(first: float, second: float) -> bool:
    return (
        first > EPSILON_MM and second < -EPSILON_MM
    ) or (
        first < -EPSILON_MM and second > EPSILON_MM
    )


def _segments_intersect(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
) -> bool:
    first_a = _orientation(first_start, first_end, second_start)
    first_b = _orientation(first_start, first_end, second_end)
    second_a = _orientation(second_start, second_end, first_start)
    second_b = _orientation(second_start, second_end, first_end)

    if _opposite_sides(first_a, first_b) and _opposite_sides(second_a, second_b):
        return True
    return (
        (
            abs(first_a) <= EPSILON_MM
            and _point_on_segment(second_start, first_start, first_end)
        )
        or (
            abs(first_b) <= EPSILON_MM
            and _point_on_segment(second_end, first_start, first_end)
        )
        or (
            abs(second_a) <= EPSILON_MM
            and _point_on_segment(first_start, second_start, second_end)
        )
        or (
            abs(second_b) <= EPSILON_MM
            and _point_on_segment(first_end, second_start, second_end)
        )
    )


def _loop_strictly_inside(
    inner: Sequence[Point2D],
    outer: Sequence[Point2D],
) -> bool:
    if any(
        not point_in_loop(point, outer) or _point_on_loop(point, outer)
        for point in inner
    ):
        return False
    return not any(
        _segments_intersect(
            inner[inner_index - 1],
            inner_point,
            outer[outer_index - 1],
            outer_point,
        )
        for inner_index, inner_point in enumerate(inner)
        for outer_index, outer_point in enumerate(outer)
    )


def _collinear(previous: Point2D, current: Point2D, following: Point2D) -> bool:
    cross = (
        (current.x - previous.x) * (following.y - current.y)
        - (current.y - previous.y) * (following.x - current.x)
    )
    return abs(cross) <= EPSILON_MM


def normalize_loop(
    points: Iterable[Point2D | Sequence[float]],
    *,
    clockwise: bool = False,
) -> tuple[Point2D, ...]:
    normalized: list[Point2D] = []
    for point in points:
        item = point if isinstance(point, Point2D) else Point2D(point[0], point[1])
        if not normalized or item != normalized[-1]:
            normalized.append(item)
    if len(normalized) > 1 and normalized[0] == normalized[-1]:
        normalized.pop()

    changed = True
    while changed and len(normalized) > 3:
        changed = False
        simplified: list[Point2D] = []
        for index, point in enumerate(normalized):
            if _collinear(normalized[index - 1], point, normalized[(index + 1) % len(normalized)]):
                changed = True
                continue
            simplified.append(point)
        normalized = simplified

    if len(normalized) < 3 or abs(signed_area(normalized)) <= EPSILON_MM:
        raise ValueError("a closed outline requires at least three non-collinear points")

    is_clockwise = signed_area(normalized) < 0
    if is_clockwise != clockwise:
        normalized.reverse()

    start = min(range(len(normalized)), key=lambda index: normalized[index])
    return tuple(normalized[start:] + normalized[:start])


@dataclass(frozen=True)
class Polygon2D:
    outer: tuple[Point2D, ...]
    cutouts: tuple[tuple[Point2D, ...], ...] = ()

    def __post_init__(self) -> None:
        outer = normalize_loop(self.outer, clockwise=False)
        cutouts = tuple(
            sorted(
                (normalize_loop(loop, clockwise=True) for loop in self.cutouts),
                key=lambda loop: (bounds(loop), loop),
            )
        )
        for loop in cutouts:
            if not _loop_strictly_inside(loop, outer):
                raise ValueError("cut-out loops must lie inside the outer outline")
        object.__setattr__(self, "outer", outer)
        object.__setattr__(self, "cutouts", cutouts)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return bounds(self.outer)

    @property
    def width(self) -> float:
        minimum_x, _, maximum_x, _ = self.bounds
        return _number(maximum_x - minimum_x)

    @property
    def height(self) -> float:
        _, minimum_y, _, maximum_y = self.bounds
        return _number(maximum_y - minimum_y)

    @property
    def area(self) -> float:
        return _number(
            abs(signed_area(self.outer))
            - sum(abs(signed_area(loop)) for loop in self.cutouts)
        )


def bounds(points: Sequence[Point2D]) -> tuple[float, float, float, float]:
    if not points:
        raise ValueError("bounds require at least one point")
    return (
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def rectangle_outline(length_mm: float, width_mm: float) -> Polygon2D:
    length = abs(_number(length_mm))
    width = abs(_number(width_mm))
    if length <= 0 or width <= 0:
        raise ValueError("rectangle dimensions must be positive")
    return Polygon2D(
        (
            Point2D(0, 0),
            Point2D(length, 0),
            Point2D(length, width),
            Point2D(0, width),
        )
    )


def normalize_polygon_origin(polygon: Polygon2D) -> Polygon2D:
    """Translate a polygon so its outer bounds start at the lower-left origin."""
    minimum_x, minimum_y, _, _ = polygon.bounds
    return translate_polygon(polygon, -minimum_x, -minimum_y)


def polygon_from_loops(
    loops: Iterable[Iterable[Point2D | Sequence[float]]],
) -> Polygon2D:
    """Build a polygon from unordered closed loops.

    The largest loop is treated as the outer boundary. Remaining loops become
    cut-outs. Disconnected outer bodies are intentionally rejected because one
    manufacturing part must have exactly one outer contour.
    """
    normalized = [normalize_loop(loop) for loop in loops]
    if not normalized:
        raise ValueError("at least one closed loop is required")
    normalized.sort(key=lambda loop: (-abs(signed_area(loop)), bounds(loop), loop))
    for loop in normalized[1:]:
        if not point_in_loop(loop[0], normalized[0]):
            raise ValueError("a manufacturing part cannot contain disconnected outer loops")
    polygon = Polygon2D(normalized[0], tuple(normalized[1:]))
    return normalize_polygon_origin(polygon)


@dataclass(frozen=True)
class AxisNormalization:
    """Map signed PyClone panel axes into positive lower-left panel space."""

    length_mm: float
    width_mm: float
    thickness_mm: float
    x_sign: int
    y_sign: int
    z_sign: int

    @classmethod
    def from_signed_dimensions(
        cls,
        x_mm: float,
        y_mm: float,
        z_mm: float,
    ) -> "AxisNormalization":
        length = abs(_number(x_mm))
        width = abs(_number(y_mm))
        thickness = abs(_number(z_mm))
        return cls(
            length,
            width,
            thickness,
            -1 if x_mm < 0 else 1,
            -1 if y_mm < 0 else 1,
            -1 if z_mm < 0 else 1,
        )

    def point(self, x_mm: float, y_mm: float) -> Point2D:
        """Map nominal positive panel coordinates into normalized panel space."""
        x = self.length_mm - x_mm if self.x_sign < 0 else x_mm
        y = self.width_mm - y_mm if self.y_sign < 0 else y_mm
        return Point2D(x, y)

    def signed_point(self, x_mm: float, y_mm: float) -> Point2D:
        """Map coordinates expressed on signed assembly axes into panel space."""
        return Point2D(x_mm * self.x_sign, y_mm * self.y_sign)

    def face(self, face: str) -> str:
        swaps = {
            "left": "right" if self.x_sign < 0 else "left",
            "right": "left" if self.x_sign < 0 else "right",
            "front": "back" if self.y_sign < 0 else "front",
            "back": "front" if self.y_sign < 0 else "back",
            "top": "bottom" if self.z_sign < 0 else "top",
            "bottom": "top" if self.z_sign < 0 else "bottom",
        }
        return swaps.get(face, face)

    def edge(self, edge: str) -> str:
        return self.face(edge)


def translate_polygon(polygon: Polygon2D, x_offset: float, y_offset: float) -> Polygon2D:
    def translate(loop: Sequence[Point2D]) -> tuple[Point2D, ...]:
        return tuple(Point2D(point.x + x_offset, point.y + y_offset) for point in loop)

    return Polygon2D(translate(polygon.outer), tuple(translate(loop) for loop in polygon.cutouts))


def transform_polygon(
    polygon: Polygon2D,
    normalization: AxisNormalization,
    *,
    signed_coordinates: bool = False,
) -> Polygon2D:
    mapper = normalization.signed_point if signed_coordinates else normalization.point

    def transform(loop: Sequence[Point2D]) -> tuple[Point2D, ...]:
        return tuple(mapper(point.x, point.y) for point in loop)

    return normalize_polygon_origin(
        Polygon2D(
            transform(polygon.outer),
            tuple(transform(loop) for loop in polygon.cutouts),
        )
    )
