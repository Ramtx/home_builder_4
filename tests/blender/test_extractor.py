import unittest

try:
    import bpy
except ModuleNotFoundError:
    bpy = None

from manufacturing.extractor import extract_scene


@unittest.skipUnless(bpy is not None, "Blender bpy module is unavailable")
class BlenderExtractorTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.collection = bpy.context.scene.collection
        self.cabinet = self._empty("Cabinet", None)
        self.cabinet["IS_CABINET_BP"] = True
        self.cabinet["MANUFACTURING_ID"] = "test-cabinet"

    def _empty(self, name, parent):
        obj = bpy.data.objects.new(name, None)
        self.collection.objects.link(obj)
        obj.parent = parent
        return obj

    def _mesh(self, name, outline, thickness, parent):
        count = len(outline)
        vertices = [(x, y, 0) for x, y in outline]
        vertices.extend((x, y, thickness) for x, y in outline)
        faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
        for index in range(count):
            following = (index + 1) % count
            faces.append((index, following, following + count, index + count))
        mesh = bpy.data.meshes.new(f"{name} Mesh")
        mesh.from_pydata(vertices, (), faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        self.collection.objects.link(obj)
        obj.parent = parent
        material = bpy.data.materials.get("White Melamine") or bpy.data.materials.new(
            "White Melamine"
        )
        obj.data.materials.append(material)
        return obj

    def _part(self, name, dimensions, outline, quantity=1):
        bp = self._empty(name, self.cabinet)
        bp["IS_CUTPART_BP"] = True
        bp["MANUFACTURING_ID"] = f"test-{name}"
        bp["MANUFACTURING_MATERIAL"] = "White Melamine"
        for axis, (tag, value) in enumerate(
            zip(("obj_x", "obj_y", "obj_z"), dimensions)
        ):
            dimension = self._empty(f"{name}-{tag}", bp)
            dimension[tag] = True
            dimension.location[axis] = value
        mesh = self._mesh(f"{name} Mesh", outline, dimensions[2], bp)
        if quantity > 1:
            modifier = mesh.modifiers.new("Array", "ARRAY")
            modifier.count = quantity
            modifier.use_relative_offset = False
            modifier.use_constant_offset = True
            modifier.constant_offset_displace = (0, 0, 0.1)
        return bp

    def test_rectangular_repeated_and_shaped_parts(self):
        self._part(
            "Rectangular",
            (0.5, -0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, -0.3), (0, -0.3)),
        )
        self._part(
            "Repeated",
            (0.45, 0.25, 0.018),
            ((0, 0), (0.45, 0), (0.45, 0.25), (0, 0.25)),
            quantity=4,
        )
        self._part(
            "Shaped",
            (0.5, 0.4, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.2), (0.3, 0.2), (0.3, 0.4), (0, 0.4)),
        )

        project = extract_scene()
        parts = {part.name: part for part in project.parts}

        self.assertEqual(set(parts), {"Rectangular", "Repeated", "Shaped"})
        self.assertEqual(
            (
                parts["Rectangular"].length_mm,
                parts["Rectangular"].width_mm,
                parts["Rectangular"].thickness_mm,
            ),
            (500, 300, 18),
        )
        self.assertEqual(parts["Repeated"].quantity, 4)
        self.assertEqual(parts["Repeated"].outline.bounds, (0, 0, 450, 250))
        self.assertEqual(len(parts["Shaped"].outline.outer), 6)
        self.assertEqual(parts["Shaped"].outline.bounds, (0, 0, 500, 400))
        self.assertFalse(
            {
                issue.code
                for issue in project.issues
                if issue.severity.value == "error"
            }
        )

    def test_suppressed_and_appliance_parts_are_excluded(self):
        suppressed = self._part(
            "Suppressed",
            (0.5, 0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3)),
        )
        suppressed["MANUFACTURING_SUPPRESSED"] = True

        appliance = self._empty("Appliance", self.cabinet)
        appliance["IS_APPLIANCE_BP"] = True
        part = self._part(
            "Appliance Part",
            (0.5, 0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3)),
        )
        part.parent = appliance

        project = extract_scene()
        self.assertEqual(project.parts, ())

    def test_invalid_explicit_outline_falls_back_with_issue(self):
        part = self._part(
            "Malformed Outline",
            (0.5, 0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3)),
        )
        part["MANUFACTURING_OUTLINE"] = "{not-json"

        project = extract_scene()

        self.assertEqual(len(project.parts), 1)
        self.assertEqual(project.parts[0].outline.bounds, (0, 0, 500, 300))
        self.assertIn(
            "extractor.invalid_explicit_outline",
            {issue.code for issue in project.issues},
        )

    def test_scaled_panel_dimensions_and_outline_use_same_space(self):
        part = self._part(
            "Scaled",
            (0.5, 0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3)),
        )
        part.scale = (2.0, 0.5, 2.0)

        project = extract_scene()
        extracted = project.parts[0]

        self.assertEqual(
            (
                extracted.length_mm,
                extracted.width_mm,
                extracted.thickness_mm,
            ),
            (1000, 150, 36),
        )
        self.assertEqual(extracted.outline.bounds, (0, 0, 1000, 150))
        self.assertNotIn(
            "extractor.outline_out_of_bounds",
            {issue.code for issue in project.issues},
        )

    def test_ancestor_scale_is_applied_to_dimensions_and_outline(self):
        self.cabinet.scale = (2.0, 0.5, 2.0)
        self._part(
            "Ancestor Scaled",
            (0.5, 0.3, 0.018),
            ((0, 0), (0.5, 0), (0.5, 0.3), (0, 0.3)),
        )

        extracted = extract_scene().parts[0]

        self.assertEqual(
            (
                extracted.length_mm,
                extracted.width_mm,
                extracted.thickness_mm,
            ),
            (1000, 150, 36),
        )
        self.assertEqual(extracted.outline.bounds, (0, 0, 1000, 150))


if __name__ == "__main__":
    unittest.main()
