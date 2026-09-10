import unittest
from dataclasses import dataclass
from decimal import Decimal

from src.adapters.property_resolver import PropertyResolver
from src.adapters.unit_resolver import UnitResolver
from src.contracts import StructuredUtilityInvoice
from src.integration_autostack import (
    AuraInputEligibility,
    AutoStackRoutingIdentityAdapter,
    CommonAreaClassifier,
    IdentityType,
)


@dataclass
class _Port:
    snapshots: tuple

    def list_canonical_snapshots(self):
        return self.snapshots

    def get_exact_snapshot(self, invoice_id, facts_version):
        return next(x for x in self.snapshots if x.invoice_id == invoice_id and x.facts_version == facts_version)


def _invoice(routing_key):
    return StructuredUtilityInvoice(
        invoice_id="inv-1",
        facts_id="facts-1",
        facts_version=1,
        vendor_code="GEORGIA_POWER",
        account_number="123",
        invoice_amount=Decimal("10.00"),
        routing_key=routing_key,
        extraction_method="AUTOSTACK_PERSISTED_FACTS",
    )


class TestP5AuraIntegration(unittest.TestCase):
    def setUp(self):
        self.wingate = "-> Wingate Apartments - 4735 Courtney Drive Forest Park, GA 30297"
        self.property_resolver = PropertyResolver([self.wingate])
        self.unit_resolver = UnitResolver({
            self.wingate: ["D8", "HC E4", "BW B4", "Wingate Phase 2-R1"]
        })

    def _adapter(self, routing_key, *, common_area_classifier=None):
        return AutoStackRoutingIdentityAdapter(
            _Port((_invoice(routing_key),)),
            self.property_resolver,
            self.unit_resolver,
            common_area_classifier=common_area_classifier,
        )

    def test_wg_route_reaches_existing_identity_pipeline(self):
        result = self._adapter("WG-4735-D8").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.unit_resolution.canonical_unit_name, "D8")

    def test_hc_route_maps_to_section_prefixed_unit(self):
        result = self._adapter("HC-4671-E4").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.unit_resolution.canonical_unit_name, "HC E4")

    def test_bw_route_maps_to_section_prefixed_unit(self):
        result = self._adapter("BW-4685-B4").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.unit_resolution.canonical_unit_name, "BW B4")

    def test_phase_2_route_maps_to_canonical_phase_unit(self):
        result = self._adapter("WG-4767-R1").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.unit_resolution.canonical_unit_name, "Wingate Phase 2-R1")

    def test_property_only_multi_unit_route_is_not_audit_eligible(self):
        result = self._adapter("4735 Wingate Apartments").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.UNIT_UNRESOLVED)

    def test_unknown_route_is_property_unresolved(self):
        result = self._adapter("UNKNOWN ROUTE").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.PROPERTY_UNRESOLVED)

    def test_common_area_without_classifier_remains_unresolved(self):
        result = self._adapter("BW-4685-BLDG F LIGHTS").resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.UNIT_UNRESOLVED)

    def test_common_area_classifier_bypasses_unit_resolver(self):
        classifier = CommonAreaClassifier(["BLDG F LIGHTS"])
        result = self._adapter(
            "BW-4685-BLDG F LIGHTS", common_area_classifier=classifier
        ).resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.identity_type, IdentityType.COMMON_AREA)
        self.assertEqual(result.identity_identifier, "BLDG F LIGHTS")
        self.assertIsNone(result.unit_resolution)

    def test_common_area_classifier_uses_fallback_hint_after_section_prefix(self):
        classifier = CommonAreaClassifier(["HSEB"])
        result = self._adapter(
            "HC-4671-HSEB", common_area_classifier=classifier
        ).resolve_canonical_snapshots()[0]
        self.assertEqual(result.identity_type, IdentityType.COMMON_AREA)
        self.assertEqual(result.identity_identifier, "HSEB")

    def test_common_area_classifier_loads_real_rules_file(self):
        classifier = CommonAreaClassifier.from_rules_file("config/utility_rules.json")
        for identifier in (
            "HSEB", "HSEE", "HSEG", "BLDG F LIGHTS", "BLDG C LIGHTS",
            "BLDG D LIGHTS", "JLNDY", "HSEO", "KLNDY",
        ):
            with self.subTest(identifier=identifier):
                self.assertEqual(classifier.classify((identifier,)), identifier)

    def test_section_specific_unit_wins_over_naked_fallback(self):
        wingate = self.wingate
        resolver = UnitResolver({wingate: ["HC E4", "E4"]})
        adapter = AutoStackRoutingIdentityAdapter(
            _Port((_invoice("HC-4671-E4"),)), self.property_resolver, resolver
        )
        result = adapter.resolve_canonical_snapshots()[0]
        self.assertEqual(result.eligibility, AuraInputEligibility.IDENTITY_RESOLVED)
        self.assertEqual(result.unit_resolution.canonical_unit_name, "HC E4")

    def test_compact_wingate_text_route_resolves_property(self):
        result = self._adapter("4735WingateApartments").resolve_canonical_snapshots()[0]
        self.assertNotEqual(result.eligibility, AuraInputEligibility.PROPERTY_UNRESOLVED)


if __name__ == "__main__":
    unittest.main()
