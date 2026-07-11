import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "WaveBend", "lib"))
import dxf_post  # noqa: E402


def dxf(header_vars="", entities=""):
    """Minimal but structurally valid DXF text."""
    return "\n".join(filter(None, [
        "  0", "SECTION", "  2", "HEADER",
        header_vars.strip("\n"),
        "  0", "ENDSEC",
        "  0", "SECTION", "  2", "ENTITIES",
        entities.strip("\n"),
        "  0", "ENDSEC",
        "  0", "EOF",
    ]))


LINE_CM = "\n".join(["  0", "LINE", " 10", "0.0", " 20", "0.0",
                     " 11", "10.0", " 21", "6.0"])
ARC_CM = "\n".join(["  0", "ARC", " 10", "5.0", " 20", "3.0",
                    " 40", "0.111", " 50", "90.0", " 51", "270.0"])
SPLINE_CM = "\n".join(["  0", "SPLINE", " 40", "0.0", " 40", "1.0",
                       " 10", "2.0", " 20", "1.5"])
INSUNITS_CM = "\n".join(["  9", "$INSUNITS", " 70", "     5"])


def pairs(text):
    lines = [l for l in text.splitlines() if l != ""]
    return [(lines[i].strip(), lines[i + 1].strip())
            for i in range(0, len(lines) - 1, 2)]


def value_after(text, entity, code):
    """First value of `code` inside `entity` in the ENTITIES section."""
    seen = False
    for c, v in pairs(text):
        if c == "0":
            seen = (v == entity)
        elif seen and c == str(code):
            return v
    return None


class TestToMm(unittest.TestCase):
    def test_line_coords_scaled(self):
        out, stats = dxf_post.to_mm(dxf(entities=LINE_CM), 10.0)
        self.assertEqual(float(value_after(out, "LINE", 11)), 100.0)
        self.assertEqual(float(value_after(out, "LINE", 21)), 60.0)
        self.assertEqual(stats.get("LINE"), 1)

    def test_arc_radius_scaled_angles_untouched(self):
        out, _ = dxf_post.to_mm(dxf(entities=ARC_CM), 10.0)
        self.assertAlmostEqual(float(value_after(out, "ARC", 40)), 1.11)
        self.assertEqual(float(value_after(out, "ARC", 50)), 90.0)
        self.assertEqual(float(value_after(out, "ARC", 51)), 270.0)

    def test_spline_knots_untouched_control_points_scaled(self):
        out, _ = dxf_post.to_mm(dxf(entities=SPLINE_CM), 10.0)
        self.assertEqual(float(value_after(out, "SPLINE", 40)), 0.0)  # knot, NOT scaled
        self.assertEqual(float(value_after(out, "SPLINE", 10)), 20.0)

    def test_declared_insunits_rewritten_to_mm(self):
        out, _ = dxf_post.to_mm(dxf(header_vars=INSUNITS_CM, entities=LINE_CM), 10.0)
        self.assertEqual(dxf_post.read_insunits(out), 4)

    def test_missing_insunits_inserted(self):
        src = dxf(entities=LINE_CM)
        self.assertIsNone(dxf_post.read_insunits(src))
        out, _ = dxf_post.to_mm(src, 10.0)
        self.assertEqual(dxf_post.read_insunits(out), 4)

    def test_extmin_scaled(self):
        hdr = "\n".join(["  9", "$EXTMIN", " 10", "0.0", " 20", "0.0",
                         "  9", "$EXTMAX", " 10", "10.0", " 20", "6.0"])
        out, _ = dxf_post.to_mm(dxf(header_vars=hdr, entities=LINE_CM), 10.0)
        found = [v for c, v in pairs(out) if c == "10"]
        self.assertIn("100.0", found)


class TestUnitDetection(unittest.TestCase):
    def test_read_insunits(self):
        self.assertEqual(dxf_post.read_insunits(dxf(header_vars=INSUNITS_CM)), 5)

    def test_scale_for_declared_units(self):
        self.assertEqual(dxf_post.scale_for_declared_units(5), 10.0)
        self.assertEqual(dxf_post.scale_for_declared_units(4), 1.0)
        self.assertAlmostEqual(dxf_post.scale_for_declared_units(1), 25.4)
        self.assertIsNone(dxf_post.scale_for_declared_units(None))
        self.assertIsNone(dxf_post.scale_for_declared_units(0))

    def test_infer_scale(self):
        # DXF says 10 wide, the face is really 100 mm -> cm file, factor 10
        self.assertEqual(dxf_post.infer_scale(10.0, 100.0), 10.0)
        # already mm
        self.assertEqual(dxf_post.infer_scale(100.0, 100.0), 1.0)
        # inches
        self.assertAlmostEqual(dxf_post.infer_scale(4.0, 101.6), 25.4)
        # nothing sane matches
        self.assertIsNone(dxf_post.infer_scale(7.0, 100.0))

    def test_extents_width(self):
        self.assertAlmostEqual(dxf_post.extents_width(dxf(entities=LINE_CM)), 10.0)


if __name__ == "__main__":
    unittest.main()
