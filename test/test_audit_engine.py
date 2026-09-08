import os
import sys
from datetime import date
from decimal import Decimal
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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
)


class TestAuditEnginePureContract(unittest.TestCase):

    def setUp(self):
        self.engine = AuditEngine(rules_path="config/utility_rules.json")

    def _make_request(
        self,
        gl_account="5815",
        unit_name="101",
        property_name="Oakridge Apartments",
        service_start=date(2026, 1, 1),
        service_end=date(2026, 1, 30),
        amount=Decimal("300.00"),
        move_in=date(2026, 1, 1),
        move_out=None,
        tenant_name="John Doe",
        unit_type="UNIT",
    ) -> AuditRequest:
        return AuditRequest(
            invoice=InvoiceData(
                invoice_id="INV-001",
                invoice_number="VENDOR-99",
                account_number="ACC-123",
                vendor_name="GA POWER",
                service_start_date=service_start,
                service_end_date=service_end,
                amount=amount,
            ),
            property=PropertyContext(
                property_id="PROP-1",
                property_name=property_name,
                unit_name=unit_name,
                unit_type=unit_type,
            ),
            occupancy=OccupancyContext(
                tenant_name=tenant_name,
                unit_status="Current" if tenant_name else "Vacant",
                move_in_date=move_in,
                move_out_date=move_out,
            ),
            accounting=AccountingContext(
                appfolio_amount_paid=Decimal("0.00"), gl_account=gl_account
            ),
        )

    # 1. Valid request -> BILLABLE, calculated_bill_back correct, Decimal
    def test_valid_request_returns_billable_and_decimal(self):
        req = self._make_request(amount=Decimal("200.00"), move_in=date(2026, 1, 1))
        res = self.engine.audit(req)

        self.assertIsInstance(res, AuditResult)
        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertIsInstance(res.calculated_bill_back, Decimal)
        self.assertEqual(res.calculated_bill_back, Decimal("200.00"))

    # 2. Missing service_start -> ANOMALY_DETECTED, MISSING_SERVICE_DATE
    def test_missing_service_start_returns_anomaly(self):
        req = self._make_request(service_start=None)
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ANOMALY_DETECTED)
        self.assertIn(AuditAnomalyFlag.MISSING_SERVICE_DATE, res.anomalies)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 3. Missing service_end -> ANOMALY_DETECTED, MISSING_SERVICE_DATE
    def test_missing_service_end_returns_anomaly(self):
        req = self._make_request(service_end=None)
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ANOMALY_DETECTED)
        self.assertIn(AuditAnomalyFlag.MISSING_SERVICE_DATE, res.anomalies)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 4. Inverted service period -> ANOMALY_DETECTED, INVALID_SERVICE_PERIOD
    def test_inverted_service_period_returns_anomaly(self):
        req = self._make_request(
            service_start=date(2026, 1, 30), service_end=date(2026, 1, 1)
        )
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ANOMALY_DETECTED)
        self.assertIn(AuditAnomalyFlag.INVALID_SERVICE_PERIOD, res.anomalies)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 5. Illegal GL -> ILLEGAL_GL
    def test_illegal_gl_returns_illegal_status(self):
        req = self._make_request(gl_account="9999")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ILLEGAL_GL)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 6. Owner expense -> OWNER_EXPENSE
    def test_owner_expense_gl_returns_owner_expense_status(self):
        req = self._make_request(gl_account="5810")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.OWNER_EXPENSE)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 7. Common area -> COMMON_AREA
    def test_common_area_returns_common_area_status(self):
        req = self._make_request(unit_name="BLDG HSE")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.COMMON_AREA)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 8. Valid service period + no occupancy overlap -> VACANT, occupied_days == 0
    def test_no_occupancy_overlap_returns_vacant(self):
        req = self._make_request(move_in=date(2024, 1, 1), move_out=date(2025, 12, 31))
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.VACANT)
        self.assertEqual(res.occupied_days, 0)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # 9. Partial occupancy -> BILLABLE, proportional bill-back
    def test_partial_occupancy_returns_proportional_bill_back(self):
        req = self._make_request(
            amount=Decimal("300.00"),
            service_start=date(2026, 1, 1),
            service_end=date(2026, 1, 30),
            move_in=date(2026, 1, 16),  # 15 days
        )
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertEqual(res.occupied_days, 15)
        self.assertEqual(res.calculated_bill_back, Decimal("150.00"))

    # 10. Full occupancy -> BILLABLE, full invoice amount
    def test_full_occupancy_returns_full_amount(self):
        req = self._make_request(amount=Decimal("450.25"), move_in=date(2025, 1, 1))
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertEqual(res.calculated_bill_back, Decimal("450.25"))

    # 11. Bill-back never exceeds invoice amount
    def test_bill_back_capped_at_invoice_amount(self):
        # Occupied days calculation cap
        req = self._make_request(
            amount=Decimal("200.00"),
            service_start=date(2026, 1, 1),
            service_end=date(2026, 1, 30),
            move_in=date(2025, 1, 1),
            move_out=date(2026, 2, 15),
        )
        res = self.engine.audit(req)

        self.assertLessEqual(res.calculated_bill_back, Decimal("200.00"))

    # 12. Monetary result is Decimal
    def test_monetary_result_is_strictly_decimal(self):
        req = self._make_request(amount=Decimal("123.45"))
        res = self.engine.audit(req)

        self.assertIsInstance(res.calculated_bill_back, Decimal)


if __name__ == "__main__":
    unittest.main()
