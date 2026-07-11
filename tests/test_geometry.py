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
    def test_fillet_corner_raises_on_collinear(self):
        # collinear edges would hit tan(0)=0; must raise ValueError, not ZeroDivisionError
        with self.assertRaises(ValueError):
            G.fillet_corner(G.Pt(0, 0), G.Pt(1, 0), G.Pt(2, 0), 0.1)

class TestWaveCell(unittest.TestCase):
    # representative cm inputs: slot=0.65", gap=0.7*0.125", fillet=0.3*gap, diag=0.19"
    SLOT, GAP, FIL, DIAG = 1.651, 0.2222, 0.0667, 0.4826
    TH = math.radians(40.0)
    def test_closed_loop_of_12_segments(self):
        cell = G.build_wave_cell(self.SLOT, self.GAP, self.FIL)
        self.assertEqual(len(cell), 12)      # 6 lines + 2 caps + 4 knee fillets
        pts = G.sample_profile(cell, n=8)
        self.assertAlmostEqual(pts[0].x, pts[-1].x, places=6)
        self.assertAlmostEqual(pts[0].y, pts[-1].y, places=6)
    def test_smile_dimensions_match_swept_path(self):
        cell = G.build_wave_cell(self.SLOT, self.GAP, self.FIL)
        xmin, ymin, xmax, ymax = G._bbox(G.sample_profile(cell))
        exp_w = self.SLOT + 2 * self.DIAG * math.cos(self.TH) + self.GAP
        exp_h = self.DIAG * math.sin(self.TH) + self.GAP
        self.assertAlmostEqual(xmax - xmin, exp_w, delta=0.02)
        self.assertAlmostEqual(ymax - ymin, exp_h, delta=0.02)
        # the horizontal run sits ON the bend line: lower edge exactly at -gap/2
        self.assertAlmostEqual(ymin, -self.GAP / 2, places=6)
        # smile: swept ends rise well above the horizontal
        self.assertGreater(ymax, self.DIAG * math.sin(self.TH) * 0.9)
    def test_frown_is_exact_mirror_of_smile(self):
        s = G._bbox(G.sample_profile(G.build_wave_cell(self.SLOT, self.GAP, self.FIL, orient=+1)))
        f = G._bbox(G.sample_profile(G.build_wave_cell(self.SLOT, self.GAP, self.FIL, orient=-1)))
        self.assertAlmostEqual(s[3], -f[1], places=6)    # ymax_smile == -ymin_frown
        self.assertAlmostEqual(s[1], -f[3], places=6)    # ymin_smile == -ymax_frown
        self.assertAlmostEqual(s[0], f[0], places=6)     # same x extent
        self.assertAlmostEqual(s[2], f[2], places=6)
    def test_cell_translated_to_center(self):
        cell = G.build_wave_cell(self.SLOT, self.GAP, self.FIL, cx=3.0, cy=-2.0)
        xmin, _, xmax, _ = G._bbox(G.sample_profile(cell))
        self.assertAlmostEqual((xmin + xmax) / 2, 3.0, delta=0.01)
    def test_no_degenerate_line_segments(self):
        cell = G.build_wave_cell(self.SLOT, self.GAP, self.FIL)
        for seg in cell:
            if seg[0] == "line":
                _, p0, p1 = seg
                self.assertGreater(G.v_len(G.v_sub(p1, p0)), 1e-4)
    def test_raises_on_nonpositive_fillet(self):
        with self.assertRaises(ValueError):
            G.build_wave_cell(self.SLOT, self.GAP, 0.0)   # sharp corners crack
    def test_raises_when_fillet_too_large(self):
        with self.assertRaises(ValueError):
            G.build_wave_cell(self.SLOT, self.GAP, 5.0)   # no room on any edge

class TestTessellation(unittest.TestCase):
    # representative cm inputs: t=0.3175 (0.125"), gap=0.7t, tab=t, fillet=0.3*gap
    T = 0.3175
    GAP = 0.3175 * 0.7
    TAB = 0.3175
    FIL = (0.3175 * 0.7) * 0.3
    def test_solve_pitch_feasible_and_near_reference(self):
        p = G.solve_pitch(1.651, self.GAP, self.TAB, self.FIL, 40.0)
        self.assertGreater(p, 0.0)
        # the SendCutSend reference runs ~1.0 in (2.54 cm) per-slot at comparable inputs
        self.assertLess(abs(p - 2.54), 0.5)
    def test_solve_pitch_large_tab_is_feasible(self):
        # A large tab just spreads the chain out; it is NOT infeasible.
        p = G.solve_pitch(1.0, 0.1, 0.8, 0.02, 40.0)   # tab = 0.8 * slot_len
        self.assertGreater(p, 0.0)
    def test_solve_pitch_propagates_degenerate_cell(self):
        # nonpositive fillet makes build_wave_cell raise; solve_pitch must surface it.
        with self.assertRaises(ValueError):
            G.solve_pitch(1.651, self.GAP, self.TAB, 0.0, 40.0)
    def test_pattern_honors_no_ligament_below_tab(self):
        out = G.generate_pattern(12.0, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        self.assertGreaterEqual(out["min_ligament"], self.TAB - 1e-3)
        self.assertGreater(out["count"], 1)
    def test_pattern_alternates_smile_frown(self):
        out = G.generate_pattern(12.0, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        rise = 0.4826 * math.sin(math.radians(40.0)) * 0.5
        for i, prof in enumerate(out["profiles"]):
            _, ymin, _, ymax = G._bbox(G.sample_profile(prof, n=6))
            if i % 2 == 0:
                self.assertGreater(ymax, rise)     # smile: ends rise
            else:
                self.assertLess(ymin, -rise)       # frown: ends fall
    def test_pattern_is_centered_on_bend_line(self):
        # horizontal edges of every slot sit ON the line: each profile's near edge at +-gap/2
        out = G.generate_pattern(12.0, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        for i, prof in enumerate(out["profiles"]):
            _, ymin, _, ymax = G._bbox(G.sample_profile(prof, n=6))
            if i % 2 == 0:
                self.assertAlmostEqual(ymin, -self.GAP / 2, places=6)
            else:
                self.assertAlmostEqual(ymax, +self.GAP / 2, places=6)
    def test_pattern_within_bend_length(self):
        B = 10.0
        out = G.generate_pattern(B, self.GAP, self.TAB, 1.651, self.FIL, 40.0)
        for prof in out["profiles"]:
            for p in G.sample_profile(prof):
                self.assertGreaterEqual(p.x, -1e-6)
                self.assertLessEqual(p.x, B + 1e-6)
    def test_fit_count_and_fit_slot_len_roundtrip(self):
        p = G.solve_pitch(1.651, self.GAP, self.TAB, self.FIL, 40.0)
        n = G.fit_count(10.0, p, margin=p / 2)
        self.assertGreaterEqual(n, 1)
    def test_fit_slot_len_raises_when_count_cannot_fit(self):
        # asking for 10000 slots in a 10 cm bend needs a pitch far below the achievable
        # minimum -> genuinely infeasible
        with self.assertRaises(ValueError):
            G.fit_slot_len(10.0, 10000, self.GAP, self.TAB, self.FIL, 40.0, margin=0.0)
    def test_generate_pattern_raises_when_no_cells_fit(self):
        # bend shorter than one slot width -> zero cells; must raise, not return inf/empty
        with self.assertRaises(ValueError):
            G.generate_pattern(0.3, self.GAP, self.TAB, 1.651, self.FIL, 40.0)

class TestDistanceAndFillet(unittest.TestCase):
    def _line(self, p, q):
        return ("line", G.Pt(*p), G.Pt(*q))
    def test_min_profile_distance_is_symmetric_vertex_to_edge(self):
        # B's apex vertex sits at x=5.4 (between A's edge samples), 1.0 below A's long
        # bottom edge. A one-sided A->B scan over-reports (~1.08); the true minimum is the
        # perpendicular 1.0 found only by also checking B-points against A-segments.
        A = [self._line((0, 0), (10, 0)), self._line((10, 0), (10, 0.1)),
             self._line((10, 0.1), (0, 0.1)), self._line((0, 0.1), (0, 0))]
        B = [self._line((5.4, -1), (4.9, -2)), self._line((4.9, -2), (5.9, -2)),
             self._line((5.9, -2), (5.4, -1))]
        self.assertAlmostEqual(G.min_profile_distance([A, B]), 1.0, delta=0.02)
        self.assertAlmostEqual(G.min_profile_distance([A, B]),
                               G.min_profile_distance([B, A]), places=6)  # order-independent


class TestPatternStyles(unittest.TestCase):
    """Every style must produce closed, arc-consistent loops and tab-safe chains."""
    SLOT, GAP, TAB, FIL = 1.651, 0.2223, 0.3175, 0.0667
    BEND = 6.0

    def _assert_closed(self, profile, tol=1e-7):
        for i, seg in enumerate(profile):
            p_end = seg[2] if seg[0] == "line" else seg[6]
            nxt = profile[(i + 1) % len(profile)]
            p_start = nxt[1] if nxt[0] == "line" else nxt[5]
            d = math.hypot(p_end.x - p_start.x, p_end.y - p_start.y)
            self.assertLess(d, tol, f"open loop between segments {i} and {i + 1}")

    def _assert_arcs_consistent(self, profile, tol=1e-6):
        for i, seg in enumerate(profile):
            if seg[0] != "arc":
                continue
            _, c, r, a0, a1, p0, p1 = seg
            e0 = math.hypot(c.x + r * math.cos(a0) - p0.x, c.y + r * math.sin(a0) - p0.y)
            e1 = math.hypot(c.x + r * math.cos(a1) - p1.x, c.y + r * math.sin(a1) - p1.y)
            self.assertLess(e0, tol, f"arc {i}: start point off circle")
            self.assertLess(e1, tol, f"arc {i}: end point off circle")

    def test_every_style_closed_and_consistent(self):
        for style in G.PATTERN_STYLES:
            for orient in (+1, -1):
                cell = G.build_cell(style, self.SLOT, self.GAP, self.FIL,
                                    orient=orient, cx=1.5, cy=-0.7)
                self._assert_closed(cell)
                self._assert_arcs_consistent(cell)

    def test_every_style_pattern_respects_tab(self):
        for style in G.PATTERN_STYLES:
            pat = G.generate_pattern(self.BEND, self.GAP, self.TAB, self.SLOT,
                                     self.FIL, style=style)
            self.assertGreaterEqual(pat["count"], 1, style)
            self.assertEqual(pat["style"], style)
            if pat["count"] > 1:
                self.assertGreaterEqual(pat["min_ligament"], self.TAB - 1e-6, style)

    def test_alternating_styles_flip_orientation(self):
        # Consecutive wave/zigzag/serpentine cells mirror in v: their bboxes'
        # v-extents must differ; slot/diamond repeat identically.
        for style in G.PATTERN_STYLES:
            pat = G.generate_pattern(self.BEND, self.GAP, self.TAB, self.SLOT,
                                     self.FIL, style=style)
            if pat["count"] < 2:
                continue
            b0 = G._bbox(G.sample_profile(pat["profiles"][0]))
            b1 = G._bbox(G.sample_profile(pat["profiles"][1]))
            if G.style_alternates(style):
                self.assertAlmostEqual(b0[1], -b1[3], places=6, msg=style)
            else:
                self.assertAlmostEqual(b0[1], b1[1], places=6, msg=style)
                self.assertAlmostEqual(b0[3], b1[3], places=6, msg=style)

    def test_cells_center_on_bend_line(self):
        # Every style's cell must straddle v=0 (the bend line runs through it).
        for style in G.PATTERN_STYLES:
            cell = G.build_cell(style, self.SLOT, self.GAP, self.FIL)
            _, ymin, _, ymax = G._bbox(G.sample_profile(cell))
            self.assertLess(ymin, 0.0, style)
            self.assertGreater(ymax, 0.0, style)

    def test_slot_cell_dimensions(self):
        cell = G.build_slot_cell(self.SLOT, self.GAP)
        xmin, ymin, xmax, ymax = G._bbox(G.sample_profile(cell))
        self.assertAlmostEqual(xmax - xmin, self.SLOT, places=6)
        self.assertAlmostEqual(ymax - ymin, self.GAP, places=6)

    def test_diamond_cell_dimensions(self):
        cell = G.build_diamond_cell(self.SLOT, self.GAP, self.FIL)
        xmin, ymin, xmax, ymax = G._bbox(G.sample_profile(cell))
        self.assertAlmostEqual(ymax - ymin, 2.0 * self.GAP, delta=0.01)
        self.assertLessEqual(xmax - xmin, self.SLOT + 1e-9)   # fillets pull the tips in

    def test_infeasible_inputs_raise(self):
        with self.assertRaises(ValueError):
            G.build_slot_cell(self.GAP, self.GAP)              # too short for a pill
        with self.assertRaises(ValueError):
            G.build_serpentine_cell(1.9 * self.GAP, self.GAP)  # lobes would vanish
        with self.assertRaises(ValueError):
            G.build_diamond_cell(self.SLOT, self.GAP, self.GAP * 3)  # fillet > tips
        with self.assertRaises(ValueError):
            G.build_cell('nonsense', self.SLOT, self.GAP, self.FIL)

    def test_cell_halfwidth_matches_probe(self):
        for style in G.PATTERN_STYLES:
            hw = G.cell_halfwidth(style, self.SLOT, self.GAP, self.FIL)
            xmin, _, xmax, _ = G._bbox(G.sample_profile(
                G.build_cell(style, self.SLOT, self.GAP, self.FIL)))
            self.assertAlmostEqual(hw, (xmax - xmin) / 2.0, delta=0.02, msg=style)


if __name__ == "__main__":
    unittest.main()
