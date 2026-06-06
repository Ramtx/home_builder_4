import unittest

from manufacturing.dxf import DXF_MILLIMETRES, DxfDocument, DxfLayer, format_number


class DxfTests(unittest.TestCase):
    def test_r2000_document_declares_millimetres_and_layers(self):
        document = DxfDocument(
            (
                DxfLayer("HB4_OUTLINE", 7),
                DxfLayer("HB4_DRILL", 3),
            )
        )
        document.add_lwpolyline(
            "HB4_OUTLINE",
            ((0, 0), (500.25, 0), (500.25, 300), (0, 300)),
        )
        document.add_circle("HB4_DRILL", (32, 37), 2.5)
        payload = document.render()

        self.assertIn("9\n$ACADVER\n1\nAC1015\n", payload)
        self.assertIn(f"9\n$INSUNITS\n70\n{DXF_MILLIMETRES}\n", payload)
        self.assertIn("2\nHB4_OUTLINE\n", payload)
        self.assertIn("2\nHB4_DRILL\n", payload)
        self.assertIn("10\n500.25\n", payload)
        self.assertTrue(payload.endswith("0\nEOF\n"))

    def test_number_format_is_locale_independent_and_rejects_non_finite(self):
        self.assertEqual(format_number(1234.5), "1234.5")
        self.assertEqual(format_number(-0.0), "0")
        with self.assertRaisesRegex(ValueError, "finite"):
            format_number(float("nan"))


if __name__ == "__main__":
    unittest.main()
