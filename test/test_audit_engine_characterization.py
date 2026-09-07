import os
import sys
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.auditor import AuditEngine
from src.domain.models import (
    AccountingContext,
    AuditRequest,
    InvoiceData,
    OccupancyContext,
    PropertyContext,
)


class TestAuditEngineCharacterization(unittest.TestCase):

    def setUp(self):
        self.engine = AuditEngine(rules_path="config/utility_rules.json")

    def _make_request(
        self,
        gl_account="5815",
        unit_name="101",
        service_start=date(2026, 1, 1),
        service_end=date(2026, 1, 30),
        amount=Decimal("300.00"),
        move_in=date(2026, 1, 1),
        move_out=None,
        tenant_name="John Doe",
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
                property_name="Oakridge Apartments",
                unit_name=unit_name,
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
    # 1. CLASIFICACIÓN GL (REGLAS DE NEGOCIO)
    # ------------------------------------------------------------------
    def test_classify_charge_owner_expense(self):
        status = self.engine.classify_charge("5810")
        self.assertEqual(status, "OWNER_EXPENSE")

    def test_classify_charge_billable(self):
        status = self.engine.classify_charge("5815")
        self.assertEqual(status, "BILLABLE")

    def test_classify_charge_illegal(self):
        status = self.engine.classify_charge("9999")
        self.assertEqual(status, "ILLEGAL")

    # ------------------------------------------------------------------
    # 2. ÁREAS COMUNES (EXCEPCIONES)
    # ------------------------------------------------------------------
    def test_common_area_keywords_positive(self):
        real_common_keywords = ["LNDRM", "LED LTS", "BLDG HSE", "UNREG LTS", "AHSE"]
        for keyword in real_common_keywords:
            with self.subTest(keyword=keyword):
                self.assertTrue(self.engine.is_common_area_exception(f"UNIT {keyword}"))

    def test_common_area_keywords_negative(self):
        self.assertFalse(self.engine.is_common_area_exception("APT 204"))

    # ------------------------------------------------------------------
    # 3. OCUPACIÓN Y LÍMITES INCLUSIVOS (+1 DÍA)
    # ------------------------------------------------------------------
    def test_occupancy_full_overlap(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2025-06-01", m_out=None
        )
        self.assertEqual(days, 30)

    def test_occupancy_partial_overlap_move_in_mid_cycle(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2026-01-16", m_out=None
        )
        self.assertEqual(days, 15)

    def test_occupancy_partial_overlap_move_out_mid_cycle(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2025-01-01", m_out="2026-01-10"
        )
        self.assertEqual(days, 10)

    def test_occupancy_exact_service_boundaries(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2026-01-01", m_out="2026-01-30"
        )
        self.assertEqual(days, 30)

    def test_occupancy_one_day_overlap(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2026-01-30", m_out="2026-01-30"
        )
        self.assertEqual(days, 1)

    def test_occupancy_no_overlap_vacant(self):
        days = self.engine.calculate_occupied_days(
            s_start="2026-01-01", s_end="2026-01-30",
            m_in="2024-01-01", m_out="2025-12-31"
        )
        self.assertEqual(days, 0)

    # ------------------------------------------------------------------
    # 4. MATEMÁTICA DE PRORRATEO (BILL-BACK)
    # ------------------------------------------------------------------
    def test_bill_back_calculation_proportional(self):
        bill_back = self.engine.calculate_bill_back(
            appfolio_amount=0.0,
            service_days=30,
            occupied_days=15,
            ocr_current_charge=300.00
        )
        self.assertEqual(round(bill_back, 2), 150.00)

    def test_bill_back_zero_occupied_days(self):
        bill_back = self.engine.calculate_bill_back(
            appfolio_amount=0.0,
            service_days=30,
            occupied_days=0,
            ocr_current_charge=300.00
        )
        self.assertEqual(round(bill_back, 2), 0.00)

    def test_bill_back_capped_at_service_days(self):
        bill_back = self.engine.calculate_bill_back(
            appfolio_amount=0.0,
            service_days=30,
            occupied_days=35,
            ocr_current_charge=300.00
        )
        self.assertEqual(round(bill_back, 2), 300.00)

    # ------------------------------------------------------------------
    # 5. CONTRATOS E INMUTABILIDAD
    # ------------------------------------------------------------------
    def test_audit_request_is_immutable(self):
        request = self._make_request()
        with self.assertRaises(FrozenInstanceError):
            request.invoice = request.invoice  # type: ignore

    def test_invalid_service_period_is_preserved_for_engine_validation(self):
        req = self._make_request(
            service_start=date(2026, 1, 30),
            service_end=date(2026, 1, 1)
        )
        self.assertGreater(
            req.invoice.service_start_date,
            req.invoice.service_end_date
        )

    def test_missing_service_dates_are_preserved_for_engine_validation(self):
        req = self._make_request(
            service_start=None,
            service_end=None
        )
        self.assertIsNone(req.invoice.service_start_date)
        self.assertIsNone(req.invoice.service_end_date)


if __name__ == "__main__":
    unittest.main()