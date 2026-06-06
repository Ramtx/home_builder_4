import unittest

from manufacturing.geometry import Polygon2D, rectangle_outline
from manufacturing.model import (
    GrainDirection,
    Material,
    StockDefinition,
)
from manufacturing.nesting import (
    NestingConfig,
    NestingStrategy,
    RotationPolicy,
    StockSpec,
    _polygons_overlap,
    dumps,
    optimize,
    validate_result,
)
from nesting_test_helpers import make_part, make_project


class RectangularNestingTests(unittest.TestCase):
    def config(self, **kwargs):
        values = {"kerf_mm": 0, "margin_mm": 0, "spacing_mm": 0}
        values.update(kwargs)
        return NestingConfig(**values)

    def test_exact_fit_uses_one_sheet_at_full_utilization(self):
        project = make_project(
            (make_part("part-a", 100, 50),),
            stock=(StockDefinition("stock", "Exact", 100, 50),),
        )

        result = optimize(project, self.config())

        self.assertTrue(result.is_valid)
        self.assertEqual(result.placed_part_count, 1)
        self.assertEqual(len(result.sheets), 1)
        self.assertEqual(result.sheets[0].utilization, 1.0)
        self.assertEqual((result.sheets[0].placements[0].x_mm, result.sheets[0].placements[0].y_mm), (0, 0))

    def test_multiple_sheets_and_finite_stock_exhaustion(self):
        project = make_project(
            (make_part("part-a", 60, 60, quantity=3),),
            stock=(StockDefinition("stock", "Finite", 100, 100, quantity=2),),
        )

        result = optimize(project, self.config())

        self.assertEqual(len(result.sheets), 2)
        self.assertEqual(result.placed_part_count, 2)
        self.assertEqual(len(result.unplaced_parts), 1)
        self.assertEqual(result.unplaced_parts[0].reason, "stock_exhausted")

    def test_oversized_and_no_stock_are_explicit(self):
        oversized = optimize(
            make_project(
                (make_part("large", 101, 100),),
                stock=(StockDefinition("stock", "Small", 100, 100),),
            ),
            self.config(),
        )
        no_stock = optimize(
            make_project((make_part("part-a"),), stock=()),
            self.config(stock=()),
        )

        self.assertEqual(oversized.unplaced_parts[0].reason, "part_does_not_fit_stock")
        self.assertEqual(no_stock.unplaced_parts[0].reason, "no_stock")
        self.assertFalse(oversized.sheets)
        self.assertFalse(no_stock.sheets)

    def test_kerf_spacing_and_margins_are_reserved(self):
        parts = (make_part("part-a", 45, 50, quantity=2),)
        project = make_project(
            parts,
            stock=(StockDefinition("stock", "Stock", 100, 50),),
        )

        exact_clearance = optimize(
            project,
            self.config(kerf_mm=4, spacing_mm=6),
        )
        too_much_clearance = optimize(
            project,
            self.config(kerf_mm=5, spacing_mm=6),
        )
        margin_fit = optimize(
            make_project(
                (make_part("margin", 90, 90),),
                stock=(StockDefinition("stock", "Stock", 100, 100),),
            ),
            self.config(margin_mm=5),
        )

        self.assertEqual(len(exact_clearance.sheets), 1)
        self.assertEqual(len(too_much_clearance.sheets), 2)
        self.assertEqual((margin_fit.sheets[0].placements[0].x_mm, margin_fit.sheets[0].placements[0].y_mm), (5, 5))

    def test_remnants_are_consumed_before_new_stock(self):
        project = make_project((make_part("part-a", 40, 40, quantity=2),))
        config = self.config(
            stock=(
                StockSpec("remnant", "Remnant", 50, 50, quantity=1, is_remnant=True),
                StockSpec("full", "Full", 100, 100, quantity=1),
            )
        )

        result = optimize(project, config)

        self.assertEqual([sheet.stock_id for sheet in result.sheets], ["remnant", "full"])
        self.assertTrue(result.sheets[0].is_remnant)

    def test_rotation_and_grain_constraints(self):
        rotatable = make_project(
            (make_part("rotatable", 100, 60),),
            stock=(StockDefinition("stock", "Stock", 80, 120),),
        )
        grain_part = make_part(
            "grain",
            100,
            60,
            grain=GrainDirection.LENGTH,
            rotation_allowed=True,
        )
        grain_project = make_project((grain_part,))

        rotated = optimize(rotatable, self.config())
        blocked = optimize(
            grain_project,
            self.config(
                stock=(StockSpec("stock", "Stock", 80, 120, grain=GrainDirection.LENGTH),)
            ),
        )
        aligned = optimize(
            grain_project,
            self.config(
                stock=(StockSpec("stock", "Stock", 80, 120, grain=GrainDirection.WIDTH),)
            ),
        )
        never = optimize(
            rotatable,
            self.config(rotation_policy=RotationPolicy.NEVER),
        )

        self.assertEqual(rotated.sheets[0].placements[0].rotation_deg, 90)
        self.assertEqual(blocked.unplaced_parts[0].reason, "part_does_not_fit_stock")
        self.assertEqual(aligned.sheets[0].placements[0].rotation_deg, 90)
        self.assertEqual(never.unplaced_parts[0].reason, "part_does_not_fit_stock")

    def test_material_and_thickness_groups_never_share_sheets(self):
        parts = (
            make_part("part-a", material_id="material-a", thickness=18),
            make_part("part-b", material_id="material-b", thickness=12),
        )
        project = make_project(
            parts,
            materials=(
                Material("material-a", "Board A", 18),
                Material("material-b", "Board B", 12),
            ),
        )
        config = self.config(
            stock=(
                StockSpec("stock-a", "A", 200, 100, material_id="material-a", thickness_mm=18),
                StockSpec("stock-b", "B", 200, 100, material_id="material-b", thickness_mm=12),
            )
        )

        result = optimize(project, config)

        self.assertEqual(len(result.sheets), 2)
        self.assertEqual(
            {(sheet.material_id, sheet.thickness_mm) for sheet in result.sheets},
            {("material-a", 18), ("material-b", 12)},
        )
        self.assertEqual(len(result.summaries), 2)

    def test_shaped_parts_are_explicitly_rejected_by_guillotine_strategy(self):
        notch = Polygon2D(
            ((0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100))
        )
        project = make_project(
            (make_part("notched", 100, 100, outline=notch),),
            stock=(StockDefinition("stock", "Stock", 100, 100),),
        )

        result = optimize(project, self.config())

        self.assertEqual(result.unplaced_parts[0].reason, "strategy_requires_rectangle")

    def test_results_are_deterministic(self):
        parts = (
            make_part("part-z", 90, 40, quantity=2),
            make_part("part-a", 60, 30, quantity=3),
        )
        first = optimize(make_project(parts), self.config())
        second = optimize(make_project(tuple(reversed(parts))), self.config())

        self.assertEqual(dumps(first), dumps(second))


class PolygonNestingTests(unittest.TestCase):
    def config(self, **kwargs):
        values = {
            "strategy": NestingStrategy.POLYGON,
            "kerf_mm": 0,
            "margin_mm": 0,
            "spacing_mm": 1,
        }
        values.update(kwargs)
        return NestingConfig(**values)

    def test_concave_notch_is_used_without_overlap(self):
        l_shape = Polygon2D(
            ((0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100))
        )
        parts = (
            make_part("l-shape", 100, 100, outline=l_shape),
            make_part("notch-part", 45, 45),
        )
        project = make_project(
            parts,
            stock=(StockDefinition("stock", "Stock", 100, 100),),
        )

        result = optimize(project, self.config())

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.sheets), 1)
        placements = {item.part_id: item for item in result.sheets[0].placements}
        self.assertEqual(
            (placements["notch-part"].x_mm, placements["notch-part"].y_mm),
            (51, 51),
        )
        self.assertEqual(validate_result(result), ())

    def test_inner_cutout_can_receive_another_part(self):
        ring = Polygon2D(
            ((0, 0), (100, 0), (100, 100), (0, 100)),
            (((20, 20), (80, 20), (80, 80), (20, 80)),),
        )
        parts = (
            make_part("ring", 100, 100, outline=ring),
            make_part("inside", 50, 50),
        )
        project = make_project(
            parts,
            stock=(StockDefinition("stock", "Stock", 100, 100),),
        )

        result = optimize(project, self.config())

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.sheets), 1)
        placements = {item.part_id: item for item in result.sheets[0].placements}
        self.assertEqual((placements["inside"].x_mm, placements["inside"].y_mm), (21, 21))

    def test_curved_approximation_stays_in_bounds(self):
        octagon = Polygon2D(
            (
                (10, 0),
                (30, 0),
                (40, 10),
                (40, 30),
                (30, 40),
                (10, 40),
                (0, 30),
                (0, 10),
            )
        )
        project = make_project(
            (make_part("curve", 40, 40, outline=octagon),),
            stock=(StockDefinition("stock", "Stock", 50, 50),),
        )

        result = optimize(project, self.config(margin_mm=5))

        self.assertTrue(result.is_valid)
        placement = result.sheets[0].placements[0]
        self.assertEqual(placement.polygon.bounds, (5, 5, 45, 45))
        self.assertEqual(placement.polygon.area, octagon.area)
        self.assertEqual(len(placement.polygon.outer), 8)

    def test_aligned_area_overlap_is_distinct_from_a_shared_edge(self):
        first = rectangle_outline(100, 100)
        overlapping = Polygon2D(((50, 0), (150, 0), (150, 100), (50, 100)))
        adjacent = Polygon2D(((100, 0), (200, 0), (200, 100), (100, 100)))

        self.assertTrue(_polygons_overlap(first, overlapping))
        self.assertFalse(_polygons_overlap(first, adjacent))


if __name__ == "__main__":
    unittest.main()
