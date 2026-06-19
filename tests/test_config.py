import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "WaveBend"))
import config

class TestConfig(unittest.TestCase):
    def test_multiplier_aluminum(self):
        self.assertAlmostEqual(config.gap_multiplier_for("Aluminum 6061"), 0.6)
    def test_multiplier_steel_and_titanium(self):
        self.assertAlmostEqual(config.gap_multiplier_for("Stainless Steel"), 0.7)
        self.assertAlmostEqual(config.gap_multiplier_for("Titanium"), 0.7)
    def test_multiplier_unknown_defaults_06(self):
        self.assertAlmostEqual(config.gap_multiplier_for("Acrylic"), 0.6)
    def test_default_gap_uses_multiplier(self):
        # t = 0.3175 cm (0.125 in), steel -> 0.7
        self.assertAlmostEqual(config.default_gap_cm(0.3175, "Mild Steel"), 0.3175 * 0.7)
    def test_default_tab_equals_thickness(self):
        self.assertAlmostEqual(config.default_tab_cm(0.3175), 0.3175)
    def test_default_fillet_is_half_gap(self):
        self.assertAlmostEqual(config.default_fillet_cm(0.2), 0.1)

if __name__ == "__main__":
    unittest.main()
