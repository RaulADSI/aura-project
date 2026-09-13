import contextlib
import json
import sqlite3
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock

from src.domain.utility_billback_eligibility import UtilityBillBackEligibilityPolicy, UtilityEligibility
from src.domain.models import AuditStatus
from src.runtime.run_billbacks import create_service, AuraRuntimeConfig
from src.application.rules_metadata import load_rules_metadata
from src.application.billback_decision_factory import BillBackDecisionFactory
from src.adapters.sqlite_billback_decision_repository import SqliteBillBackDecisionRepository
from src.adapters.sqlite_billback_decision_reader import SqliteBillBackDecisionReader
from src.application.billback_decision_query_service import BillBackDecisionQueryService
from src.application.operational_summary import build_operational_summary
from src.delivery.csv_exporter import CsvBillBackExporter
from test import test_p56_runtime as fixtures
from test.test_p6_decision_persistence import make_decision


class TestUtilityEligibility(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TestRuntime()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config

    def update(self, sql, params=()):
        with contextlib.closing(sqlite3.connect(self.fixture.db)) as conn, conn:
            conn.execute(sql, params)

    def test_unknown_vendor_is_review_before_amount_and_occupancy(self):
        self.update("UPDATE utility_invoice_details SET vendor_code='NEW_VENDOR', current_service_amount=NULL WHERE invoice_id='review-only'")
        service = create_service(self.config)
        service.request_builder = Mock()
        service.audit_engine = Mock()
        run = service.run(invoice_id="review-only", facts_version=1)
        self.assertFalse(run.results)
        self.assertIn("BILLBACK_ELIGIBILITY_REVIEW_REQUIRED", run.rejected[0][1])
        service.request_builder.build.assert_not_called()
        service.audit_engine.audit.assert_not_called()
        self.assertEqual(BillBackDecisionFactory(load_rules_metadata(self.config.utility_rules_path)).from_run(run), ())

    def test_gp_standard_and_final_regression(self):
        for bill_type in (None, "STANDARD", "FINAL"):
            self.update("UPDATE utility_invoice_details SET bill_type=?", (bill_type,))
            fixtures.assert_p56(self, create_service(self.config).run())

    def test_common_area_without_amount_dates_or_occupancy_is_persisted(self):
        self.update("UPDATE utility_invoice_details SET current_service_amount=NULL, service_period_start=NULL, service_period_end=NULL WHERE invoice_id='common-0'")
        service = create_service(self.config)
        service.request_builder.rent_roll_contexts = Mock()
        service.audit_engine = Mock()
        run = service.run(invoice_id="common-0", facts_version=1)
        self.assertFalse(run.rejected)
        self.assertEqual(run.results[0].status, AuditStatus.COMMON_AREA)
        self.assertEqual(run.results[0].calculated_bill_back, Decimal("0.00"))
        service.audit_engine.audit.assert_not_called()
        self.roundtrip_zero(run, AuditStatus.COMMON_AREA)

    def test_explicit_nonbillable_before_amount_and_persists_reason(self):
        self.update("UPDATE utility_invoice_details SET current_service_amount=NULL, service_period_start=NULL, service_period_end=NULL WHERE invoice_id='review-only'")
        rules = json.loads(self.config.utility_rules_path.read_text())
        rules["non_billable_services"] = [{"vendor_code": "GEORGIA_POWER", "routing_key": "WG-4735-V0", "reason": "Service explicitly owner-paid"}]
        path = self.fixture.folder / "rules.json"
        path.write_text(json.dumps(rules))
        config = AuraRuntimeConfig(self.config.autostack_db_path, self.config.rent_roll_path, path)
        service = create_service(config)
        service.request_builder.rent_roll_contexts = Mock()
        service.audit_engine = Mock()
        run = service.run(invoice_id="review-only", facts_version=1)
        self.assertEqual(run.results[0].status, AuditStatus.NON_BILLABLE)
        self.assertEqual(run.results[0].notes, "Service explicitly owner-paid")
        service.audit_engine.audit.assert_not_called()
        self.roundtrip_zero(run, AuditStatus.NON_BILLABLE)

    def roundtrip_zero(self, run, expected_status):
        decisions = BillBackDecisionFactory(load_rules_metadata(self.config.utility_rules_path)).from_run(run)
        repo = SqliteBillBackDecisionRepository(self.fixture.folder / "aura.db")
        first = repo.save(decisions[0])
        self.assertEqual(first, repo.save(decisions[0]))
        reader = SqliteBillBackDecisionReader(repo.path)
        stored = reader.list_active()[0]
        self.assertIsNone(stored.current_service_amount)
        self.assertIsNone(stored.service_period_start)
        self.assertEqual(stored.classification, expected_status)
        self.assertEqual(stored.decision_reason, run.results[0].notes)
        models = BillBackDecisionQueryService(reader).list_active()
        self.assertEqual(build_operational_summary(models).statuses, {expected_status.name: 1})
        CsvBillBackExporter().export(models, self.fixture.folder / "decisions.csv")

    def test_gas_south_is_not_eligible_even_with_complete_facts(self):
        self.update("UPDATE utility_invoice_details SET vendor_code='GAS_SOUTH' WHERE invoice_id='review-only'")
        service = create_service(self.config)
        self.assertNotIn("review-only", {i.invoice.invoice_id for i in service.run().identities})
        run = service.run(invoice_id="review-only", facts_version=1)
        self.assertFalse(run.results)
        self.assertIn("BILLBACK_ELIGIBILITY_REVIEW_REQUIRED", run.rejected[0][1])

    def test_common_area_precedes_explicit_exclusion(self):
        policy = UtilityBillBackEligibilityPolicy([dict(vendor_code="OTHER", routing_key="HSE", reason="excluded")])
        decision = policy.evaluate(vendor_code="OTHER", routing_key="HSE", identity_type="COMMON_AREA")
        self.assertEqual(decision.outcome, UtilityEligibility.COMMON_AREA)

    def test_nullable_facts_are_only_allowed_for_zero_eligibility(self):
        with self.assertRaises(TypeError):
            make_decision(current_service_amount=None)
        with self.assertRaises(ValueError):
            make_decision(classification=AuditStatus.NON_BILLABLE, bill_back_amount=Decimal("1"))

    def test_invalid_policy_config_fails_startup(self):
        with self.assertRaises(ValueError):
            UtilityBillBackEligibilityPolicy([dict(vendor_code="GP")])

    def test_legacy_database_migrates_without_losing_decisions(self):
        from src.adapters.sqlite_billback_decision_repository import SCHEMA
        path = self.fixture.folder / "old.db"
        old_schema = SCHEMA.replace("service_period_start TEXT,", "service_period_start TEXT NOT NULL,").replace("service_period_end TEXT,", "service_period_end TEXT NOT NULL,").replace("current_service_amount TEXT,", "current_service_amount TEXT NOT NULL,")
        with contextlib.closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript(old_schema)
            values = SqliteBillBackDecisionRepository._to_row(make_decision())
            conn.execute("INSERT INTO bill_back_decisions VALUES (" + ",".join("?" for _ in values) + ")", values)
        repo = SqliteBillBackDecisionRepository(path)
        self.assertEqual(repo.list_active(), (make_decision(),))
        zero = replace(make_decision(), decision_id="zero", invoice_id="zero", classification=AuditStatus.NON_BILLABLE,
                       current_service_amount=None, service_period_start=None, service_period_end=None,
                       bill_back_amount=Decimal("0.00"), occupied_days=0, total_service_days=0)
        repo.save(zero)
        self.assertEqual(len(repo.list_active()), 2)
        self.assertEqual(len(SqliteBillBackDecisionRepository(path).list_active()), 2)
