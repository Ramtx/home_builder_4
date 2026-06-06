import json
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
except ModuleNotFoundError:
    bpy = None


@unittest.skipUnless(bpy is not None, "Blender bpy module is unavailable")
class BlenderDrawingExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from manufacturing import operators, props, ui

        cls.modules = (props, operators, ui)
        for module in cls.modules:
            module.register()

    @classmethod
    def tearDownClass(cls):
        for module in reversed(cls.modules):
            module.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.collection = bpy.context.scene.collection

    def _empty(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        self.collection.objects.link(obj)
        obj.parent = parent
        return obj

    def test_operator_exports_scene_to_pdf_svg_and_dxf(self):
        from manufacturing.model import stable_id

        cabinet = self._empty("Base Cabinet")
        cabinet["IS_CABINET_BP"] = True
        cabinet["MANUFACTURING_ID"] = "blender-cabinet"

        part = self._empty("Operator Panel", cabinet)
        part["IS_CUTPART_BP"] = True
        part["MANUFACTURING_ID"] = "blender-panel"
        part["MANUFACTURING_MATERIAL"] = "White Melamine"
        part["MANUFACTURING_OUTLINE"] = json.dumps(
            ((0, 0), (500, 0), (500, 300), (0, 300))
        )
        for axis, (tag, value) in enumerate(
            zip(("obj_x", "obj_y", "obj_z"), (0.5, 0.3, 0.018))
        ):
            dimension = self._empty(f"Operator Panel {tag}", part)
            dimension[tag] = True
            dimension.location[axis] = value

        with tempfile.TemporaryDirectory() as root:
            result = bpy.ops.manufacturing.export_drawings(
                directory=root,
            )
            files = sorted(
                str(path.relative_to(root))
                for path in Path(root).rglob("*")
                if path.is_file()
            )

        self.assertEqual(result, {"FINISHED"})
        panel_id = stable_id("part", "blender-panel")
        self.assertEqual(
            files,
            [
                ".home_builder_drawings.json",
                f"dxf/operator-panel__{panel_id}.dxf",
                "manufacturing_booklet.pdf",
                f"svg/operator-panel__{panel_id}.svg",
            ],
        )
        self.assertEqual(
            bpy.context.scene.manufacturing.drawing_output_directory,
            root,
        )


if __name__ == "__main__":
    unittest.main()
