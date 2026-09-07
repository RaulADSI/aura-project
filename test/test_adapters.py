from decimal import Decimal
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.adapters.appfolio_adapter import AppFolioAdapter
from src.adapters.autostack_adapter import (
    AdapterValidationError,
    AutoStackAdapter,
)
from src.adapters.audit_request_builder import AuditRequestBuilder
from src.domain.models import (
    AccountingContext,
    AuditRequest,
    InvoiceData,
    OccupancyContext,
    PropertyContext,
)


class TestAutoStackAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = AutoStackAdapter()

    def test_parses_invoice_into_domain_contract(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "invoice_number": "GA-9921",
                "account_number": "4401-221",
                "vendor_name": "GEORGIA POWER",
                "service_start_date": "2026-01-01",
                "service_end_date": "2026-01-30",
                "amount": "154.50",
            }
        ]

        invoices = self.adapter.parse_invoice_payload(payload)

        self.assertEqual(len(invoices), 1)

        invoice = invoices[0]

        self.assertEqual(invoice.invoice_id, "INV-1001")
        self.assertEqual(invoice.invoice_number, "GA-9921")
        self.assertEqual(invoice.account_number, "4401-221")
        self.assertEqual(invoice.vendor_name, "GEORGIA POWER")
        self.assertEqual(invoice.amount, Decimal("154.50"))

    def test_amount_uses_decimal_and_half_up_rounding(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "invoice_number": "GA-9921",
                "account_number": "4401-221",
                "vendor_name": "GEORGIA POWER",
                "amount": "154.505",
            }
        ]

        invoices = self.adapter.parse_invoice_payload(payload)

        self.assertIsInstance(invoices[0].amount, Decimal)
        self.assertEqual(invoices[0].amount, Decimal("154.51"))

    def test_amount_does_not_pass_through_float(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "account_number": "4401-221",
                "vendor_name": "GEORGIA POWER",
                "amount": "0.29",
            }
        ]

        invoice = self.adapter.parse_invoice_payload(payload)[0]

        self.assertEqual(invoice.amount, Decimal("0.29"))

    def test_missing_invoice_id_raises_validation_error(self):
        payload = [
            {
                "account_number": "4401-221",
                "vendor_name": "GEORGIA POWER",
                "amount": "154.50",
            }
        ]

        with self.assertRaises(AdapterValidationError):
            self.adapter.parse_invoice_payload(payload)

    def test_missing_account_number_raises_validation_error(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "vendor_name": "GEORGIA POWER",
                "amount": "154.50",
            }
        ]

        with self.assertRaises(AdapterValidationError):
            self.adapter.parse_invoice_payload(payload)

    def test_missing_vendor_raises_validation_error(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "account_number": "4401-221",
                "amount": "154.50",
            }
        ]

        with self.assertRaises(AdapterValidationError):
            self.adapter.parse_invoice_payload(payload)

    def test_missing_amount_raises_validation_error(self):
        payload = [
            {
                "invoice_id": "INV-1001",
                "account_number": "4401-221",
                "vendor_name": "GEORGIA POWER",
            }
        ]

        with self.assertRaises(AdapterValidationError):
            self.adapter.parse_invoice_payload(payload)


class TestAppFolioAdapter(unittest.TestCase):

    def setUp(self):
        self.data_path = "data/02_appfolio_reports/"
        self.adapter = AppFolioAdapter(self.data_path)

    def test_has_no_dependency_on_data_extractor(self):
        self.assertFalse(hasattr(self.adapter, "extractor"))
        self.assertFalse(hasattr(self.adapter, "DataExtractor"))

    def test_loads_rent_roll_contexts(self):
        contexts = self.adapter.load_rent_roll_contexts("rent_roll.json")
        self.assertGreater(len(contexts), 0)

        first_key = list(contexts.keys())[0]
        prop_ctx, occ_ctx = contexts[first_key]

        self.assertIsInstance(prop_ctx, PropertyContext)
        self.assertIsInstance(occ_ctx, OccupancyContext)
        self.assertTrue(len(prop_ctx.property_name) > 0)
        self.assertTrue(len(prop_ctx.unit_name) > 0)

    def test_loads_accounting_contexts_with_decimal_and_clean_gl(self):
        accounting_map = self.adapter.load_accounting_contexts("appfolio_bills.csv")
        self.assertGreater(len(accounting_map), 0)

        for key, acc_ctx in accounting_map.items():
            self.assertIsInstance(acc_ctx, AccountingContext)
            self.assertIsInstance(acc_ctx.appfolio_amount_paid, Decimal)

            if acc_ctx.gl_account:
                # Ensure GL account code is extracted as a 4-digit string
                self.assertTrue(
                    len(acc_ctx.gl_account) == 4 and acc_ctx.gl_account.isdigit(),
                    f"GL account '{acc_ctx.gl_account}' should be a 4-digit code."
                )

    def test_prioritizes_utility_gl_accounts_over_other_expenses(self):
        accounting_map = self.adapter.load_accounting_contexts("appfolio_bills.csv")
        # Match key for 1031 Thornwoode Lane has HOA Dues (5730) and Electricity (5810)
        key = "1031THORNWOODLANESTONEMOUNTAINGA30083"
        self.assertIn(key, accounting_map)

        acc_ctx = accounting_map[key]
        self.assertEqual(acc_ctx.gl_account, "5810")
        # Sum of 5810 bills: 83.80 + 30.00 + 150.00 = 263.80
        self.assertEqual(acc_ctx.appfolio_amount_paid, Decimal("263.80"))


class TestAuditRequestBuilder(unittest.TestCase):

    def setUp(self):
        self.data_path = "data/02_appfolio_reports/"
        self.builder = AuditRequestBuilder(self.data_path)

    def test_assembles_audit_requests_with_exact_property_correlation(self):
        raw_autostack = [
            {
                "invoice_id": "INV-550",
                "invoice_number": "GA-881",
                "account_number": "97737-48323",
                "vendor_name": "GEORGIA POWER",
                "property_name": "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307",
                "unit_name": "Apt 2",
                "service_start_date": "2026-01-01",
                "service_end_date": "2026-01-30",
                "amount": "250.00",
            }
        ]

        requests = self.builder.build_requests(raw_autostack)
        self.assertEqual(len(requests), 1)

        req = requests[0]
        self.assertIsInstance(req, AuditRequest)
        self.assertIsInstance(req.invoice, InvoiceData)
        self.assertIsInstance(req.property, PropertyContext)
        self.assertIsInstance(req.occupancy, OccupancyContext)
        self.assertIsInstance(req.accounting, AccountingContext)

        self.assertEqual(req.invoice.invoice_id, "INV-550")
        self.assertEqual(req.invoice.amount, Decimal("250.00"))
        self.assertEqual(req.property.property_name, "-> 1414 Euclid Ave - 1414 Euclid Ave Atlanta, GA 30307")
        self.assertEqual(req.property.unit_name, "Apt 2")
        self.assertEqual(req.occupancy.tenant_name, "Charles Burch")

    def test_handles_unmatched_property_without_crashing(self):
        raw_autostack = [
            {
                "invoice_id": "INV-999",
                "account_number": "9999-999",
                "vendor_name": "UNKNOWN POWER",
                "property_name": "999 Nonexistent St",
                "unit_name": "Apt 99",
                "amount": "100.00",
            }
        ]

        requests = self.builder.build_requests(raw_autostack)
        self.assertEqual(len(requests), 1)

        req = requests[0]
        self.assertEqual(req.property.property_name, "999 Nonexistent St")
        self.assertEqual(req.property.unit_name, "Apt 99")
        self.assertIsNone(req.occupancy.tenant_name)
        self.assertEqual(req.accounting.appfolio_amount_paid, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()