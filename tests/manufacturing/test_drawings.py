from __future__ import annotations

import binascii
from pathlib import Path
import re
import struct
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zlib

from manufacturing.drawings import (
    SVG_NAMESPACE,
    UnsupportedPanelGeometry,
    collect_unique_panels,
    export_drawing_package,
    render_panel_svg,
    write_png_pdf,
)
from manufacturing.model import IssueSeverity, ValidationIssue

from .drawing_fixtures import make_part, make_project, required_panel_parts


GOLDEN_DIRECTORY = Path(__file__).with_name("golden")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _rgb_png(width: int = 2, height: int = 1) -> bytes:
    pixels = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + _png_chunk(b"IDAT", zlib.compress(pixels))
        + _png_chunk(b"IEND", b"")
    )


class DrawingTests(unittest.TestCase):
    def test_required_panel_matrix_and_duplicate_quantities(self):
        project = make_project(required_panel_parts())
        panels = collect_unique_panels(project)

        self.assertEqual(len(project.parts), 9)
        self.assertEqual(len(panels), 8)
        self.assertEqual([panel.part.id for panel in panels], sorted(
            panel.part.id for panel in panels
        ))
        rectangular = panels[0]
        self.assertEqual(rectangular.part.id, "part-01-rectangular")
        self.assertEqual(rectangular.quantity, 5)
        self.assertEqual(
            rectangular.part_ids,
            ("part-01-rectangular", "part-02-duplicate"),
        )
        self.assertEqual(rectangular.cabinet_names, ("Cabinet A", "Cabinet B"))

    def test_svg_xml_dimensions_labels_shapes_and_operations(self):
        panels = collect_unique_panels(make_project(required_panel_parts()))
        documents = {
            panel.part.id: ET.fromstring(render_panel_svg(panel))
            for panel in panels
        }
        namespace = {"svg": SVG_NAMESPACE}
        for panel in panels:
            with self.subTest(part=panel.part.id):
                root = documents[panel.part.id]
                self.assertEqual(root.tag, f"{{{SVG_NAMESPACE}}}svg")
                self.assertEqual(root.attrib["width"], "297mm")
                self.assertEqual(root.attrib["height"], "210mm")
                self.assertEqual(
                    float(root.attrib["data-length-mm"]),
                    panel.part.length_mm,
                )
                self.assertEqual(
                    float(root.attrib["data-width-mm"]),
                    panel.part.width_mm,
                )
                text = " ".join(root.itertext())
                self.assertIn(f"Part ID: {panel.part.id}", text)
                self.assertIn("Material: White Melamine", text)
                self.assertIn("Thickness: 18 mm", text)
                self.assertIn("FRONT EDGE:", text)
                self.assertIn("BACK EDGE:", text)
                self.assertIn("LEFT:", text)
                self.assertIn("RIGHT:", text)
                self.assertIn("VALIDATION NOTES", text)
                self.assertIsNotNone(root.find("svg:title", namespace))

        drilled = documents["part-03-drilled"]
        classes = " ".join(
            element.attrib.get("class", "")
            for element in drilled.iter()
        )
        self.assertIn("operation-through_hole", classes)
        self.assertIn("operation-blind_hole", classes)
        self.assertIn("operation-line_bore", classes)
        grooved_classes = " ".join(
            element.attrib.get("class", "")
            for element in documents["part-04-grooved"].iter()
        )
        self.assertIn("operation-groove", grooved_classes)
        pocketed_classes = " ".join(
            element.attrib.get("class", "")
            for element in documents["part-05-pocketed"].iter()
        )
        self.assertIn("operation-pocket", pocketed_classes)
        self.assertIn("operation-contour_cutout", pocketed_classes)
        self.assertIsNotNone(
            documents["part-05-pocketed"].find(
                ".//svg:polygon[@id='panel-cutout-1']",
                namespace,
            )
        )

        curved_points = documents["part-08-curved"].find(
            ".//svg:polygon[@id='panel-outline']",
            namespace,
        ).attrib["points"]
        self.assertEqual(len(curved_points.split()), 7)
        notched_points = documents["part-06-notched"].find(
            ".//svg:polygon[@id='panel-outline']",
            namespace,
        ).attrib["points"]
        mirrored_points = documents["part-07-mirrored"].find(
            ".//svg:polygon[@id='panel-outline']",
            namespace,
        ).attrib["points"]
        self.assertNotEqual(notched_points, mirrored_points)
        self.assertIn(
            "GRAIN - WIDTH",
            " ".join(documents["part-09-grain-width"].itertext()),
        )

    def test_package_filenames_pdf_index_and_outputs_are_deterministic(self):
        project = make_project(required_panel_parts())
        with tempfile.TemporaryDirectory() as first_root, tempfile.TemporaryDirectory() as second_root:
            first = export_drawing_package(project, first_root)
            second = export_drawing_package(
                make_project(tuple(reversed(required_panel_parts()))),
                second_root,
            )

            expected_stems = tuple(panel.filename_stem for panel in first.panels)
            self.assertEqual(
                tuple(path.stem for path in first.svg_paths),
                expected_stems,
            )
            self.assertEqual(
                tuple(path.stem for path in first.dxf_paths),
                expected_stems,
            )
            self.assertEqual(
                tuple(path.name for path in first.svg_paths),
                tuple(path.name for path in second.svg_paths),
            )
            self.assertEqual(
                tuple(path.read_bytes() for path in first.svg_paths),
                tuple(path.read_bytes() for path in second.svg_paths),
            )
            self.assertEqual(
                tuple(path.read_bytes() for path in first.dxf_paths),
                tuple(path.read_bytes() for path in second.dxf_paths),
            )
            self.assertEqual(
                first.booklet_path.read_bytes(),
                second.booklet_path.read_bytes(),
            )

            pdf = first.booklet_path.read_bytes()
            self.assertEqual(first.page_count, 9)
            self.assertEqual(len(re.findall(rb"/Type /Page\b", pdf)), 9)
            self.assertIn(b"MANUFACTURING DRAWING INDEX", pdf)
            self.assertIn(b"part-01-rectangular", pdf)
            self.assertIn(b"Quantity: 5", pdf)
            self.assertIn(b"White Melamine", pdf)
            self.assertTrue(pdf.endswith(b"%%EOF\n"))

    def test_unsupported_panel_fails_before_creating_package(self):
        unsupported = make_part(
            "part-unsupported",
            "Unsupported",
            issues=(
                ValidationIssue(
                    IssueSeverity.WARNING,
                    "extractor.outline_fallback",
                    "Boundary extraction failed",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "not-created"
            with self.assertRaises(UnsupportedPanelGeometry):
                export_drawing_package(make_project((unsupported,)), destination)
            self.assertFalse(destination.exists())

    def test_small_svg_and_dxf_golden_files(self):
        panel = collect_unique_panels(
            make_project((make_part("golden-panel", "Golden Panel"),))
        )[0]
        svg = render_panel_svg(panel, page_number=2, total_pages=2)
        self.assertEqual(
            svg,
            (GOLDEN_DIRECTORY / "golden-panel.svg").read_text(encoding="utf-8"),
        )
        from manufacturing.dxf import render_part_dxf

        self.assertEqual(
            render_part_dxf(panel.part),
            (GOLDEN_DIRECTORY / "golden-panel.dxf").read_text(encoding="ascii"),
        )

    def test_blender_png_pdf_writer_is_dependency_free_and_multipage(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            image_a = root_path / "a.png"
            image_b = root_path / "b.png"
            image_a.write_bytes(_rgb_png())
            image_b.write_bytes(_rgb_png(1, 2))
            output = write_png_pdf(
                (image_a, image_b),
                root_path / "views.pdf",
                title="Assembly Views",
                page_width_points=792,
                page_height_points=612,
            )
            pdf = output.read_bytes()

        self.assertEqual(len(re.findall(rb"/Type /Page\b", pdf)), 2)
        self.assertEqual(pdf.count(b"/Subtype /Image"), 2)
        self.assertIn(b"/Predictor 15", pdf)
        self.assertIn(b"Assembly Views", pdf)


if __name__ == "__main__":
    unittest.main()
