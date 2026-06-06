import tempfile
from pathlib import Path
import unittest

try:
    import bpy
except ModuleNotFoundError:
    bpy = None

import manufacturing


@unittest.skipUnless(bpy is not None, "Blender bpy module is unavailable")
class BlenderCutListOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manufacturing.register()

    @classmethod
    def tearDownClass(cls):
        manufacturing.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        collection = bpy.context.scene.collection

        cabinet = bpy.data.objects.new("Cabinet", None)
        collection.objects.link(cabinet)
        cabinet["IS_CABINET_BP"] = True
        cabinet["MANUFACTURING_ID"] = "operator-cabinet"

        part = bpy.data.objects.new("Repeated Shelf", None)
        collection.objects.link(part)
        part.parent = cabinet
        part["IS_CUTPART_BP"] = True
        part["IS_SHELF_BP"] = True
        part["MANUFACTURING_ID"] = "operator-shelf"
        part["MANUFACTURING_MATERIAL"] = "White Melamine"
        part["MANUFACTURING_QUANTITY"] = 3

        for axis, (tag, value) in enumerate(
            zip(("obj_x", "obj_y", "obj_z"), (0.5, 0.3, 0.018))
        ):
            dimension = bpy.data.objects.new(f"Repeated Shelf {tag}", None)
            collection.objects.link(dimension)
            dimension.parent = part
            dimension[tag] = True
            dimension.location[axis] = value

    def test_operator_exports_reports_headlessly(self):
        with tempfile.TemporaryDirectory() as directory:
            result = bpy.ops.home_builder.export_manufacturing_cut_list(
                "EXEC_DEFAULT",
                directory=directory,
            )

            self.assertEqual(result, {"FINISHED"})
            expected = {
                "cut_list.csv",
                "cut_list.json",
                "material_summary.csv",
                "material_summary.json",
                "hardware.csv",
                "hardware.json",
                "validation.csv",
                "validation.json",
                "cut_list.html",
            }
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                expected,
            )
            self.assertIn(
                '"total_quantity": 3',
                (Path(directory) / "cut_list.json").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
