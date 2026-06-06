import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manufacturing.geometry import Polygon2D, rectangle_outline
from manufacturing.model import (
    Cabinet,
    Face,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
)
from manufacturing.mozaik import MozaikProfile, export_package, load_profile


def make_part(
    part_id,
    *,
    name=None,
    quantity=1,
    material_id="material-a",
    outline=None,
    machining=(),
):
    return Part(
        id=part_id,
        source_id=f"source-{part_id}",
        cabinet_id="cabinet-a",
        name=name or part_id,
        category=PartCategory.SHELF,
        quantity=quantity,
        material_id=material_id,
        length_mm=500.25,
        width_mm=300,
        thickness_mm=18,
        outline=outline or rectangle_outline(500.25, 300),
        machining=machining,
    )


def make_project(parts, *, material_name="White Melamine"):
    return ManufacturingProject(
        project_id="project-a",
        name="Kitchen",
        cabinets=(
            Cabinet(
                "cabinet-a",
                "Base Cabinet",
                "source-cabinet-a",
                tuple(part.id for part in parts),
            ),
        ),
        parts=tuple(parts),
        materials=(Material("material-a", material_name, 18),),
    )


def directory_contents(path):
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


class MozaikExportTests(unittest.TestCase):
    def test_package_is_deterministic_and_manifest_links_resolve(self):
        hole = MachiningOperation(
            id="hole-a",
            operation_type=MachiningType.BLIND_HOLE,
            face=Face.TOP,
            x_mm=32,
            y_mm=37,
            diameter_mm=5,
            depth_mm=12,
        )
        parts = (
            make_part("part-b", machining=(hole,)),
            make_part("part-a", machining=(hole,)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            first_result = export_package(make_project(parts), first)
            second_result = export_package(
                make_project(tuple(reversed(parts))),
                second,
            )

            self.assertTrue(first_result.ok)
            self.assertEqual(directory_contents(first), directory_contents(second))
            manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["compatibility"]["native_moz"])
            self.assertFalse(manifest["compatibility"]["xml_emitted"])
            for panel in manifest["panels"]:
                self.assertTrue((first / panel["dxf_file"]).is_file())
            for record in manifest["files"]:
                self.assertTrue((first / record["path"]).is_file())
            self.assertFalse(list(first.rglob("*.xml")))
            self.assertFalse(list(first.rglob("*.moz")))

    def test_strict_material_profile_reports_missing_and_accepts_mapping(self):
        profile_data = load_profile().to_dict()
        profile_data["unmapped_material_policy"] = "error"
        profile = MozaikProfile.from_dict(profile_data)
        project = make_project((make_part("part-a"),))

        with tempfile.TemporaryDirectory() as temporary:
            missing = export_package(project, Path(temporary) / "missing", profile)
            self.assertFalse(missing.ok)
            self.assertEqual(missing.panel_count, 0)
            self.assertIn(
                "mozaik.missing_material_mapping",
                {issue.code for issue in missing.issues},
            )

            profile_data["material_mappings"] = [
                {
                    "source_material_id": "material-a",
                    "source_thickness_mm": 18,
                    "export_name": "WHITE-18",
                    "thickness_name": "18MM",
                }
            ]
            mapped = export_package(
                project,
                Path(temporary) / "mapped",
                MozaikProfile.from_dict(profile_data),
            )
            self.assertTrue(mapped.ok)
            manifest = json.loads(
                (Path(temporary) / "mapped" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["panels"][0]["material"]["export_name"],
                "WHITE-18",
            )

    def test_windows_absolute_and_drive_relative_output_paths_are_rejected(self):
        for unsafe_path in ("C:/outside/panels", "C:outside/panels"):
            with self.subTest(unsafe_path=unsafe_path):
                profile_data = load_profile().to_dict()
                profile_data["output"]["panels_directory"] = unsafe_path
                issues = MozaikProfile.from_dict(profile_data).validate()
                self.assertIn(
                    "mozaik.unsafe_output_filename",
                    {issue.code for issue in issues},
                )

    def test_existing_symlink_cannot_escape_package_root(self):
        profile = load_profile()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / profile.output["panels_directory"]).symlink_to(
                outside,
                target_is_directory=True,
            )

            with self.assertRaisesRegex(ValueError, "escapes"):
                export_package(
                    make_project((make_part("part-a"),)),
                    root,
                    profile,
                )
            self.assertTrue(outside.is_dir())

    def test_nested_optimizer_csv_parent_is_created(self):
        profile_data = load_profile().to_dict()
        profile_data["output"]["optimizer_csv"] = "csv/optimizer/parts.csv"
        profile = MozaikProfile.from_dict(profile_data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = export_package(
                make_project((make_part("part-a"),)),
                root,
                profile,
            )

            self.assertTrue(result.ok)
            self.assertTrue((root / "csv/optimizer/parts.csv").is_file())

    def test_csv_quotes_unicode_and_uses_decimal_points(self):
        part = make_part("part-a", name='Étagère, "Nord"')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "locale.localeconv",
                return_value={"decimal_point": ",", "thousands_sep": "."},
            ):
                result = export_package(
                    make_project((part,), material_name="Mélamine, Blanc"),
                    root,
                )

            self.assertTrue(result.ok)
            payload = (root / "optimizer-parts.csv").read_text(encoding="utf-8")
            self.assertIn('"Mélamine, Blanc"', payload)
            self.assertIn('"Étagère, ""Nord"""', payload)
            self.assertIn("500.25", payload)
            with (root / "optimizer-parts.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["Material"], "Mélamine, Blanc")
            self.assertEqual(row["Length"], "500.25")

    def test_duplicate_panel_definitions_aggregate_quantities(self):
        first_operations = (
            MachiningOperation(
                "a-hole",
                MachiningType.THROUGH_HOLE,
                Face.TOP,
                x_mm=32,
                y_mm=32,
                diameter_mm=5,
            ),
            MachiningOperation(
                "z-groove",
                MachiningType.GROOVE,
                Face.TOP,
                x_mm=50,
                y_mm=100,
                end_x_mm=150,
                end_y_mm=100,
                width_mm=10,
            ),
        )
        second_operations = (
            MachiningOperation(
                "a-groove-copy",
                MachiningType.GROOVE,
                Face.TOP,
                x_mm=50,
                y_mm=100,
                end_x_mm=150,
                end_y_mm=100,
                width_mm=10,
            ),
            MachiningOperation(
                "z-hole-copy",
                MachiningType.THROUGH_HOLE,
                Face.TOP,
                x_mm=32,
                y_mm=32,
                diameter_mm=5,
            ),
        )
        parts = (
            make_part(
                "part-a",
                name="Left shelf",
                quantity=2,
                machining=first_operations,
            ),
            make_part(
                "part-b",
                name="Right shelf",
                quantity=3,
                machining=second_operations,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = export_package(make_project(parts), root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            self.assertTrue(result.ok)
            self.assertEqual(result.panel_count, 1)
            self.assertEqual(manifest["panels"][0]["quantity"], 5)
            self.assertEqual(
                manifest["panels"][0]["part_ids"],
                ["part-a", "part-b"],
            )
            self.assertEqual(
                [item["part_id"] for item in manifest["panels"][0]["source_operations"]],
                ["part-a", "part-b"],
            )

    def test_unsupported_machining_is_warned_and_recorded_as_omitted(self):
        side_hole = MachiningOperation(
            id="side-hole",
            operation_type=MachiningType.THROUGH_HOLE,
            face=Face.LEFT,
            x_mm=20,
            y_mm=20,
            diameter_mm=5,
        )
        pathless_cutout = MachiningOperation(
            id="pathless-cutout",
            operation_type=MachiningType.CONTOUR_CUTOUT,
            face=Face.TOP,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = export_package(
                make_project(
                    (
                        make_part(
                            "part-a",
                            machining=(side_hole, pathless_cutout),
                        ),
                    )
                ),
                root,
            )
            codes = {issue.code for issue in result.issues}
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            self.assertTrue(result.ok)
            self.assertIn("mozaik.unsupported_operation_face", codes)
            self.assertIn("mozaik.missing_operation_path", codes)
            self.assertEqual(
                {item["status"] for item in manifest["panels"][0]["machining"]},
                {"omitted"},
            )

    def test_unsafe_outline_and_duplicate_profile_paths_are_errors(self):
        outline = Polygon2D(((0, 0), (500.25, 300), (0, 200), (400, 0)))
        profile_data = load_profile().to_dict()
        profile_data["output"]["manifest"] = profile_data["output"]["optimizer_csv"]
        profile_issues = MozaikProfile.from_dict(profile_data).validate()

        self.assertIn(
            "mozaik.duplicate_output_filename",
            {issue.code for issue in profile_issues},
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = export_package(
                make_project((make_part("part-a", outline=outline),)),
                temporary,
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.panel_count, 0)
            self.assertIn(
                "mozaik.self_intersecting_outline",
                {issue.code for issue in result.issues},
            )

    def test_intersecting_and_nested_cutouts_are_rejected(self):
        cutout_cases = (
            (
                ((50, 50), (250, 50), (250, 200), (50, 200)),
                ((150, 100), (350, 100), (350, 250), (150, 250)),
            ),
            (
                ((50, 50), (350, 50), (350, 250), (50, 250)),
                ((100, 100), (200, 100), (200, 200), (100, 200)),
            ),
        )
        for index, cutouts in enumerate(cutout_cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temporary:
                outline = Polygon2D(
                    ((0, 0), (500.25, 0), (500.25, 300), (0, 300)),
                    cutouts,
                )
                result = export_package(
                    make_project((make_part("part-a", outline=outline),)),
                    temporary,
                )

                self.assertFalse(result.ok)
                self.assertEqual(result.panel_count, 0)
                self.assertIn(
                    "mozaik.overlapping_cutouts",
                    {issue.code for issue in result.issues},
                )

    def test_dxf_contains_all_stable_operation_layers_and_mm_units(self):
        operations = (
            MachiningOperation(
                "through",
                MachiningType.THROUGH_HOLE,
                Face.TOP,
                x_mm=32,
                y_mm=32,
                diameter_mm=5,
            ),
            MachiningOperation(
                "line-bore",
                MachiningType.LINE_BORE,
                Face.TOP,
                x_mm=50,
                y_mm=60,
                end_x_mm=114,
                end_y_mm=60,
                diameter_mm=5,
                spacing_mm=32,
            ),
            MachiningOperation(
                "groove",
                MachiningType.GROOVE,
                Face.BOTTOM,
                x_mm=50,
                y_mm=100,
                end_x_mm=150,
                end_y_mm=100,
                width_mm=10,
                depth_mm=6,
            ),
            MachiningOperation(
                "pocket",
                MachiningType.POCKET,
                Face.TOP,
                depth_mm=6,
                path=((200, 50), (250, 50), (250, 100), (200, 100)),
            ),
            MachiningOperation(
                "cutout",
                MachiningType.CONTOUR_CUTOUT,
                Face.TOP,
                path=((300, 50), (350, 50), (350, 100), (300, 100)),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_package(
                make_project((make_part("part-a", machining=operations),)),
                root,
            )
            dxf_path = next((root / "panels").glob("*.dxf"))
            payload = dxf_path.read_text(encoding="ascii")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            for layer in load_profile().layers.values():
                self.assertIn(f"2\n{layer}\n", payload)
            self.assertIn("9\n$INSUNITS\n70\n4\n", payload)
            self.assertEqual(
                {item["status"] for item in manifest["panels"][0]["machining"]},
                {"exported"},
            )
            self.assertEqual(
                {
                    item["dxf_layer"]
                    for item in manifest["panels"][0]["machining"]
                },
                {
                    "HB4_DRILL",
                    "HB4_GROOVE",
                    "HB4_POCKET",
                    "HB4_CUT_OUT",
                },
            )

    def test_hole_crossing_outline_is_an_error_and_is_omitted(self):
        unsafe_hole = MachiningOperation(
            "unsafe-hole",
            MachiningType.THROUGH_HOLE,
            Face.TOP,
            x_mm=2,
            y_mm=20,
            diameter_mm=10,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = export_package(
                make_project(
                    (make_part("part-a", machining=(unsafe_hole,)),)
                ),
                root,
            )
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

            self.assertFalse(result.ok)
            self.assertIn(
                "mozaik.unsafe_hole_geometry",
                {issue.code for issue in result.issues},
            )
            self.assertEqual(
                manifest["panels"][0]["machining"][0]["status"],
                "omitted",
            )


if __name__ == "__main__":
    unittest.main()
