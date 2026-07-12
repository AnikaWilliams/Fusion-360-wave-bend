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


class TestStyleGapFloors(unittest.TestCase):
    """Research kerf floors (docs/pattern-research.md): curved styles keep the
    family multiplier; dogbone floors at 0.7 t; straight-slot styles at 1.0 t."""
    T = 0.3175

    def test_curved_styles_keep_family_multiplier(self):
        for style in ("wave", "crescent", "serpentine", "zigzag"):
            self.assertAlmostEqual(
                config.default_gap_cm(self.T, "Aluminum", style=style),
                self.T * 0.6, places=9, msg=style)

    def test_dogbone_floor_raises_aluminum_only(self):
        self.assertAlmostEqual(config.default_gap_cm(self.T, "Aluminum", style="dogbone"),
                               self.T * 0.7, places=9)
        self.assertAlmostEqual(config.default_gap_cm(self.T, "Mild Steel", style="dogbone"),
                               self.T * 0.7, places=9)

    def test_straight_slot_styles_floor_at_full_thickness(self):
        for style in ("stagger", "slot", "meander", "diamond"):
            for family in ("Aluminum", "Mild Steel", "Stainless Steel"):
                self.assertAlmostEqual(
                    config.default_gap_cm(self.T, family, style=style),
                    self.T * 1.0, places=9, msg=f"{style}/{family}")

    def test_default_style_is_backward_compatible(self):
        self.assertAlmostEqual(config.default_gap_cm(self.T, "Aluminum"),
                               self.T * 0.6, places=9)


if __name__ == "__main__":
    unittest.main()
