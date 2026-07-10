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
    def test_default_fillet_below_half_gap(self):
        # must be < gap/2 (else the angled cell ends collapse); 0.3*gap
        self.assertAlmostEqual(config.default_fillet_cm(0.2), 0.06)
        self.assertLess(config.default_fillet_cm(0.2), 0.2 / 2.0)

class TestMaterialFamily(unittest.TestCase):
    def test_family_words(self):
        self.assertEqual(config.material_family("Aluminum 6061"), config.FAMILY_ALUMINUM)
        self.assertEqual(config.material_family("Stainless Steel"), config.FAMILY_STAINLESS)
        self.assertEqual(config.material_family("Steel"), config.FAMILY_MILD_STEEL)
        self.assertEqual(config.material_family("Titanium"), config.FAMILY_TITANIUM)
    def test_alloy_hints_from_sheetmetal_rule_names(self):
        # rule names often carry only the alloy, e.g. Fusion's '.063" 5052'
        self.assertEqual(config.material_family('.063" 5052'), config.FAMILY_ALUMINUM)
        self.assertEqual(config.material_family("2mm 304"), config.FAMILY_STAINLESS)
        self.assertEqual(config.material_family("Ti-6Al-4V"), config.FAMILY_TITANIUM)
    def test_stainless_wins_over_steel_and_family_over_alloy(self):
        self.assertEqual(config.material_family("Stainless Steel 5052-ish"),
                         config.FAMILY_STAINLESS)
    def test_unrecognized_returns_none(self):
        self.assertIsNone(config.material_family("Acrylic"))
        self.assertIsNone(config.material_family(""))
        self.assertIsNone(config.material_family(None))

if __name__ == "__main__":
    unittest.main()
