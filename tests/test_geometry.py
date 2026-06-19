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

if __name__ == "__main__":
    unittest.main()
