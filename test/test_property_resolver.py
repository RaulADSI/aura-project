import unittest

from src.adapters.property_resolver import (
    PropertyResolutionStatus,
    PropertyResolver,
)


class TestPropertyResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = PropertyResolver(
            [
                "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
                "-> 1352 North Ave - 1352 North Ave Atlanta, GA 30307",
                "-> Waters Edge Apartments - 417 Barton Drive Forest Park, GA 30297",
                "-> Polaris At Cumming - 1006 Tribble Gap Road Cumming, GA 30040",
            ]
        )

    def test_exact_normalized_alias(self):
        result = self.resolver.resolve("1414 Euclid Ave")
        self.assertEqual(result.status, PropertyResolutionStatus.EXACT_NORMALIZED)
        self.assertTrue(result.resolved)
        self.assertIn("1414 Euclid Ave", result.canonical_property_name)

    def test_address_component_match_ignores_direction_and_locality(self):
        result = self.resolver.resolve("1414 EUCLID AVE NE, ATLANTA GA")
        self.assertEqual(result.status, PropertyResolutionStatus.ADDRESS_COMPONENT_MATCH)
        self.assertIn("1414 Euclid Ave", result.canonical_property_name)

    def test_address_component_match_handles_street_type_expansion(self):
        result = self.resolver.resolve("417 BARTON DR, ATLANTA GA")
        self.assertEqual(result.status, PropertyResolutionStatus.ADDRESS_COMPONENT_MATCH)
        self.assertIn("Waters Edge Apartments", result.canonical_property_name)

    def test_input_alias_segment_can_match_property_name(self):
        result = self.resolver.resolve(
            "Polaris At Cumming; 1006 Tribble Rd; Cumming GA 30040-2254"
        )
        self.assertEqual(result.status, PropertyResolutionStatus.EXACT_NORMALIZED)
        self.assertIn("Polaris At Cumming", result.canonical_property_name)

    def test_unresolved_is_not_guessed(self):
        result = self.resolver.resolve("999 Nonexistent St Atlanta GA")
        self.assertEqual(result.status, PropertyResolutionStatus.UNRESOLVED)
        self.assertFalse(result.resolved)
        self.assertIsNone(result.canonical_property_name)

    def test_ambiguous_component_is_exposed(self):
        resolver = PropertyResolver(
            [
                "-> Alpha - 100 Main St Atlanta, GA 30301",
                "-> Beta - 100 Main St Decatur, GA 30030",
            ]
        )
        result = resolver.resolve("100 Main St")
        self.assertEqual(result.status, PropertyResolutionStatus.AMBIGUOUS)
        self.assertFalse(result.resolved)
        self.assertEqual(len(result.candidates), 2)


if __name__ == "__main__":
    unittest.main()
