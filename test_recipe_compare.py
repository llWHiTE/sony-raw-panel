from pathlib import Path
import tempfile
import unittest

from recipe_compare import RecipeParseError, recipe_fingerprint, recipes_equal


BASE = """<?xml version="1.0" encoding="utf-8"?>
<plist version="1.0">
  <dict>
    <key>DevelopmentParameters</key>
    <dict>
      <key>Adjuster</key>
      <dict><key>Exposure</key><integer>0</integer></dict>
      <key>Name</key><string>Studio recipe</string>
      <key>ToneCurve_Y</key>
      <dict><key>ToneCurve</key><dict>
        <key>ControlPoint0</key><dict><key>X</key><real>0,0000</real><key>Y</key><real>0.000</real></dict>
        <key>ControlPoint1</key><dict><key>X</key><real>1,0000</real><key>Y</key><real>1.000</real></dict>
        <key>ControlPointCount</key><integer>2</integer>
      </dict></dict>
    </dict>
    <key>UnrelatedTopLevelMetadata</key><string>ignored</string>
  </dict>
</plist>
"""

REORDERED_EQUIVALENT = """<plist version="1.0"><dict>
<key>UnrelatedTopLevelMetadata</key><string>different and irrelevant</string>
<key>DevelopmentParameters</key><dict>
  <key>ToneCurve_Y</key><dict><key>ToneCurve</key><dict>
    <key>ControlPointCount</key><integer>0002</integer>
    <key>ControlPoint1</key><dict><key>Y</key><real>1,0</real><key>X</key><real>1.000000</real></dict>
    <key>ControlPoint0</key><dict><key>Y</key><real>0,0</real><key>X</key><real>0.000000</real></dict>
  </dict></dict>
  <key>Name</key><string>Studio recipe</string>
  <key>Adjuster</key><dict><key>Exposure</key><integer>+000</integer></dict>
</dict></dict></plist>"""


class RecipeCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def recipe(self, name, contents):
        path = self.folder / name
        path.write_text(contents, encoding="utf-8")
        return path

    def test_ignores_xml_whitespace_dict_order_and_equivalent_real_spelling(self):
        base = self.recipe("base.xml", BASE)
        equivalent = self.recipe("equivalent.xml", REORDERED_EQUIVALENT)

        self.assertTrue(recipes_equal(base, equivalent))
        self.assertEqual(recipe_fingerprint(base), recipe_fingerprint(equivalent))

    def test_exposure_difference_is_not_equal(self):
        base = self.recipe("base.xml", BASE)
        changed = self.recipe("exposure.xml", BASE.replace("<integer>0</integer></dict>\n      <key>Name", "<integer>1</integer></dict>\n      <key>Name", 1))

        self.assertFalse(recipes_equal(base, changed))

    def test_nested_tone_curve_difference_is_not_equal(self):
        base = self.recipe("base.xml", BASE)
        changed = self.recipe("curve.xml", BASE.replace("<real>1.000</real>", "<real>0.875</real>"))

        self.assertFalse(recipes_equal(base, changed))

    def test_name_difference_is_not_equal(self):
        base = self.recipe("base.xml", BASE)
        changed = self.recipe("name.xml", BASE.replace("Studio recipe", "Outdoor recipe"))

        self.assertFalse(recipes_equal(base, changed))

    def test_missing_development_parameter_is_not_equal(self):
        base = self.recipe("base.xml", BASE)
        missing = self.recipe("missing.xml", BASE.replace("<key>Name</key><string>Studio recipe</string>", ""))

        self.assertFalse(recipes_equal(base, missing))

    def test_unknown_development_parameter_is_not_equal(self):
        base = self.recipe("base.xml", BASE)
        unknown = self.recipe("unknown.xml", BASE.replace("</dict>\n    <key>UnrelatedTopLevelMetadata", "<key>FutureSonyField</key><integer>7</integer></dict>\n    <key>UnrelatedTopLevelMetadata", 1))

        self.assertFalse(recipes_equal(base, unknown))

    def test_preserves_array_order_and_plist_types(self):
        base = self.recipe("base.xml", """<plist><dict><key>DevelopmentParameters</key><dict>
            <key>Values</key><array><integer>1</integer><real>2.0</real><true/></array>
        </dict></dict></plist>""")
        reordered = self.recipe("reordered.xml", """<plist><dict><key>DevelopmentParameters</key><dict>
            <key>Values</key><array><real>2.0</real><integer>1</integer><true/></array>
        </dict></dict></plist>""")
        changed_type = self.recipe("types.xml", """<plist><dict><key>DevelopmentParameters</key><dict>
            <key>Values</key><array><real>1.0</real><real>2.0</real><true/></array>
        </dict></dict></plist>""")

        self.assertFalse(recipes_equal(base, reordered))
        self.assertFalse(recipes_equal(base, changed_type))

    def test_malformed_recipe_raises(self):
        malformed = self.recipe("malformed.xml", "<plist><dict><key>DevelopmentParameters</key><dict></plist>")

        with self.assertRaises(RecipeParseError):
            recipe_fingerprint(malformed)

    def test_duplicate_dictionary_keys_raise(self):
        duplicate = self.recipe("duplicate.xml", """<plist><dict><key>DevelopmentParameters</key><dict>
            <key>Name</key><string>first</string><key>Name</key><string>second</string>
        </dict></dict></plist>""")

        with self.assertRaises(RecipeParseError):
            recipes_equal(duplicate, duplicate)


if __name__ == "__main__":
    unittest.main()
