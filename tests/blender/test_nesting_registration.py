from pathlib import Path
import tempfile
import unittest

try:
    import bpy
except ModuleNotFoundError:
    bpy = None


@unittest.skipUnless(bpy is not None, "Blender bpy module is unavailable")
class BlenderNestingRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from manufacturing import operators, props, ui

        cls.operators = operators
        cls.props = props
        cls.ui = ui
        cls.registered_here = not hasattr(
            bpy.types.Scene, "manufacturing_nesting"
        )
        if cls.registered_here:
            props.register()
            operators.register()
            ui.register()

    @classmethod
    def tearDownClass(cls):
        if cls.registered_here:
            cls.ui.unregister()
            cls.operators.unregister()
            cls.props.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _empty(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = parent
        return obj

    def _add_cut_part(self):
        cabinet = self._empty("Cabinet")
        cabinet["IS_CABINET_BP"] = True
        cabinet["MANUFACTURING_ID"] = "nesting-cabinet"
        part = self._empty("Panel", cabinet)
        part["IS_CUTPART_BP"] = True
        part["MANUFACTURING_ID"] = "nesting-panel"
        part["MANUFACTURING_MATERIAL"] = "White Melamine"
        for axis, (tag, value) in enumerate(
            zip(("obj_x", "obj_y", "obj_z"), (0.5, 0.3, 0.018))
        ):
            dimension = self._empty(tag, part)
            dimension[tag] = True
            dimension.location[axis] = value

        vertices = (
            (0, 0, 0),
            (0.5, 0, 0),
            (0.5, 0.3, 0),
            (0, 0.3, 0),
            (0, 0, 0.018),
            (0.5, 0, 0.018),
            (0.5, 0.3, 0.018),
            (0, 0.3, 0.018),
        )
        faces = (
            (0, 3, 2, 1),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (1, 2, 6, 5),
            (2, 3, 7, 6),
            (3, 0, 4, 7),
        )
        mesh = bpy.data.meshes.new("Panel Mesh")
        mesh.from_pydata(vertices, (), faces)
        obj = bpy.data.objects.new("Panel Mesh", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = part
        obj.data.materials.append(bpy.data.materials.new("White Melamine"))

    def test_properties_operator_and_panel_register_together(self):
        self.assertTrue(hasattr(bpy.types.Scene, "manufacturing_nesting"))
        self.assertTrue(hasattr(bpy.types, "MANUFACTURING_OT_export_nesting"))
        self.assertTrue(hasattr(bpy.types, "MANUFACTURING_PT_nesting"))
        self.assertEqual(
            bpy.types.MANUFACTURING_OT_export_nesting.bl_idname,
            "manufacturing.export_nesting",
        )
        self.assertEqual(
            bpy.types.MANUFACTURING_PT_nesting.bl_category,
            "Home Builder",
        )

    def test_export_operator_writes_neutral_nesting_files(self):
        self._add_cut_part()
        with tempfile.TemporaryDirectory() as directory:
            settings = bpy.context.scene.manufacturing_nesting
            settings.stock_width = 1.0
            settings.stock_height = 1.0
            settings.kerf = 0.0
            settings.margin = 0.0
            settings.spacing = 0.0
            settings.export_directory = directory

            result = bpy.ops.manufacturing.export_nesting()

            self.assertEqual(result, {"FINISHED"})
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                {"nesting.json", "nesting.csv", "sheet-0001.svg"},
            )
            self.assertIn("1 placed", settings.last_summary)

    def test_export_operator_rejects_blank_directory(self):
        settings = bpy.context.scene.manufacturing_nesting
        settings.export_directory = "   "

        result = bpy.ops.manufacturing.export_nesting()

        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(settings.last_export_path, "")


if __name__ == "__main__":
    unittest.main()
