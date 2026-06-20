import os, sys, math, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "WaveBend", "lib"))
import geometry as G

class TestPrimitives(unittest.TestCase):
    def test_unit_length(self):
        u = G.v_unit(G.Pt(3, 4))
        self.assertAlmostEqual(G.v_len(u), 1.0)
        self.assertAlmostEqual(u.x, 0.6); self.assertAlmostEqual(u.y, 0.8)
    def test_point_seg_distance_midpoint(self):
        d = G.point_seg_distance(G.Pt(0, 1), G.Pt(-1, 0), G.Pt(1, 0))
        self.assertAlmostEqual(d, 1.0)
    def test_point_seg_distance_past_end(self):
        d = G.point_seg_distance(G.Pt(2, 0), G.Pt(-1, 0), G.Pt(1, 0))
        self.assertAlmostEqual(d, 1.0)   # clamped to endpoint (1,0)
    def test_sample_line_endpoints(self):
        pts = G.sample_segment(("line", G.Pt(0, 0), G.Pt(1, 0)), n=4)
        self.assertEqual(len(pts), 5)
        self.assertAlmostEqual(pts[-1].x, 1.0)
    def test_min_profile_distance_two_squares(self):
        def sq(cx):
            c = [G.Pt(cx-0.5, -0.5), G.Pt(cx+0.5, -0.5), G.Pt(cx+0.5, 0.5), G.Pt(cx-0.5, 0.5)]
            return [("line", c[i], c[(i+1) % 4]) for i in range(4)]
        self.assertAlmostEqual(G.min_profile_distance([sq(0), sq(2.0)], n=8), 1.0, places=3)

class TestFillet(unittest.TestCase):
    def _dist_pt_to_line(self, p, a, d):       # perpendicular dist, d unit dir
        ap = G.v_sub(p, a)
        return abs(ap.x * d.y - ap.y * d.x)
    def test_fillet_is_tangent_to_both_edges(self):
        A = G.Pt(-1, 0); B = G.Pt(0, 0); C = G.Pt(0, 1)   # right-angle corner
        T1, T2, c, a0, a1, t = G.fillet_corner(A, B, C, 0.1)
        d1 = self._dist_pt_to_line(c, B, G.v_unit(G.v_sub(A, B)))
        d2 = self._dist_pt_to_line(c, B, G.v_unit(G.v_sub(C, B)))
        self.assertAlmostEqual(d1, 0.1, places=6)
        self.assertAlmostEqual(d2, 0.1, places=6)
    def test_filleted_square_is_closed(self):
        verts = [G.Pt(-1, -1), G.Pt(1, -1), G.Pt(1, 1), G.Pt(-1, 1)]
        segs = G.filleted_polygon(verts, 0.2)
        self.assertEqual(len(segs), 8)                    # 4 arcs + 4 lines
        pts = G.sample_profile(segs, n=6)
        # closed: last sampled point coincides with first
        self.assertAlmostEqual(pts[0].x, pts[-1].x, places=6)
        self.assertAlmostEqual(pts[0].y, pts[-1].y, places=6)

class TestCell(unittest.TestCase):
    def test_cell_height_equals_gap_and_width_under_slotlen(self):
        cell = G.build_cell(1.651, 0.1905, 0.05, 40.0)   # cm: 0.65in, 0.075in, ~0.02in
        pts = G.sample_profile(cell)
        xmin, ymin, xmax, ymax = G._bbox(pts)
        self.assertAlmostEqual(ymax - ymin, 0.1905, places=3)        # height == gap
        self.assertLessEqual(xmax - xmin, 1.651 + 1e-6)              # width <= slot_len
        self.assertGreater(xmax - xmin, 1.651 - 4 * 0.05)           # not collapsed
    def test_cell_centered(self):
        cell = G.build_cell(1.651, 0.1905, 0.05, 40.0, cx=3.0, cy=-2.0)
        pts = G.sample_profile(cell)
        xmin, ymin, xmax, ymax = G._bbox(pts)
        self.assertAlmostEqual((xmin + xmax) / 2, 3.0, places=3)
        self.assertAlmostEqual((ymin + ymax) / 2, -2.0, places=3)
    def test_cell_raises_when_too_short(self):
        with self.assertRaises(ValueError):
            G.build_cell(0.2, 0.19, 0.2, 40.0)            # fillet bigger than the flat
    def test_cell_raises_when_fillet_ge_half_gap(self):
        # fillet == gap/2 collapses the angled ends to zero-length segments
        with self.assertRaises(ValueError):
            G.build_cell(1.651, 0.2222, 0.1111, 40.0)     # fillet == gap/2 exactly
        with self.assertRaises(ValueError):
            G.build_cell(1.651, 0.2222, 0.15, 40.0)       # fillet > gap/2
    def test_cell_has_no_degenerate_line_segments(self):
        # a valid cell (fillet < gap/2) must have only positive-length straight edges
        cell = G.build_cell(1.651, 0.2222, 0.2222 * 0.3, 40.0)
        for seg in cell:
            if seg[0] == "line":
                _, p0, p1 = seg
                self.assertGreater(G.v_len(G.v_sub(p1, p0)), 1e-4)

class TestTessellation(unittest.TestCase):
    # representative cm inputs: t=0.3175 (0.125"), gap=0.7t, tab=t, fillet=0.3*gap
    # (fillet must stay < gap/2 or the cell ends degenerate — see TestCell)
    T = 0.3175
    GAP = 0.3175 * 0.7
    TAB = 0.3175
    FIL = (0.3175 * 0.7) * 0.3
    def test_solve_pitch_feasible(self):
        p = G.solve_pitch(1.651, self.GAP, self.TAB, self.FIL, 40.0)
        self.assertGreater(p, 0.0)
    def test_solve_pitch_raises_when_tab_too_large(self):
        with self.assertRaises(ValueError):
            G.solve_pitch(1.651, self.GAP, 5.0, self.FIL, 40.0)   # absurd tab
    def test_pattern_honors_no_ligament_below_tab(self):
        out = G.generate_pattern(10.0, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        self.assertGreaterEqual(out["min_ligament"], self.TAB - 1e-3)
        self.assertAlmostEqual(out["central_tab"], self.TAB, places=4)
        self.assertGreater(out["count"], 1)
    def test_pattern_within_bend_length(self):
        B = 8.0
        out = G.generate_pattern(B, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        for prof in out["profiles"]:
            for p in G.sample_profile(prof):
                self.assertGreaterEqual(p.x, -1e-6)
                self.assertLessEqual(p.x, B + 1e-6)
    def test_fit_count_and_fit_slot_len_roundtrip(self):
        p = G.solve_pitch(1.651, self.GAP, self.TAB, self.FIL, 40.0)
        n = G.fit_count(10.0, p, margin=p / 2)
        self.assertGreaterEqual(n, 1)
    def test_fit_slot_len_raises_when_infeasible(self):
        # tab=10.0 cm is absurdly large; no slot_len can yield a feasible pitch
        with self.assertRaises(ValueError):
            G.fit_slot_len(10.0, 3, self.GAP, 10.0, self.FIL, 40.0, margin=0.0)

if __name__ == "__main__":
    unittest.main()
