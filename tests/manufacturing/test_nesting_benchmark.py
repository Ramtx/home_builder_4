import json
from pathlib import Path
import time
import unittest

from manufacturing.model import StockDefinition
from manufacturing.nesting import NestingConfig, optimize
from tests.manufacturing.test_nesting import make_part, make_project


FIXTURE = Path(__file__).with_name("fixtures") / "nesting_benchmark.json"


class NestingBenchmarkTests(unittest.TestCase):
    def test_representative_cabinet_panel_fixture(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        parts = tuple(
            make_part(
                item["id"],
                item["length_mm"],
                item["width_mm"],
                quantity=item["quantity"],
            )
            for item in data["parts"]
        )
        stock = data["stock"]
        project = make_project(
            parts,
            stock=(
                StockDefinition(
                    "benchmark-stock",
                    "Benchmark stock",
                    stock["width_mm"],
                    stock["height_mm"],
                ),
            ),
        )

        started = time.perf_counter()
        result = optimize(project, NestingConfig())
        elapsed = time.perf_counter() - started

        self.assertTrue(result.is_valid)
        self.assertFalse(result.unplaced_parts)
        self.assertEqual(result.placed_part_count, sum(item["quantity"] for item in data["parts"]))
        self.assertEqual(len(result.sheets), 16)
        utilization = sum(sheet.used_area_mm2 for sheet in result.sheets) / sum(
            sheet.stock_area_mm2 for sheet in result.sheets
        )
        self.assertGreater(utilization, 0.72)
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
