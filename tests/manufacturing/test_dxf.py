from __future__ import annotations

import unittest

from manufacturing.dxf import (
    UnsupportedPanelGeometry,
    groove_polygon,
    render_part_dxf,
)
from manufacturing.geometry import Point2D, Polygon2D
from manufacturing.model import (
    Face,
    IssueSeverity,
    MachiningType,
    ValidationIssue,
)

from .drawing_fixtures import make_part, operation


def _tags(dxf: str) -> list[tuple[str, str]]:
    lines = dxf.splitlines()
    return list(zip(lines[::2], lines[1::2]))


def _entity_tags(dxf: str, entity_type: str) -> list[list[tuple[str, str]]]:
    tags = _tags(dxf)
    entities: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] | None = None
    for tag in tags:
        if tag[0] == "0":
            if current is not None:
                entities.append(current)
                current = None
            if tag[1] == entity_type:
                current = [tag]
        elif current is not None:
            current.append(tag)
    if current is not None:
        entities.append(current)
    return entities


class DxfTests(unittest.TestCase):
    def test_sections_units_layers_and_closed_contours(self):
        part = make_part(
            "part-dxf-operations",
            "DXF Operations",
            outline=Polygon2D(
                (
                    Point2D(0, 0),
                    Point2D(500, 0),
                    Point2D(500, 300),
                    Point2D(0, 300),
                ),
                (
                    (
                        Point2D(420, 220),
                        Point2D(460, 220),
                        Point2D(460, 260),
                        Point2D(420, 260),
                    ),
                ),
            ),
            machining=(
                operation(
                    "through",
                    MachiningType.THROUGH_HOLE,
                    x_mm=40,
                    y_mm=40,
                    diameter_mm=5,
                ),
                operation(
                    "blind",
                    MachiningType.BLIND_HOLE,
                    face=Face.BOTTOM,
                    x_mm=80,
                    y_mm=40,
                    diameter_mm=8,
                    depth_mm=12,
                ),
                operation(
                    "line",
                    MachiningType.LINE_BORE,
                    x_mm=120,
                    y_mm=50,
                    end_x_mm=120,
                    end_y_mm=114,
                    diameter_mm=5,
                    depth_mm=12,
                    spacing_mm=32,
                ),
                operation(
                    "groove",
                    MachiningType.GROOVE,
                    x_mm=160,
                    y_mm=50,
                    end_x_mm=360,
                    end_y_mm=50,
                    width_mm=8,
                    depth_mm=6,
                ),
                operation(
                    "pocket",
                    MachiningType.POCKET,
                    x_mm=180,
                    y_mm=100,
                    depth_mm=5,
                    path=((180, 100), (300, 100), (300, 160), (180, 160)),
                ),
                operation(
                    "contour",
                    MachiningType.CONTOUR_CUTOUT,
                    x_mm=340,
                    y_mm=100,
                    depth_mm=18,
                    path=((340, 100), (390, 100), (390, 160), (340, 160)),
                ),
            ),
        )

        dxf = render_part_dxf(part)
        tags = _tags(dxf)
        sections = {
            tags[index + 1][1]
            for index, tag in enumerate(tags[:-1])
            if tag == ("0", "SECTION") and tags[index + 1][0] == "2"
        }
        layers = {
            tags[index + 1][1]
            for index, tag in enumerate(tags[:-1])
            if tag == ("0", "LAYER") and tags[index + 1][0] == "2"
        }

        self.assertEqual(sections, {"HEADER", "TABLES", "ENTITIES"})
        insunits_index = tags.index(("9", "$INSUNITS"))
        self.assertEqual(tags[insunits_index + 1], ("70", "4"))
        self.assertEqual(
            layers,
            {
                "OUTLINE",
                "CUTOUT",
                "THROUGH_HOLE_TOP",
                "BLIND_HOLE_BOTTOM",
                "LINE_BORE_TOP",
                "GROOVE_TOP",
                "POCKET_TOP",
                "CONTOUR_CUTOUT_TOP",
            },
        )
        polylines = _entity_tags(dxf, "LWPOLYLINE")
        self.assertGreaterEqual(len(polylines), 5)
        self.assertTrue(all(("70", "1") in entity for entity in polylines))
        self.assertEqual(len(_entity_tags(dxf, "CIRCLE")), 5)
        self.assertEqual(dxf.encode("ascii").decode("ascii"), dxf)
        self.assertTrue(dxf.endswith("0\nEOF\n"))

    def test_finished_dimensions_and_output_are_deterministic(self):
        operations = (
            operation(
                "b",
                MachiningType.THROUGH_HOLE,
                x_mm=200,
                y_mm=100,
                diameter_mm=5,
            ),
            operation(
                "a",
                MachiningType.THROUGH_HOLE,
                x_mm=100,
                y_mm=100,
                diameter_mm=5,
            ),
        )
        forward = make_part("part-deterministic", "Panel", machining=operations)
        reverse = make_part(
            "part-deterministic",
            "Panel",
            machining=tuple(reversed(operations)),
        )

        first = render_part_dxf(forward)
        self.assertEqual(first, render_part_dxf(reverse))
        tags = _tags(first)
        extmax_index = tags.index(("9", "$EXTMAX"))
        self.assertIn(("10", "500"), tags[extmax_index : extmax_index + 5])
        self.assertIn(("20", "300"), tags[extmax_index : extmax_index + 5])

    def test_edge_groove_footprint_stays_inside_panel(self):
        edge_groove = operation(
            "edge-dado",
            MachiningType.GROOVE,
            x_mm=20,
            y_mm=0,
            end_x_mm=480,
            end_y_mm=0,
            width_mm=8,
            depth_mm=6,
            parameters=(("edge", Face.BACK.value),),
        )
        polygon = groove_polygon(edge_groove)

        self.assertEqual(
            polygon,
            (
                Point2D(20, 0),
                Point2D(480, 0),
                Point2D(480, 8),
                Point2D(20, 8),
            ),
        )
        self.assertIn("GROOVE_TOP", render_part_dxf(
            make_part("part-edge-dado", "Edge Dado", machining=(edge_groove,))
        ))

    def test_unsupported_or_incomplete_geometry_is_rejected(self):
        fallback = make_part(
            "part-fallback",
            "Fallback",
            issues=(
                ValidationIssue(
                    IssueSeverity.WARNING,
                    "extractor.rectangular_outline_fallback",
                    "No evaluated boundary",
                ),
            ),
        )
        incomplete = make_part(
            "part-incomplete",
            "Incomplete",
            machining=(
                operation(
                    "pocket",
                    MachiningType.POCKET,
                    depth_mm=5,
                ),
            ),
        )
        unsupported_token = make_part(
            "part-unsupported-token",
            "Unsupported Token",
            issues=(
                ValidationIssue(
                    IssueSeverity.WARNING,
                    "extractor.unsupported_machine_token",
                    "Machine token is not supported",
                ),
            ),
        )

        for part in (fallback, incomplete, unsupported_token):
            with self.subTest(part=part.id):
                with self.assertRaises(UnsupportedPanelGeometry):
                    render_part_dxf(part)

    def test_operations_in_removed_panel_material_are_rejected(self):
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
        cutout_outline = Polygon2D(
            (
                Point2D(0, 0),
                Point2D(500, 0),
                Point2D(500, 300),
                Point2D(0, 300),
            ),
            (
                (
                    Point2D(200, 100),
                    Point2D(300, 100),
                    Point2D(300, 200),
                    Point2D(200, 200),
                ),
            ),
        )
        cases = (
            make_part(
                "hole-in-notch",
                "Hole In Notch",
                outline=notched_outline,
                machining=(
                    operation(
                        "hole",
                        MachiningType.THROUGH_HOLE,
                        x_mm=460,
                        y_mm=250,
                        diameter_mm=5,
                    ),
                ),
            ),
            make_part(
                "hole-in-cutout",
                "Hole In Cutout",
                outline=cutout_outline,
                machining=(
                    operation(
                        "hole",
                        MachiningType.THROUGH_HOLE,
                        x_mm=250,
                        y_mm=150,
                        diameter_mm=5,
                    ),
                ),
            ),
            make_part(
                "groove-crosses-cutout",
                "Groove Crosses Cutout",
                outline=cutout_outline,
                machining=(
                    operation(
                        "groove",
                        MachiningType.GROOVE,
                        x_mm=100,
                        y_mm=150,
                        end_x_mm=400,
                        end_y_mm=150,
                        width_mm=8,
                        depth_mm=6,
                    ),
                ),
            ),
            make_part(
                "pocket-encloses-cutout",
                "Pocket Encloses Cutout",
                outline=cutout_outline,
                machining=(
                    operation(
                        "pocket",
                        MachiningType.POCKET,
                        depth_mm=6,
                        path=(
                            (150, 50),
                            (350, 50),
                            (350, 250),
                            (150, 250),
                        ),
                    ),
                ),
            ),
            make_part(
                "contour-crosses-notch",
                "Contour Crosses Notch",
                outline=notched_outline,
                machining=(
                    operation(
                        "contour",
                        MachiningType.CONTOUR_CUTOUT,
                        depth_mm=18,
                        path=(
                            (350, 180),
                            (470, 180),
                            (470, 240),
                            (350, 240),
                        ),
                    ),
                ),
            ),
        )

        for part in cases:
            with self.subTest(part=part.id):
                with self.assertRaises(UnsupportedPanelGeometry):
                    render_part_dxf(part)

    def test_hole_radius_must_clear_cutout_boundary(self):
        part = make_part(
            "hole-overlaps-cutout",
            "Hole Overlaps Cutout",
            outline=Polygon2D(
                (
                    Point2D(0, 0),
                    Point2D(500, 0),
                    Point2D(500, 300),
                    Point2D(0, 300),
                ),
                (
                    (
                        Point2D(200, 100),
                        Point2D(300, 100),
                        Point2D(300, 200),
                        Point2D(200, 200),
                    ),
                ),
            ),
            machining=(
                operation(
                    "hole",
                    MachiningType.THROUGH_HOLE,
                    x_mm=190,
                    y_mm=150,
                    diameter_mm=25,
                ),
            ),
        )

        with self.assertRaises(UnsupportedPanelGeometry):
            render_part_dxf(part)

    def test_operation_inside_shaped_panel_material_is_supported(self):
        part = make_part(
            "valid-shaped-hole",
            "Valid Shaped Hole",
            outline=Polygon2D(
                (
                    Point2D(0, 0),
                    Point2D(500, 0),
                    Point2D(500, 200),
                    Point2D(420, 200),
                    Point2D(420, 300),
                    Point2D(0, 300),
                )
            ),
            machining=(
                operation(
                    "hole",
                    MachiningType.THROUGH_HOLE,
                    x_mm=100,
                    y_mm=250,
                    diameter_mm=5,
                ),
            ),
        )

        self.assertIn("THROUGH_HOLE_TOP", render_part_dxf(part))


if __name__ == "__main__":
    unittest.main()
