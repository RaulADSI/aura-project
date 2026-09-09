import unittest

from src.adapters.historical_fixture_adapter import (
    HistoricalFixtureAdapter,
    parse_service_address,
)


class TestHistoricalFixtureAdapter(unittest.TestCase):
    def test_extracts_apt_and_preserves_locality(self):
        self.assertEqual(
            parse_service_address("1414 EUCLID AVE NE APT 3, ATLANTA GA"),
            ("1414 EUCLID AVE NE, ATLANTA GA", "3"),
        )

    def test_extracts_compact_apt_dot(self):
        self.assertEqual(
            parse_service_address("1006 TRIBBLE GAP RD APT.Z ATLANTA GA"),
            ("1006 TRIBBLE GAP RD, ATLANTA GA", "Z"),
        )

    def test_extracts_unit_after_semicolon(self):
        self.assertEqual(
            parse_service_address("417 BARTON DR;UNIT C3 ATLANTA GA 30338"),
            ("417 BARTON DR, ATLANTA GA 30338", "C3"),
        )

    def test_extracts_hash_unit(self):
        self.assertEqual(
            parse_service_address("2730 PEARL ST #1"),
            ("2730 PEARL ST", "1"),
        )

    def test_bldg_hse_maps_to_hse(self):
        self.assertEqual(
            parse_service_address("1360 NORTH AVE NE BLDG HSE ATLANTA GA"),
            ("1360 NORTH AVE NE, ATLANTA GA", "HSE"),
        )

    def test_no_explicit_unit_marker_remains_unchanged(self):
        self.assertEqual(
            parse_service_address("3272 COLLEGE ST A"),
            ("3272 COLLEGE ST A", ""),
        )

    def test_preserves_current_payload(self):
        source = {"property_name": "Existing Property", "unit_name": "7"}
        self.assertEqual(HistoricalFixtureAdapter.transform_payload(source), source)


if __name__ == "__main__":
    unittest.main()

class TestHistoricalFixturePropertyResolution(unittest.TestCase):
    def test_resolved_property_is_replaced_with_canonical_identity(self):
        from src.adapters.property_resolver import PropertyResolver

        resolver = PropertyResolver([
            "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307"
        ])
        batch = HistoricalFixtureAdapter.transform_batch(
            [{"service_address": "1414 EUCLID AVE NE APT 3, ATLANTA GA"}],
            property_resolver=resolver,
        )
        self.assertEqual(batch[0]["unit_name"], "3")
        self.assertEqual(
            batch[0]["property_name"],
            "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
        )
        self.assertEqual(
            batch[0]["property_resolution_status"],
            "ADDRESS_COMPONENT_MATCH",
        )

    def test_unresolved_property_remains_original_and_is_classified(self):
        from src.adapters.property_resolver import PropertyResolver

        resolver = PropertyResolver(["-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307"])
        batch = HistoricalFixtureAdapter.transform_batch(
            [{"service_address": "999 UNKNOWN ST APT 1 ATLANTA GA"}],
            property_resolver=resolver,
        )
        self.assertEqual(batch[0]["property_name"], "999 UNKNOWN ST, ATLANTA GA")
        self.assertEqual(batch[0]["property_resolution_status"], "UNRESOLVED")
