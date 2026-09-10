import unittest

from src.adapters.unit_resolver import (
    UnitResolutionStatus,
    UnitResolver,
    normalize_unit_name,
)


class TestUnitResolver(unittest.TestCase):
    def setUp(self):
        self.units = {
            "Multi": ["Apt 3", "04", "C1", "D10"],
            "Single": [""],
            "SingleNamed": ["Main"],
            "Ambiguous": ["03", "3"],
        }
        self.resolver = UnitResolver(self.units)

    def test_normalization_cascade(self):
        self.assertEqual(normalize_unit_name(" Apt 03 "), "3")
        self.assertEqual(normalize_unit_name("UNIT c1"), "C1")
        self.assertEqual(normalize_unit_name("# D10"), "D10")
        self.assertEqual(normalize_unit_name("Ste  04"), "4")

    def test_exact_unit(self):
        result = self.resolver.resolve("Multi", "C1")
        self.assertEqual(result.status, UnitResolutionStatus.EXACT_UNIT)
        self.assertEqual(result.canonical_unit_name, "C1")

    def test_normalized_unit(self):
        result = self.resolver.resolve("Multi", "#03")
        self.assertEqual(result.status, UnitResolutionStatus.NORMALIZED_UNIT)
        self.assertEqual(result.canonical_unit_name, "Apt 3")

    def test_numeric_leading_zero_normalization(self):
        result = self.resolver.resolve("Multi", "4")
        self.assertEqual(result.status, UnitResolutionStatus.NORMALIZED_UNIT)
        self.assertEqual(result.canonical_unit_name, "04")

    def test_property_only_single_unit_blank(self):
        result = self.resolver.resolve("Single", "HSE")
        self.assertEqual(result.status, UnitResolutionStatus.PROPERTY_ONLY_SINGLE_UNIT)
        self.assertEqual(result.canonical_unit_name, "")

    def test_property_only_single_named_unit(self):
        result = self.resolver.resolve("SingleNamed", "legacy")
        self.assertEqual(result.status, UnitResolutionStatus.PROPERTY_ONLY_SINGLE_UNIT)
        self.assertEqual(result.canonical_unit_name, "Main")

    def test_unresolved_multi_unit(self):
        result = self.resolver.resolve("Multi", "99")
        self.assertEqual(result.status, UnitResolutionStatus.UNRESOLVED)

    def test_ambiguous_normalized_unit(self):
        result = self.resolver.resolve("Ambiguous", "003")
        self.assertEqual(result.status, UnitResolutionStatus.AMBIGUOUS)

    def test_explicit_alias_status_is_resolved(self):
        result = UnitResolver.from_explicit_alias("HSE", "C1")
        self.assertEqual(result.status, UnitResolutionStatus.EXPLICIT_ALIAS)
        self.assertEqual(result.canonical_unit_name, "C1")
        self.assertTrue(result.resolved)



if __name__ == "__main__":
    unittest.main()
