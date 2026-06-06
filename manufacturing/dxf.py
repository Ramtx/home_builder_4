"""Small deterministic ASCII DXF writer for manufacturing panel geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Sequence


DXF_VERSION = "AC1015"
DXF_MILLIMETRES = 4


def format_number(value: float) -> str:
    """Format a finite DXF number with a locale-independent decimal point."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("DXF coordinates must be finite")
    rounded = round(value, 4)
    if rounded == -0.0:
        rounded = 0.0
    text = f"{rounded:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _pair(code: int, value: object) -> tuple[str, str]:
    return (str(code), str(value))


@dataclass(frozen=True)
class DxfLayer:
    name: str
    color: int = 7

    def __post_init__(self) -> None:
        if (
            not self.name
            or "\n" in self.name
            or "\r" in self.name
            or not self.name.isascii()
        ):
            raise ValueError(
                "DXF layer names must be non-empty single-line ASCII strings"
            )
        if not 1 <= int(self.color) <= 255:
            raise ValueError("DXF layer color must be between 1 and 255")


class DxfDocument:
    """Build the limited DXF entity set needed by panel exports."""

    def __init__(self, layers: Iterable[DxfLayer]):
        self.layers = tuple(layers)
        if not self.layers:
            raise ValueError("at least one DXF layer is required")
        names = [layer.name.casefold() for layer in self.layers]
        if len(names) != len(set(names)):
            raise ValueError("DXF layer names must be unique")
        self._layer_names = {layer.name for layer in self.layers}
        self._entities: list[tuple[str, ...]] = []

    def _require_layer(self, layer: str) -> None:
        if layer not in self._layer_names:
            raise ValueError(f"undefined DXF layer: {layer}")

    def add_lwpolyline(
        self,
        layer: str,
        points: Sequence[Sequence[float]],
        *,
        closed: bool = True,
    ) -> None:
        self._require_layer(layer)
        if len(points) < (3 if closed else 2):
            raise ValueError("DXF polylines require enough points for their topology")
        pairs = [
            _pair(0, "LWPOLYLINE"),
            _pair(100, "AcDbEntity"),
            _pair(8, layer),
            _pair(100, "AcDbPolyline"),
            _pair(90, len(points)),
            _pair(70, 1 if closed else 0),
        ]
        for point in points:
            pairs.extend(
                (
                    _pair(10, format_number(point[0])),
                    _pair(20, format_number(point[1])),
                )
            )
        self._entities.append(tuple(item for pair in pairs for item in pair))

    def add_circle(
        self,
        layer: str,
        center: Sequence[float],
        radius: float,
    ) -> None:
        self._require_layer(layer)
        if radius <= 0:
            raise ValueError("DXF circle radius must be positive")
        pairs = (
            _pair(0, "CIRCLE"),
            _pair(100, "AcDbEntity"),
            _pair(8, layer),
            _pair(100, "AcDbCircle"),
            _pair(10, format_number(center[0])),
            _pair(20, format_number(center[1])),
            _pair(30, "0"),
            _pair(40, format_number(radius)),
        )
        self._entities.append(tuple(item for pair in pairs for item in pair))

    def add_text(
        self,
        layer: str,
        text: str,
        insert: Sequence[float],
        height: float,
    ) -> None:
        self._require_layer(layer)
        if height <= 0:
            raise ValueError("DXF text height must be positive")
        safe_text = (
            text.replace("\r", " ")
            .replace("\n", " ")
            .encode("ascii", errors="replace")
            .decode("ascii")
        )
        pairs = (
            _pair(0, "TEXT"),
            _pair(100, "AcDbEntity"),
            _pair(8, layer),
            _pair(100, "AcDbText"),
            _pair(10, format_number(insert[0])),
            _pair(20, format_number(insert[1])),
            _pair(30, "0"),
            _pair(40, format_number(height)),
            _pair(1, safe_text),
        )
        self._entities.append(tuple(item for pair in pairs for item in pair))

    def render(self) -> str:
        pairs: list[tuple[str, str]] = [
            _pair(0, "SECTION"),
            _pair(2, "HEADER"),
            _pair(9, "$ACADVER"),
            _pair(1, DXF_VERSION),
            _pair(9, "$INSUNITS"),
            _pair(70, DXF_MILLIMETRES),
            _pair(9, "$MEASUREMENT"),
            _pair(70, 1),
            _pair(0, "ENDSEC"),
            _pair(0, "SECTION"),
            _pair(2, "TABLES"),
            _pair(0, "TABLE"),
            _pair(2, "LTYPE"),
            _pair(70, 1),
            _pair(0, "LTYPE"),
            _pair(100, "AcDbSymbolTableRecord"),
            _pair(100, "AcDbLinetypeTableRecord"),
            _pair(2, "CONTINUOUS"),
            _pair(70, 0),
            _pair(3, "Solid line"),
            _pair(72, 65),
            _pair(73, 0),
            _pair(40, 0.0),
            _pair(0, "ENDTAB"),
            _pair(0, "TABLE"),
            _pair(2, "LAYER"),
            _pair(70, len(self.layers)),
        ]
        for layer in self.layers:
            pairs.extend(
                (
                    _pair(0, "LAYER"),
                    _pair(100, "AcDbSymbolTableRecord"),
                    _pair(100, "AcDbLayerTableRecord"),
                    _pair(2, layer.name),
                    _pair(70, 0),
                    _pair(62, layer.color),
                    _pair(6, "CONTINUOUS"),
                )
            )
        pairs.extend(
            (
                _pair(0, "ENDTAB"),
                _pair(0, "ENDSEC"),
                _pair(0, "SECTION"),
                _pair(2, "BLOCKS"),
                _pair(0, "ENDSEC"),
                _pair(0, "SECTION"),
                _pair(2, "ENTITIES"),
            )
        )
        lines = [item for pair in pairs for item in pair]
        for entity in self._entities:
            lines.extend(entity)
        lines.extend(("0", "ENDSEC", "0", "EOF"))
        return "\n".join(lines) + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.render(), encoding="ascii", newline="\n")
