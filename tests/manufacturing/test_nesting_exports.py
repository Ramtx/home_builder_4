import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from manufacturing.geometry import Polygon2D
from manufacturing.model import StockDefinition
from manufacturing.nesting import (
    NestingConfig,
    NestingStrategy,
    csv_string,
    dumps,
    export_result,
    optimize,
    svg_string,
)
from nesting_test_helpers import make_part, make_project


class NestingExportTests(unittest.TestCase):
    def make_result(self):
        outline = Polygon2D(
            ((0, 0), (100, 0), (100, 80), (0, 80)),
            (((20, 20), (40, 20), (40, 40), (20, 40)),),
        )
        project = make_project(
            (make_part("part-a", 100, 80, outline=outline, name='Panel, "A" & B'),),
            stock=(StockDefinition("stock", "Stock", 120, 100),),
        )
        return optimize(
            project,
            NestingConfig(
                strategy=NestingStrategy.POLYGON,
                kerf_mm=0,
                margin_mm=10,
                spacing_mm=0,
            ),
        )

    def test_json_and_csv_are_deterministic_and_structured(self):
        result = self.make_result()

        first_json = dumps(result)
        second_json = dumps(result)
        first_csv = csv_string(result)
        second_csv = csv_string(result)

        self.assertEqual(first_json, second_json)
        self.assertEqual(first_csv, second_csv)
        self.assertTrue(first_json.endswith("\n"))
        self.assertTrue(first_csv.endswith("\n"))
        self.assertEqual(json.loads(first_json)["strategy"], "polygon")
        rows = list(csv.DictReader(io.StringIO(first_csv)))
        self.assertEqual(rows[0]["part_name"], 'Panel, "A" & B')
        self.assertEqual(rows[0]["status"], "placed")

    def test_svg_contains_sheet_outline_cutout_path_and_escaped_label(self):
        result = self.make_result()
        payload = svg_string(result.sheets[0], result)

        self.assertIn('viewBox="0 0 120 100"', payload)
        self.assertIn('fill-rule: evenodd', payload)
        self.assertIn("<path", payload)
        self.assertIn("Panel, &quot;A&quot; &amp; B", payload)
        self.assertGreaterEqual(payload.count("M "), 2)
        self.assertEqual(
            ElementTree.fromstring(payload).tag,
            "{http://www.w3.org/2000/svg}svg",
        )

    def test_export_result_writes_json_csv_and_one_svg_per_sheet(self):
        result = self.make_result()
        with tempfile.TemporaryDirectory() as directory:
            paths = export_result(result, directory)

            self.assertEqual(
                {path.name for path in paths},
                {"nesting.json", "nesting.csv", "sheet-0001.svg"},
            )
            self.assertTrue(all(Path(path).is_file() for path in paths))
            self.assertEqual(
                (Path(directory) / "nesting.json").read_text(encoding="utf-8"),
                dumps(result),
            )

    def test_export_result_removes_only_stale_sheet_diagrams(self):
        result = self.make_result()
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "sheet-0002.svg"
            unrelated = Path(directory) / "drawing.svg"
            stale.write_text("stale", encoding="utf-8")
            unrelated.write_text("keep", encoding="utf-8")

            export_result(result, directory)

            self.assertFalse(stale.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
