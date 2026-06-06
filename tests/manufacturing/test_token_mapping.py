import unittest
from types import SimpleNamespace
from unittest.mock import patch

from manufacturing.extractor import (
    _convert_token,
    _part_quantity,
    _single_part_modifiers,
)
from manufacturing.geometry import AxisNormalization
from manufacturing.model import Face, MachiningType


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

    def test_corner_notch_is_rejected_instead_of_emitting_an_empty_path(self):
        operations, issues = _convert_token(
            "Corner_Notch",
            {
                "Face Name": 0,
                "Corner Name": 1,
                "X": 0.05,
                "Y": 0.04,
                "Route Depth": 0.018,
            },
            AxisNormalization.from_signed_dimensions(500, 300, 18),
            "operation-corner",
            "part-corner",
        )

        self.assertEqual(operations, ())
        self.assertEqual(issues[0].code, "extractor.unsupported_machine_token")

    def test_outline_context_disables_and_restores_machining_modifiers(self):
        modifiers = (
            SimpleNamespace(
                type="ARRAY",
                node_group=None,
                show_viewport=True,
                show_render=False,
            ),
            SimpleNamespace(
                type="NODES",
                node_group=SimpleNamespace(name="PCMT_Blind_Hole"),
                show_viewport=True,
                show_render=True,
            ),
            SimpleNamespace(
                type="NODES",
                node_group=SimpleNamespace(name="Decorative Geometry"),
                show_viewport=True,
                show_render=True,
            ),
        )
        mesh = SimpleNamespace(modifiers=modifiers)

        with _single_part_modifiers(mesh):
            self.assertFalse(modifiers[0].show_viewport)
            self.assertFalse(modifiers[0].show_render)
            self.assertFalse(modifiers[1].show_viewport)
            self.assertFalse(modifiers[1].show_render)
            self.assertTrue(modifiers[2].show_viewport)
            self.assertTrue(modifiers[2].show_render)

        self.assertTrue(modifiers[0].show_viewport)
        self.assertFalse(modifiers[0].show_render)
        self.assertTrue(modifiers[1].show_viewport)
        self.assertTrue(modifiers[1].show_render)


if __name__ == "__main__":
    unittest.main()
