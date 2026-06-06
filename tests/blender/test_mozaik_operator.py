import json
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
except ModuleNotFoundError:
    bpy = None

from manufacturing import operators, props, ui
from manufacturing.mozaik import DEFAULT_PROFILE_PATH


@unittest.skipUnless(bpy is not None, "Blender bpy module is unavailable")
class BlenderMozaikOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        props.register()
        operators.register()
        ui.register()

    @classmethod
    def tearDownClass(cls):
        ui.unregister()
        operators.unregister()
        props.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def _empty(self, name, parent=None):
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = parent
        return obj

    def _create_panel(self):
        cabinet = self._empty("Cabinet")
        cabinet["IS_CABINET_BP"] = True
        cabinet["MANUFACTURING_ID"] = "operator-cabinet"

        part = self._empty("Shelf", cabinet)
        part["IS_CUTPART_BP"] = True
        part["MANUFACTURING_ID"] = "operator-shelf"
        part["MANUFACTURING_MATERIAL"] = "White Melamine"
        dimensions = (0.5, 0.3, 0.018)
        for axis, (tag, value) in enumerate(
            zip(("obj_x", "obj_y", "obj_z"), dimensions)
        ):
            dimension = self._empty(f"Shelf-{tag}", part)
            dimension[tag] = True
            dimension.location[axis] = value

        outline = ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3))
        vertices = [(x, y, 0) for x, y in outline]
        vertices.extend((x, y, dimensions[2]) for x, y in outline)
        faces = [(3, 2, 1, 0), (4, 5, 6, 7)]
        faces.extend(
            (
                index,
                (index + 1) % 4,
                (index + 1) % 4 + 4,
                index + 4,
            )
            for index in range(4)
        )
        mesh = bpy.data.meshes.new("Shelf Mesh")
        mesh.from_pydata(vertices, (), faces)
        mesh.update()
        mesh_object = bpy.data.objects.new("Shelf Mesh", mesh)
        bpy.context.scene.collection.objects.link(mesh_object)
        mesh_object.parent = part
        mesh_object.data.materials.append(bpy.data.materials.new("White Melamine"))

    def test_registered_operator_writes_complete_package(self):
        self._create_panel()
        output_directory = Path(self.temporary.name) / "package"
        settings = bpy.context.scene.manufacturing
        settings.output_directory = str(output_directory)
        settings.profile_path = str(DEFAULT_PROFILE_PATH)

        result = bpy.ops.manufacturing.export_mozaik_package()

        self.assertEqual(result, {"FINISHED"})
        manifest_path = output_directory / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["panels"]), 1)
        self.assertTrue((output_directory / manifest["panels"][0]["dxf_file"]).is_file())
        self.assertFalse(manifest["compatibility"]["native_moz"])


if __name__ == "__main__":
    unittest.main()
