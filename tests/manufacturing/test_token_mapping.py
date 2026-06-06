import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from manufacturing.extractor import _convert_token, _part_quantity
from manufacturing.geometry import AxisNormalization, rectangle_outline
from manufacturing.model import (
    Cabinet,
    Face,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
)
from manufacturing.mozaik import export_package


class TokenMappingTests(unittest.TestCase):
    def test_generic_array_does_not_duplicate_axis_prompt_quantity(self):
        modifier = SimpleNamespace(
            type="ARRAY",
            show_viewport=True,
            name="Array",
            count=4,
        )
        mesh = SimpleNamespace(modifiers=(modifier,))

        with patch(
            "manufacturing.extractor._prompt_value",
            side_effect=lambda _bp, name: 4 if name == "Z Quantity" else None,
        ):
            self.assertEqual(_part_quantity(object(), (mesh,)), 4)

    def test_line_bore_coordinates_and_face_follow_signed_axes(self):
        normalization = AxisNormalization.from_signed_dimensions(-500, 300, -18)
        operations, issues = _convert_token(
            "Line_Bore",
            {
                "Face Name": 1,
                "X": 0.05,
                "Y": 0.02,
                "Z": 0.012,
                "Diameter": 0.005,
                "End X": 0.45,
                "End Y": 0.02,
                "Distance Between Holes": 0.032,
            },
            normalization,
            "operation-a",
            "part-a",
        )

        self.assertFalse(issues)
        self.assertEqual(len(operations), 1)
        operation = operations[0]
        self.assertEqual(operation.operation_type, MachiningType.LINE_BORE)
        self.assertEqual(operation.face, Face.BOTTOM)
        self.assertEqual((operation.x_mm, operation.end_x_mm), (450, 50))
        self.assertEqual(operation.depth_mm, 12)
        self.assertEqual(operation.diameter_mm, 5)

    def test_unsupported_token_is_a_structured_warning(self):
        operations, issues = _convert_token(
            "Cam_Lock",
            {},
            AxisNormalization.from_signed_dimensions(500, 300, 18),
            "operation-a",
            "part-a",
        )

        self.assertEqual(operations, ())
        self.assertEqual(issues[0].code, "extractor.unsupported_machine_token")

    def test_dado_is_inset_from_each_selected_edge(self):
        normalization = AxisNormalization.from_signed_dimensions(500, 300, 18)
        expected = {
            1: (15, 20, 15, 280),
            2: (485, 20, 485, 280),
            3: (20, 285, 480, 285),
            4: (20, 15, 480, 15),
        }
        for edge, coordinates in expected.items():
            with self.subTest(edge=edge):
                operations, issues = _convert_token(
                    "Dado",
                    {
                        "Edge Name": edge,
                        "Lead In": 0.02,
                        "Lead Out": 0.02,
                        "Beginning Depth": 0.01,
                        "Dado Thickness": 0.01,
                        "Panel Penetration": 0.006,
                    },
                    normalization,
                    f"operation-{edge}",
                    "part-a",
                )

                self.assertFalse(issues)
                operation = operations[0]
                self.assertEqual(operation.operation_type, MachiningType.GROOVE)
                self.assertEqual(
                    (
                        operation.x_mm,
                        operation.y_mm,
                        operation.end_x_mm,
                        operation.end_y_mm,
                    ),
                    coordinates,
                )
                self.assertEqual(operation.width_mm, 10)
                self.assertEqual(dict(operation.parameters)["beginning_depth_mm"], 10)

    def test_machine_token_coordinates_follow_panel_axis_scale(self):
        normalization = AxisNormalization.from_signed_dimensions(1000, 150, 36)
        operations, issues = _convert_token(
            "Line_Bore",
            {
                "Face Name": 1,
                "X": 0.05,
                "Y": 0.02,
                "Z": 0.012,
                "Diameter": 0.005,
                "End X": 0.45,
                "End Y": 0.02,
                "Distance Between Holes": 0.032,
            },
            normalization,
            "operation-a",
            "part-a",
            (2.0, 0.5, 2.0),
        )

        self.assertFalse(issues)
        operation = operations[0]
        self.assertEqual(
            (
                operation.x_mm,
                operation.y_mm,
                operation.end_x_mm,
                operation.end_y_mm,
            ),
            (100, 10, 900, 10),
        )
        self.assertEqual(operation.depth_mm, 24)
        self.assertEqual(operation.spacing_mm, 64)

    def test_positive_width_dado_exports_as_a_groove(self):
        normalization = AxisNormalization.from_signed_dimensions(500, 300, 18)
        operations, issues = _convert_token(
            "Dado",
            {
                "Edge Name": 4,
                "Lead In": 0.02,
                "Lead Out": 0.02,
                "Beginning Depth": 0.01,
                "Dado Thickness": 0.01,
                "Panel Penetration": 0.006,
            },
            normalization,
            "dado-a",
            "part-a",
        )
        part = Part(
            id="part-a",
            source_id="source-part-a",
            cabinet_id="cabinet-a",
            name="Dado panel",
            category=PartCategory.SHELF,
            quantity=1,
            material_id="material-a",
            length_mm=500,
            width_mm=300,
            thickness_mm=18,
            outline=rectangle_outline(500, 300),
            machining=operations,
        )
        project = ManufacturingProject(
            project_id="project-a",
            name="Dado export",
            cabinets=(
                Cabinet(
                    "cabinet-a",
                    "Cabinet",
                    "source-cabinet-a",
                    ("part-a",),
                ),
            ),
            parts=(part,),
            materials=(Material("material-a", "White Melamine", 18),),
        )

        with tempfile.TemporaryDirectory() as temporary:
            result = export_package(project, Path(temporary))
            dxf = next((Path(temporary) / "panels").glob("*.dxf")).read_text(
                encoding="ascii"
            )

        self.assertFalse(issues)
        self.assertTrue(result.ok)
        self.assertIn("2\nHB4_GROOVE\n", dxf)
        self.assertNotIn(
            "mozaik.unsafe_groove_geometry",
            {issue.code for issue in result.issues},
        )


if __name__ == "__main__":
    unittest.main()
