from datetime import date
from decimal import Decimal, ROUND_DOWN, getcontext
import unittest

from src.auditor import AuditEngine
from src.domain.models import (
    AccountingContext,
    AuditAnomalyFlag,
    AuditRequest,
    AuditResult,
    AuditStatus,
    InvoiceData,
    OccupancyContext,
    PropertyContext,
    ZERO_MONEY,
    quantize_money,
)


class TestDomainInvariants(unittest.TestCase):

    def setUp(self):
        self.engine = AuditEngine("config/utility_rules.json")

    def _make_valid_request(self, amount=Decimal("300.00")) -> AuditRequest:
        return AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-001",
                invoice_number="VENDOR-99",
                account_number="ACC-123",
                vendor_name="GA POWER",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=amount,
            ),
            property=PropertyContext(
                property_id="PROP-1",
                property_name="Oakridge Apartments",
                unit_name="101",
            ),
            occupancy=OccupancyContext(
                tenant_name="John Doe",
                unit_status="Current",
                move_in_date=date(2026, 1, 1),
                move_out_date=None,
            ),
            accounting=AccountingContext(
                appfolio_amount_paid=Decimal("0.00"),
                gl_account="5815",
            ),
        )

    # ------------------------------------------------------------------
    # 1. QUANTIZE_MONEY PRIMITIVE & CONTEXT ISOLATION
    # ------------------------------------------------------------------
    def test_quantize_money_ignores_global_rounding(self):
        original_rounding = getcontext().rounding
        try:
            getcontext().rounding = ROUND_DOWN
            self.assertEqual(quantize_money(Decimal("10.005")), Decimal("10.01"))
        finally:
            getcontext().rounding = original_rounding

    def test_quantize_money_rejects_non_decimal(self):
        with self.assertRaises(TypeError):
            quantize_money(10.005)  # float

        with self.assertRaises(TypeError):
            quantize_money("10.005")  # str

    # ------------------------------------------------------------------
    # 2. INVOICE DATA & ACCOUNTING CONTEXT ANTI-FLOAT / NEGATIVE
    # ------------------------------------------------------------------
    def test_invoice_data_rejects_float_amount(self):
        with self.assertRaises(TypeError):
            InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="VENDOR",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=100.50,  # float error
            )

    def test_invoice_data_rejects_negative_amount(self):
        with self.assertRaises(ValueError):
            InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="VENDOR",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=Decimal("-50.00"),
            )

    def test_accounting_context_rejects_float_paid(self):
        with self.assertRaises(TypeError):
            AccountingContext(appfolio_amount_paid=100.00)

    def test_accounting_context_rejects_negative_paid(self):
        with self.assertRaises(ValueError):
            AccountingContext(appfolio_amount_paid=Decimal("-10.00"))

    # ------------------------------------------------------------------
    # 3. AUDIT RESULT STRUCTURAL INVARIANTS
    # ------------------------------------------------------------------
    def test_audit_result_rejects_non_zero_for_zero_statuses(self):
        req = self._make_valid_request()
        zero_statuses = [
            AuditStatus.VACANT,
            AuditStatus.OWNER_EXPENSE,
            AuditStatus.ILLEGAL_GL,
            AuditStatus.COMMON_AREA,
            AuditStatus.ANOMALY_DETECTED,
            AuditStatus.NON_BILLABLE,
        ]
        for status in zero_statuses:
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    AuditResult(
                        request=req,
                        status=status,
                        calculated_bill_back=Decimal("15.00"),  # Violation!
                        total_service_days=31,
                        occupied_days=15,
                    )

    def test_audit_result_rejects_occupied_days_exceeding_total_service_days(self):
        req = self._make_valid_request()
        with self.assertRaises(ValueError):
            AuditResult(
                request=req,
                status=AuditStatus.BILLABLE,
                calculated_bill_back=Decimal("300.00"),
                total_service_days=30,
                occupied_days=35,  # Exceeds 30!
            )

    def test_audit_result_rejects_non_zero_occupied_days_when_total_days_zero(self):
        req = self._make_valid_request()
        with self.assertRaises(ValueError):
            AuditResult(
                request=req,
                status=AuditStatus.ANOMALY_DETECTED,
                calculated_bill_back=Decimal("0.00"),
                total_service_days=0,
                occupied_days=5,  # Invalid when total service days is 0!
            )

    # ------------------------------------------------------------------
    # 4. OCCUPANCY BOUNDARIES & EDGE CASES
    # ------------------------------------------------------------------
    def test_single_day_service_period(self):
        req = AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="POWER",
                service_start_date=date(2026, 1, 11),
                service_end_date=date(2026, 1, 11),
                amount=Decimal("100.00"),
            ),
            property=PropertyContext(property_id="1", property_name="P1", unit_name="U1"),
            occupancy=OccupancyContext(
                tenant_name="John Doe",
                move_in_date=date(2026, 1, 11),
                move_out_date=date(2026, 1, 11),
            ),
            accounting=AccountingContext(gl_account="5815"),
        )
        res = self.engine.audit(req)
        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertEqual(res.total_service_days, 1)
        self.assertEqual(res.occupied_days, 1)
        self.assertEqual(res.calculated_bill_back, Decimal("100.00"))

    def test_single_day_occupied_in_multi_day_service(self):
        # Service: Jan 1 -> Jan 31 (31 days)
        # Move-in/out: Jan 31 -> Jan 31 (1 day)
        # Amount: $310.00 -> $10.00
        req = AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="POWER",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=Decimal("310.00"),
            ),
            property=PropertyContext(property_id="1", property_name="P1", unit_name="U1"),
            occupancy=OccupancyContext(
                tenant_name="John Doe",
                move_in_date=date(2026, 1, 31),
                move_out_date=date(2026, 1, 31),
            ),
            accounting=AccountingContext(gl_account="5815"),
        )
        res = self.engine.audit(req)
        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertEqual(res.total_service_days, 31)
        self.assertEqual(res.occupied_days, 1)
        self.assertEqual(res.calculated_bill_back, Decimal("10.00"))

    def test_tenant_moved_out_before_service_period(self):
        req = AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="POWER",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=Decimal("300.00"),
            ),
            property=PropertyContext(property_id="1", property_name="P1", unit_name="U1"),
            occupancy=OccupancyContext(
                tenant_name="Old Tenant",
                move_in_date=date(2024, 1, 1),
                move_out_date=date(2025, 12, 31),
            ),
            accounting=AccountingContext(gl_account="5815"),
        )
        res = self.engine.audit(req)
        self.assertEqual(res.status, AuditStatus.VACANT)
        self.assertEqual(res.occupied_days, 0)
        self.assertEqual(res.calculated_bill_back, ZERO_MONEY)

    def test_tenant_moves_in_after_service_period(self):
        req = AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-1",
                invoice_number=None,
                account_number="ACC-1",
                vendor_name="POWER",
                service_start_date=date(2026, 1, 1),
                service_end_date=date(2026, 1, 31),
                amount=Decimal("300.00"),
            ),
            property=PropertyContext(property_id="1", property_name="P1", unit_name="U1"),
            occupancy=OccupancyContext(
                tenant_name="Future Tenant",
                move_in_date=date(2026, 2, 1),
                move_out_date=None,
            ),
            accounting=AccountingContext(gl_account="5815"),
        )
        res = self.engine.audit(req)
        self.assertEqual(res.status, AuditStatus.VACANT)
        self.assertEqual(res.occupied_days, 0)
        self.assertEqual(res.calculated_bill_back, ZERO_MONEY)

    # ------------------------------------------------------------------
    # 5. PARAMETERIZED DETERMINISTIC GL CLASSIFICATION
    # ------------------------------------------------------------------
    def test_gl_classification_determinism(self):
        test_cases = [
            ("5815", "BILLABLE"),
            ("5825", "BILLABLE"),
            ("5855", "BILLABLE"),
            ("5860", "BILLABLE"),
            ("5810", "OWNER_EXPENSE"),
            ("5820", "OWNER_EXPENSE"),
            ("5830", "OWNER_EXPENSE"),
            ("5840", "OWNER_EXPENSE"),
            ("5850", "OWNER_EXPENSE"),
            ("9999", "ILLEGAL"),
            ("1000", "ILLEGAL"),
            (None, "UNKNOWN"),
        ]
        for gl_code, expected_class in test_cases:
            with self.subTest(gl_code=gl_code):
                self.assertEqual(self.engine.classify_charge(gl_code), expected_class)


if __name__ == "__main__":
    unittest.main()
