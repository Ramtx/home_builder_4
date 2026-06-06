import json
import unittest

from manufacturing.geometry import Polygon2D
from manufacturing.model import (
    Cabinet,
    Face,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
    IssueSeverity,
    ValidationIssue,
)
from manufacturing.serialization import SchemaVersionError, dumps, loads


class SerializationTests(unittest.TestCase):
    def make_project(self):
        operation = MachiningOperation(
            id="operation-a",
            operation_type=MachiningType.BLIND_HOLE,
            face=Face.TOP,
            x_mm=32,
            y_mm=37,
            diameter_mm=5,
            depth_mm=12,
        )
        part = Part(
            id="part-a",
            source_id="source-part-a",
            cabinet_id="cabinet-a",
            name="Notched panel",
            category=PartCategory.SHELF,
            quantity=3,
            material_id="material-a",
            length_mm=500,
            width_mm=300,
            thickness_mm=18,
            outline=Polygon2D(
                ((0, 0), (500, 0), (500, 200), (300, 200), (300, 300), (0, 300))
            ),
            machining=(operation,),
            issues=(
                ValidationIssue(
                    IssueSeverity.WARNING,
                    "part.example",
                    "Example structured detail",
                    "part-a",
                    (("bounds", (0, 0, 500, 300)),),
                ),
            ),
        )
        return ManufacturingProject(
            project_id="project-a",
            name="Project",
            cabinets=(Cabinet("cabinet-a", "Cabinet", "source-cabinet", ("part-a",)),),
            parts=(part,),
            materials=(Material("material-a", "White melamine", 18),),
        )

    def test_json_round_trip(self):
        project = self.make_project()
        payload = dumps(project)

        self.assertEqual(loads(payload), project)
        self.assertTrue(payload.endswith("\n"))
        self.assertEqual(payload, dumps(loads(payload)))

    def test_schema_version_is_rejected(self):
        data = json.loads(dumps(self.make_project()))
        data["schema_version"] = 999

        with self.assertRaisesRegex(SchemaVersionError, "999"):
            loads(json.dumps(data))

    def test_json_root_must_be_an_object(self):
        with self.assertRaisesRegex(ValueError, "root"):
            loads("[]")


if __name__ == "__main__":
    unittest.main()
