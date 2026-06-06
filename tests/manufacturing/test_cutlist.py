import csv
import io
import json
import tempfile
from pathlib import Path
import unittest

from manufacturing.cutlist import (
    build_cut_list,
    export_cut_list,
    format_mm,
    render_hardware_json,
    render_html,
    render_parts_csv,
    render_parts_json,
    render_validation_json,
)
from manufacturing.geometry import Polygon2D, rectangle_outline
from manufacturing.model import (
    Cabinet,
    EdgeBanding,
    Face,
    GrainDirection,
    HardwareItem,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
)


def make_part(
    part_id,
    *,
    cabinet_id="cabinet-a",
    name="Shelf",
    quantity=1,
    material_id="material-a",
    grain=GrainDirection.NONE,
    rotation_allowed=True,
    edge_banding=None,
    machining=(),
    source_id=None,
    length_mm=500,
    width_mm=300,
    thickness_mm=18,
    outline=None,
):
    return Part(
        id=part_id,
        source_id=f"source-{part_id}" if source_id is None else source_id,
        cabinet_id=cabinet_id,
        name=name,
        category=PartCategory.SHELF,
        quantity=quantity,
        material_id=material_id,
        length_mm=length_mm,
        width_mm=width_mm,
        thickness_mm=thickness_mm,
        outline=outline or rectangle_outline(max(length_mm, 1), max(width_mm, 1)),
        rotation_allowed=rotation_allowed,
        grain=grain,
        edge_banding=edge_banding or EdgeBanding(),
        face=Face.TOP,
        machining=machining,
    )


def make_project(*, parts=(), hardware=(), cabinets=None, materials=None, name="Project"):
    return ManufacturingProject(
        project_id="project-a",
        name=name,
        source_path="/projects/example.blend",
        cabinets=cabinets
        or (
            Cabinet("cabinet-a", "Base A", "source-cabinet-a"),
            Cabinet("cabinet-b", "Base B", "source-cabinet-b"),
        ),
        parts=parts,
        materials=materials
        if materials is not None
        else (
            Material("material-a", "White melamine", 18),
            Material("material-b", "Oak veneer", 18),
        ),
        hardware=hardware,
    )


class CutListTests(unittest.TestCase):
    def test_repeated_shelves_consolidate_and_keep_traceability(self):
        project = make_project(
            parts=(
                make_part("part-a", quantity=4),
                make_part(
                    "part-b",
                    cabinet_id="cabinet-b",
                    name="Upper shelf",
                    quantity=2,
                ),
            )
        )

        report = build_cut_list(project)

        self.assertEqual(len(report.parts), 1)
        row = report.parts[0]
        self.assertEqual(row.quantity, 6)
        self.assertEqual(row.cabinet_ids, ("cabinet-a", "cabinet-b"))
        self.assertEqual(row.part_ids, ("part-a", "part-b"))
        self.assertEqual(len(row.trace), 2)
        self.assertEqual(report.materials[0].quantity, 6)
        self.assertEqual(report.materials[0].finished_area_m2, 0.9)

    def test_material_summary_uses_shaped_outline_and_cutout_area(self):
        shaped_outline = Polygon2D(
            ((0, 0), (500, 0), (500, 200), (300, 200), (300, 400), (0, 400)),
            (((100, 100), (200, 100), (200, 200), (100, 200)),),
        )
        project = make_project(
            parts=(
                make_part(
                    "shaped",
                    quantity=2,
                    length_mm=500,
                    width_mm=400,
                    outline=shaped_outline,
                ),
            )
        )

        report = build_cut_list(project)

        self.assertEqual(shaped_outline.area, 150000)
        self.assertEqual(report.materials[0].finished_area_m2, 0.3)

    def test_material_grain_edge_outline_and_machining_are_group_identity(self):
        hole_a = MachiningOperation(
            "operation-a",
            MachiningType.BLIND_HOLE,
            Face.TOP,
            x_mm=32,
            y_mm=37,
            diameter_mm=5,
            depth_mm=12,
        )
        hole_same = MachiningOperation(
            "operation-source-specific",
            MachiningType.BLIND_HOLE,
            Face.TOP,
            x_mm=32,
            y_mm=37,
            diameter_mm=5,
            depth_mm=12,
        )
        hole_deeper = MachiningOperation(
            "operation-b",
            MachiningType.BLIND_HOLE,
            Face.TOP,
            x_mm=32,
            y_mm=37,
            diameter_mm=5,
            depth_mm=15,
        )
        parts = (
            make_part("base-a", machining=(hole_a,)),
            make_part("base-b", machining=(hole_same,)),
            make_part("material", material_id="material-b", machining=(hole_a,)),
            make_part("grain", grain=GrainDirection.LENGTH, machining=(hole_a,)),
            make_part(
                "edge",
                edge_banding=EdgeBanding(front="1 mm ABS"),
                machining=(hole_a,),
            ),
            make_part("machining", machining=(hole_deeper,)),
        )

        report = build_cut_list(make_project(parts=parts))

        self.assertEqual(len(report.parts), 5)
        consolidated = next(row for row in report.parts if set(row.part_ids) == {"base-a", "base-b"})
        self.assertEqual(consolidated.quantity, 2)
        self.assertIn("depth=12", consolidated.machining_summary)

    def test_machining_operation_ids_and_order_do_not_prevent_consolidation(self):
        first = (
            MachiningOperation(
                "z-source-id",
                MachiningType.BLIND_HOLE,
                Face.TOP,
                x_mm=32,
                y_mm=37,
                diameter_mm=5,
                depth_mm=12,
            ),
            MachiningOperation(
                "a-source-id",
                MachiningType.GROOVE,
                Face.TOP,
                x_mm=0,
                y_mm=100,
                end_x_mm=500,
                end_y_mm=100,
                width_mm=6,
                depth_mm=6,
            ),
        )
        second = (
            MachiningOperation(
                "a-other-id",
                MachiningType.BLIND_HOLE,
                Face.TOP,
                x_mm=32,
                y_mm=37,
                diameter_mm=5,
                depth_mm=12,
            ),
            MachiningOperation(
                "z-other-id",
                MachiningType.GROOVE,
                Face.TOP,
                x_mm=0,
                y_mm=100,
                end_x_mm=500,
                end_y_mm=100,
                width_mm=6,
                depth_mm=6,
            ),
        )

        report = build_cut_list(
            make_project(
                parts=(
                    make_part("part-a", machining=first),
                    make_part("part-b", machining=second),
                )
            )
        )

        self.assertEqual(len(report.parts), 1)
        self.assertEqual(report.parts[0].quantity, 2)

    def test_unit_formatting_and_row_order_are_deterministic(self):
        first = make_project(
            parts=(
                make_part("part-z", material_id="material-b", length_mm=400),
                make_part("part-a", length_mm=600),
            )
        )
        second = make_project(parts=tuple(reversed(first.parts)))

        self.assertEqual(format_mm(12.3400), "12.34")
        self.assertEqual(format_mm(12.34567), "12.3457")
        self.assertEqual(format_mm(-0.0), "0")
        self.assertEqual(render_parts_json(build_cut_list(first)), render_parts_json(build_cut_list(second)))
        self.assertEqual(render_parts_csv(build_cut_list(first)), render_parts_csv(build_cut_list(second)))

    def test_csv_escaping_unicode_newlines_and_json_stability(self):
        material = Material(
            "material-a",
            'Birch, "Premium"\nÉdition',
            18,
        )
        cabinet = Cabinet(
            "cabinet-a",
            'Kitchen, "North"\nWall',
            "source-cabinet",
            ("part-a",),
        )
        part = make_part(
            "part-a",
            name='Shelf, "A"\nCafé',
            source_id='source, "part"\nα',
        )
        report = build_cut_list(
            make_project(
                parts=(part,),
                cabinets=(cabinet,),
                materials=(material,),
                name='Project, "One"\nΩ',
            )
        )

        payload = render_parts_csv(report)
        parsed = list(csv.DictReader(io.StringIO(payload)))

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["part_names"], part.name)
        self.assertEqual(parsed[0]["material_name"], material.name)
        self.assertEqual(parsed[0]["source_identities"], part.source_id)
        json_payload = render_parts_json(report)
        self.assertIn("Café", json_payload)
        self.assertEqual(json_payload, render_parts_json(build_cut_list(make_project(
            parts=(part,),
            cabinets=(cabinet,),
            materials=(material,),
            name='Project, "One"\nΩ',
        ))))
        self.assertIn("Shelf, &quot;A&quot;", render_html(report))

    def test_empty_and_incomplete_jobs_produce_warnings_without_omitting_parts(self):
        empty_report = build_cut_list(make_project(parts=(), hardware=()))
        empty_codes = {issue.code for issue in empty_report.issues}
        self.assertIn("cutlist.no_parts", empty_codes)
        self.assertIn("cutlist.empty_job", empty_codes)

        incomplete = make_part(
            "part-incomplete",
            cabinet_id="missing-cabinet",
            name="",
            material_id=None,
            source_id="",
        )
        report = build_cut_list(
            make_project(
                parts=(incomplete,),
                cabinets=(Cabinet("cabinet-a", "Base", "source"),),
                materials=(),
            )
        )

        self.assertEqual(len(report.parts), 1)
        codes = {issue.code for issue in report.issues}
        self.assertIn("cutlist.part_missing_material", codes)
        self.assertIn("cutlist.part_missing_name", codes)
        self.assertIn("cutlist.part_missing_source_identity", codes)
        self.assertIn("part.missing_cabinet", codes)
        self.assertIn("cutlist.part_missing_material", report.parts[0].validation_codes)
        validation = json.loads(render_validation_json(report))
        self.assertGreaterEqual(validation["counts"]["warning"], 3)

    def test_hardware_consolidates_by_name_and_supplier_code(self):
        hardware = (
            HardwareItem("hardware-a", "110 degree hinge", 2, "H-110", "cabinet-a"),
            HardwareItem("hardware-b", "110 degree hinge", 4, "H-110", "cabinet-b"),
            HardwareItem("hardware-c", "110 degree hinge", 1, "H-110-S", "cabinet-a"),
        )

        report = build_cut_list(make_project(hardware=hardware))

        self.assertEqual(len(report.hardware), 2)
        grouped = next(row for row in report.hardware if row.supplier_code == "H-110")
        self.assertEqual(grouped.quantity, 6)
        self.assertEqual(grouped.cabinet_ids, ("cabinet-a", "cabinet-b"))
        payload = json.loads(render_hardware_json(report))
        self.assertEqual(payload["total_quantity"], 7)

    def test_export_writes_complete_bundle(self):
        report_project = make_project(parts=(make_part("part-a"),))

        with tempfile.TemporaryDirectory() as directory:
            exported = export_cut_list(report_project, directory)

            self.assertEqual(len(exported.paths()), 9)
            self.assertTrue(all(path.is_file() for path in exported.paths()))
            self.assertEqual(Path(directory), exported.directory)
            self.assertTrue(exported.parts_json.read_text(encoding="utf-8").endswith("\n"))


if __name__ == "__main__":
    unittest.main()
