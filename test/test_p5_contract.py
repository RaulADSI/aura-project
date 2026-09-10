import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

from src.contracts import StructuredUtilityInvoice
from src.contracts.structured_utility_invoice import CONTRACT_VERSION


class TestStructuredUtilityInvoice(unittest.TestCase):
    def _make(self, **overrides):
        values = {
            "invoice_id": "INV-001",
            "facts_id": "FACTS-001-v1",
            "facts_version": 1,
            "vendor_code": "FPL",
            "account_number": "6258331070",
            "invoice_amount": Decimal("117.90"),
            "invoice_number": "1001",
            "invoice_date": date(2026, 8, 31),
            "service_period_start": date(2026, 8, 1),
            "service_period_end": date(2026, 8, 31),
            "current_service_amount": Decimal("117.90"),
            "total_due": Decimal("217.90"),
            "extraction_method": "DETERMINISTIC_EXTRACTOR",
            "extractor_version": "FPL-v3",
        }
        values.update(overrides)
        return StructuredUtilityInvoice(**values)

    def test_contract_is_frozen(self):
        invoice = self._make()
        with self.assertRaises(FrozenInstanceError):
            invoice.invoice_amount = Decimal("1.00")

    def test_invoice_amount_must_be_decimal(self):
        with self.assertRaises(TypeError):
            self._make(invoice_amount=117.90)

    def test_zero_is_valid_and_distinct_from_missing(self):
        invoice = self._make(
            invoice_amount=Decimal("0.00"),
            current_service_amount=None,
            total_due=Decimal("0.00"),
        )
        self.assertEqual(invoice.invoice_amount, Decimal("0.00"))
        self.assertIsNone(invoice.current_service_amount)
        self.assertEqual(invoice.total_due, Decimal("0.00"))

    def test_optional_monetary_fact_rejects_float(self):
        with self.assertRaises(TypeError):
            self._make(current_service_amount=12.34)

    def test_monetary_fields_are_not_implicitly_substituted(self):
        invoice = self._make(
            current_service_amount=None,
            total_due=Decimal("117.90"),
        )
        self.assertIsNone(invoice.current_service_amount)
        self.assertEqual(invoice.total_due, Decimal("117.90"))

    def test_facts_version_must_be_positive_integer(self):
        for invalid in (0, -1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self._make(facts_version=invalid)
        with self.assertRaises(TypeError):
            self._make(facts_version="2")

    def test_contract_version_is_explicit_and_supported(self):
        invoice = self._make()
        self.assertEqual(invoice.contract_version, CONTRACT_VERSION)
        with self.assertRaises(ValueError):
            self._make(contract_version=2)

    def test_invalid_service_period_is_rejected_at_contract_boundary(self):
        with self.assertRaises(ValueError):
            self._make(
                service_period_start=date(2026, 9, 1),
                service_period_end=date(2026, 8, 31),
            )

    def test_blank_optional_strings_must_be_none(self):
        with self.assertRaises(ValueError):
            self._make(unit_hint="   ")

    def test_snapshot_identity_is_explicit(self):
        invoice = self._make(facts_id="FACTS-X", facts_version=7)
        self.assertEqual(
            (invoice.invoice_id, invoice.facts_id, invoice.facts_version),
            ("INV-001", "FACTS-X", 7),
        )


if __name__ == "__main__":
    unittest.main()
