import unittest

from manufacturing.geometry import rectangle_outline
from manufacturing.model import (
    Cabinet,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
    ValidationIssue,
    IssueSeverity,
    stable_id,
)
from manufacturing.serialization import dumps


def make_part(part_id="part-b", cabinet_id="cabinet-b", material_id="material-b", quantity=1):
    return Part(
        id=part_id,
        source_id=f"source-{part_id}",
        cabinet_id=cabinet_id,
        name=part_id,
        category=PartCategory.CUSTOM,
        quantity=quantity,
        material_id=material_id,
        length_mm=-500,
        width_mm=-300,
        thickness_mm=-18,
        outline=rectangle_outline(500, 300),
    )


class ModelTests(unittest.TestCase):
    def test_dimensions_are_positive_and_millimetre_rounded(self):
        part = make_part()

        self.assertEqual((part.length_mm, part.width_mm, part.thickness_mm), (500, 300, 18))

    def test_project_ordering_and_json_are_deterministic(self):
        parts = (
            make_part("part-z", "cabinet-z", "material-z"),
            make_part("part-a", "cabinet-a", "material-a"),
        )
        cabinets = (
            Cabinet("cabinet-z", "Z", "source-z", ("part-z",)),
            Cabinet("cabinet-a", "A", "source-a", ("part-a",)),
        )
        materials = (
            Material("material-z", "Z board", 18),
            Material("material-a", "A board", 18),
        )

        forward = ManufacturingProject(
            project_id="project",
            name="Project",
            cabinets=cabinets,
            parts=parts,
            materials=materials,
        )
        reverse = ManufacturingProject(
            project_id="project",
            name="Project",
            cabinets=tuple(reversed(cabinets)),
            parts=tuple(reversed(parts)),
            materials=tuple(reversed(materials)),
        )

        self.assertEqual([part.id for part in forward.parts], ["part-a", "part-z"])
        self.assertEqual(dumps(forward), dumps(reverse))

    def test_validation_reports_references_quantities_and_duplicates(self):
        invalid = make_part(quantity=0)
        project = ManufacturingProject(
            project_id="project",
            name="Project",
            cabinets=(
                Cabinet("cabinet-b", "Cabinet", "source", ("missing-part",)),
            ),
            parts=(invalid, invalid),
            materials=(),
        )

        codes = {issue.code for issue in project.validate()}
        self.assertIn("project.duplicate_part_id", codes)
        self.assertIn("part.invalid_quantity", codes)
        self.assertIn("part.missing_material", codes)
        self.assertIn("cabinet.missing_parts", codes)

    def test_issue_details_have_deterministic_order(self):
        issue = ValidationIssue(
            IssueSeverity.WARNING,
            "test",
            "message",
            details=(("z", 1), ("a", 2)),
        )

        self.assertEqual(issue.details, (("a", 2), ("z", 1)))

    def test_stable_ids_are_repeatable_and_typed(self):
        first = stable_id("part", "cabinet/path", "Panel", 18)
        second = stable_id("part", "cabinet/path", "Panel", 18)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("part-"))
        self.assertNotEqual(first, stable_id("cabinet", "cabinet/path", "Panel", 18))
        self.assertNotEqual(first, stable_id("part", "cabinet/path", "Other", 18))


if __name__ == "__main__":
    unittest.main()
