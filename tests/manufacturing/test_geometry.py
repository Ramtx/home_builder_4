import unittest

from manufacturing.geometry import (
    AxisNormalization,
    Point2D,
    Polygon2D,
    is_clockwise,
    normalize_loop,
    polygon_from_loops,
)


class GeometryTests(unittest.TestCase):
    def test_loop_normalization_is_deterministic(self):
        loop = normalize_loop(
            ((10, 0), (10, 5), (0, 5), (0, 0), (5, 0), (10, 0))
        )

        self.assertEqual(
            loop,
            (
                Point2D(0, 0),
                Point2D(10, 0),
                Point2D(10, 5),
                Point2D(0, 5),
            ),
        )
        self.assertFalse(is_clockwise(loop))

    def test_polygon_normalizes_outer_and_cutout_winding(self):
        polygon = Polygon2D(
            ((10, 0), (0, 0), (0, 10), (10, 10)),
            (((2, 2), (8, 2), (8, 8), (2, 8)),),
        )

        self.assertFalse(is_clockwise(polygon.outer))
        self.assertTrue(is_clockwise(polygon.cutouts[0]))
        self.assertEqual(polygon.area, 64)

    def test_unordered_loops_move_to_lower_left_origin(self):
        polygon = polygon_from_loops(
            (
                ((12, 12), (14, 12), (14, 14), (12, 14)),
                ((10, 10), (20, 10), (20, 20), (10, 20)),
            )
        )

        self.assertEqual(polygon.bounds, (0, 0, 10, 10))
        self.assertEqual(len(polygon.cutouts), 1)

    def test_disconnected_loops_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "disconnected"):
            polygon_from_loops(
                (
                    ((0, 0), (10, 0), (10, 10), (0, 10)),
                    ((20, 20), (21, 20), (21, 21), (20, 21)),
                )
            )

    def test_cutout_edge_crossing_concave_outer_loop_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the outer outline"):
            Polygon2D(
                (
                    (0, 0),
                    (10, 0),
                    (10, 10),
                    (6, 10),
                    (6, 4),
                    (4, 4),
                    (4, 10),
                    (0, 10),
                ),
                (
                    (
                        (3, 7),
                        (7, 7),
                        (7, 8),
                        (3, 8),
                    ),
                ),
            )

    def test_cutout_touching_outer_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the outer outline"):
            Polygon2D(
                ((0, 0), (10, 0), (10, 10), (0, 10)),
                (((0, 2), (4, 2), (4, 4), (0, 4)),),
            )

    def test_overlapping_cutouts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not intersect"):
            Polygon2D(
                ((0, 0), (20, 0), (20, 20), (0, 20)),
                (
                    ((2, 2), (10, 2), (10, 10), (2, 10)),
                    ((8, 8), (16, 8), (16, 16), (8, 16)),
                ),
            )

    def test_nested_cutouts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not intersect"):
            Polygon2D(
                ((0, 0), (20, 0), (20, 20), (0, 20)),
                (
                    ((2, 2), (18, 2), (18, 18), (2, 18)),
                    ((6, 6), (10, 6), (10, 10), (6, 10)),
                ),
            )

    def test_separate_cutouts_are_accepted(self):
        polygon = Polygon2D(
            ((0, 0), (20, 0), (20, 20), (0, 20)),
            (
                ((2, 2), (6, 2), (6, 6), (2, 6)),
                ((14, 14), (18, 14), (18, 18), (14, 18)),
            ),
        )

        self.assertEqual(polygon.area, 368)

    def test_signed_axis_normalization_preserves_orientation(self):
        normalization = AxisNormalization.from_signed_dimensions(-500, 300, -18)

        self.assertEqual(
            (normalization.length_mm, normalization.width_mm, normalization.thickness_mm),
            (500, 300, 18),
        )
        self.assertEqual(normalization.point(50, 20), Point2D(450, 20))
        self.assertEqual(normalization.signed_point(-50, 20), Point2D(50, 20))
        self.assertEqual(normalization.face("left"), "right")
        self.assertEqual(normalization.face("top"), "bottom")


if __name__ == "__main__":
    unittest.main()
