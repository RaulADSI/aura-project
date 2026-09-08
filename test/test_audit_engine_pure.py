from datetime import date
from decimal import Decimal
import os
import sys
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


class TestPureAuditEngine(unittest.TestCase):

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

    # ------------------------------------------------------------------
    # 1. BILLABLE STATUS & PRORATION
    # ------------------------------------------------------------------
    def test_audit_billable_full_proration(self):
        req = self._make_request(
            amount=Decimal("300.00"),
            service_start=date(2026, 1, 1),
            service_end=date(2026, 1, 30),
            move_in=date(2026, 1, 16),  # 15 occupied days
        )
        res = self.engine.audit(req)

        self.assertIsInstance(res, AuditResult)
        self.assertEqual(res.status, AuditStatus.BILLABLE)
        self.assertEqual(res.calculated_bill_back, Decimal("150.00"))
        self.assertEqual(res.total_service_days, 30)
        self.assertEqual(res.occupied_days, 15)
        self.assertEqual(len(res.anomalies), 0)

    # ------------------------------------------------------------------
    # 2. OWNER EXPENSE & ILLEGAL GL
    # ------------------------------------------------------------------
    def test_audit_owner_expense(self):
        req = self._make_request(gl_account="5810")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.OWNER_EXPENSE)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    def test_audit_illegal_gl(self):
        req = self._make_request(gl_account="9999")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ILLEGAL_GL)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # ------------------------------------------------------------------
    # 3. COMMON AREA & VACANT
    # ------------------------------------------------------------------
    def test_audit_common_area(self):
        req = self._make_request(unit_name="BLDG HSE")
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.COMMON_AREA)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    def test_audit_vacant_unit(self):
        req = self._make_request(tenant_name=None, move_in=None)
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.VACANT)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    # ------------------------------------------------------------------
    # 4. ANOMALIES & DATES
    # ------------------------------------------------------------------
    def test_audit_missing_service_dates_anomaly(self):
        req = self._make_request(service_start=None, service_end=None)
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ANOMALY_DETECTED)
        self.assertIn(AuditAnomalyFlag.MISSING_SERVICE_DATE, res.anomalies)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    def test_audit_invalid_service_period_anomaly(self):
        req = self._make_request(
            service_start=date(2026, 1, 30), service_end=date(2026, 1, 1)
        )
        res = self.engine.audit(req)

        self.assertEqual(res.status, AuditStatus.ANOMALY_DETECTED)
        self.assertIn(AuditAnomalyFlag.INVALID_SERVICE_PERIOD, res.anomalies)
        self.assertEqual(res.calculated_bill_back, Decimal("0.00"))

    def test_audit_unmatched_property_flag(self):
        req = self._make_request(property_name="Unmatched Property", unit_name="UNKNOWN")
        res = self.engine.audit(req)

        self.assertIn(AuditAnomalyFlag.MISSING_RENT_ROLL_CONTEXT, res.anomalies)


if __name__ == "__main__":
    unittest.main()
