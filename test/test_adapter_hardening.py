from datetime import date
from decimal import Decimal
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.adapters.appfolio_adapter import AppFolioAdapter
from src.adapters.autostack_adapter import AutoStackAdapter
from src.adapters.audit_request_builder import AuditRequestBuilder
from src.adapters.utils import (
    AdapterValidationError,
    parse_decimal,
    parse_optional_iso_date,
    require_string,
    sanitize_string,
)
from src.domain.models import AuditRequest, InvoiceData, PropertyContext


class TestAdapterHardeningUtils(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. ADAPTER VALIDATION ERROR STRUCTURE
    # ------------------------------------------------------------------
    def test_adapter_validation_error_attributes(self):
        err = AdapterValidationError(
            "Test error",
            source="AutoStack",
            field="amount",
            record_id="INV-101",
            value="invalid",
        )
        self.assertEqual(err.source, "AutoStack")
        self.assertEqual(err.field, "amount")
        self.assertEqual(err.record_id, "INV-101")
        self.assertEqual(err.value, "invalid")
        self.assertEqual(str(err), "Test error")

    # ------------------------------------------------------------------
    # 2. STRING SANITIZATION & REQUIREMENT
    # ------------------------------------------------------------------
    def test_sanitize_string_null_like_values(self):
        null_likes = [None, "", "   ", "nan", "NAN", "None", "null", "NaT", "nat"]
        for val in null_likes:
            with self.subTest(val=val):
                self.assertEqual(sanitize_string(val), "")

    def test_require_string_valid(self):
        self.assertEqual(require_string("  INV-123  ", field="invoice_id"), "INV-123")

    def test_require_string_empty_raises_validation_error(self):
        for val in [None, "", "  ", "nan", "None"]:
            with self.subTest(val=val):
                with self.assertRaises(AdapterValidationError) as ctx:
                    require_string(val, field="invoice_id", record_id="REC-1")
                self.assertEqual(ctx.exception.field, "invoice_id")
                self.assertEqual(ctx.exception.record_id, "REC-1")

    # ------------------------------------------------------------------
    # 3. DECIMAL PARSING & ANTI-FLOAT PROTECTION
    # ------------------------------------------------------------------
    def test_parse_decimal_valid_strings(self):
        self.assertEqual(parse_decimal("12.34", field="amount"), Decimal("12.34"))
        self.assertEqual(parse_decimal(" $1,234.56 ", field="amount"), Decimal("1234.56"))
        self.assertEqual(parse_decimal(" (123.45) ", field="amount"), Decimal("-123.45"))
        self.assertEqual(parse_decimal("-123.45", field="amount"), Decimal("-123.45"))

    def test_parse_decimal_rejects_float(self):
        with self.assertRaises(AdapterValidationError) as ctx:
            parse_decimal(12.34, field="amount")  # float input
        self.assertIn("cannot be float", str(ctx.exception))

    def test_parse_decimal_rejects_empty_or_malformed(self):
        invalid_inputs = ["", "   ", "nan", "abc", "12.3.4", "12.3x"]
        for val in invalid_inputs:
            with self.subTest(val=val):
                with self.assertRaises(AdapterValidationError):
                    parse_decimal(val, field="amount")

    # ------------------------------------------------------------------
    # 4. OPTIONAL DATE PARSING
    # ------------------------------------------------------------------
    def test_parse_optional_date_valid(self):
        self.assertEqual(
            parse_optional_iso_date("2026-01-15", field="date"),
            date(2026, 1, 15),
        )
        self.assertEqual(
            parse_optional_iso_date(" 2026-01-15 ", field="date"),
            date(2026, 1, 15),
        )
        self.assertEqual(
            parse_optional_iso_date("2026/01/15", field="date"),
            date(2026, 1, 15),
        )

    def test_parse_optional_date_null_like_returns_none(self):
        for val in [None, "", "  ", "nan", "NaT", "none", "null"]:
            with self.subTest(val=val):
                self.assertIsNone(parse_optional_iso_date(val, field="date"))

    def test_parse_optional_date_corrupt_raises_validation_error(self):
        for val in ["01/99/foobar", "invalid-date", "2026-13-45"]:
            with self.subTest(val=val):
                with self.assertRaises(AdapterValidationError) as ctx:
                    parse_optional_iso_date(val, field="date", record_id="REC-1")
                self.assertEqual(ctx.exception.field, "date")


class TestAutoStackAdapterHardening(unittest.TestCase):

    def setUp(self):
        self.adapter = AutoStackAdapter()

    def test_autostack_rejects_non_list_payload(self):
        with self.assertRaises(AdapterValidationError):
            self.adapter.parse_invoice_payload("not a list")  # type: ignore

    def test_autostack_rejects_empty_critical_fields(self):
        required_fields = ["invoice_id", "account_number", "vendor_name", "amount"]
        base = {
            "invoice_id": "INV-100",
            "account_number": "ACC-100",
            "vendor_name": "GA POWER",
            "amount": "100.00",
        }
        for field in required_fields:
            with self.subTest(field=field):
                invalid_item = base.copy()
                invalid_item[field] = ""  # empty critical field
                with self.assertRaises(AdapterValidationError) as ctx:
                    self.adapter.parse_invoice_payload([invalid_item])
                self.assertEqual(ctx.exception.field, field)

    def test_autostack_rejects_float_amount(self):
        payload = [{
            "invoice_id": "INV-100",
            "account_number": "ACC-100",
            "vendor_name": "GA POWER",
            "amount": 100.50,  # float error!
        }]
        with self.assertRaises(AdapterValidationError) as ctx:
            self.adapter.parse_invoice_payload(payload)
        self.assertEqual(ctx.exception.field, "amount")

    def test_autostack_corrupt_date_raises_validation_error(self):
        payload = [{
            "invoice_id": "INV-100",
            "account_number": "ACC-100",
            "vendor_name": "GA POWER",
            "amount": "100.00",
            "service_start_date": "invalid-date-string",
        }]
        with self.assertRaises(AdapterValidationError) as ctx:
            self.adapter.parse_invoice_payload(payload)
        self.assertEqual(ctx.exception.field, "service_start_date")


class TestAuditRequestBuilderHardening(unittest.TestCase):

    def setUp(self):
        self.builder = AuditRequestBuilder("data/02_appfolio_reports/")

    def test_unmatched_property_logs_warning_and_flows_to_domain(self):
        payload = [{
            "invoice_id": "INV-UNMATCHED-1",
            "account_number": "ACC-UNMATCHED",
            "vendor_name": "GA POWER",
            "property_name": "Nonexistent Property 999",
            "unit_name": "Apt 99",
            "amount": "100.00",
            "service_start_date": "2026-01-01",
            "service_end_date": "2026-01-30",
        }]

        with self.assertLogs("src.adapters.audit_request_builder", level="WARNING") as cm:
            requests = self.builder.build_requests(payload)

        self.assertEqual(len(requests), 1)
        req = requests[0]
        self.assertIsInstance(req, AuditRequest)
        self.assertEqual(req.property.property_name, "Nonexistent Property 999")
        self.assertEqual(req.property.unit_name, "Apt 99")
        self.assertIsNone(req.occupancy.tenant_name)
        # Check warning log was emitted
        self.assertTrue(any("Rent Roll context not found" in log for log in cm.output))




class TestAppFolioAdapterHardening(unittest.TestCase):

    def setUp(self):
        self.data_path = "data/02_appfolio_reports/"
        self.adapter = AppFolioAdapter(self.data_path)

    def test_property_level_and_unit_level_accounting_keys_generated(self):
        accounting_map = self.adapter.load_accounting_contexts("appfolio_bills.csv")
        prop_key = "1031THORNWOODLANESTONEMOUNTAINGA30083"
        self.assertIn(prop_key, accounting_map)
        self.assertEqual(accounting_map[prop_key].gl_account, "5810")
        self.assertEqual(accounting_map[prop_key].appfolio_amount_paid, Decimal("263.80"))

    def test_corrupt_currency_raises_adapter_validation_error(self):
        # Test _parse_currency directly with corrupt input
        with self.assertRaises(AdapterValidationError):
            self.adapter._parse_currency("$xyz")

    def test_gl_priority_is_independent_of_csv_row_order(self):
        # Test deterministic GL selection
        import pandas as pd
        df1 = pd.DataFrame([
            {"gl_account": "5420 - Cleaning", "paid": "$100.00", "unpaid": "$0.00"},
            {"gl_account": "5810 - Electricity", "paid": "$50.00", "unpaid": "$0.00"},
            {"gl_account": "5825 - Gas", "paid": "$30.00", "unpaid": "$0.00"},
        ])
        df1["paid_dec"] = df1["paid"].apply(self.adapter._parse_currency)
        df1["unpaid_dec"] = df1["unpaid"].apply(self.adapter._parse_currency)
        df1["appfolio_amount"] = df1["paid_dec"] + df1["unpaid_dec"]

        df2 = df1.iloc[::-1].copy()

        ctx1 = self.adapter._build_accounting_context(df1, "gl_account")
        ctx2 = self.adapter._build_accounting_context(df2, "gl_account")

        self.assertEqual(ctx1.gl_account, "5810")
        self.assertEqual(ctx2.gl_account, "5810")
        self.assertEqual(ctx1.appfolio_amount_paid, Decimal("50.00"))
        self.assertEqual(ctx2.appfolio_amount_paid, Decimal("50.00"))


if __name__ == "__main__":
    unittest.main()
