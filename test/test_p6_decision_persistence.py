import contextlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.adapters.sqlite_billback_decision_repository import (
    NonDeterministicDecisionError,
    RuleVersionConflictError,
    SqliteBillBackDecisionRepository,
)
from src.application.billback_decision_factory import BillBackDecisionFactory
from src.application.persist_billback_decisions import PersistBillBackDecisions
from src.application.rules_metadata import RulesMetadata, load_rules_metadata
from src.domain.billback_decision import BillBackDecision, DecisionStatus
from src.domain.models import AuditStatus
from src.runtime.run_billbacks import AuraRuntimeConfig, create_service
from test.test_p5_autostack_sqlite_adapter import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def make_decision(**changes):
    base = BillBackDecision(
        decision_id="decision-1",
        invoice_id="invoice-1",
        source_facts_id="facts-1",
        source_facts_version=1,
        rule_version="1",
        rules_hash="abc123",
        decision_version=1,
        vendor="GEORGIA_POWER",
        account_number="123",
        property_name="Wingate Apartments",
        unit_name="D6",
        tenant_name="Tenant",
        service_period_start=__import__('datetime').date(2026, 7, 22),
        service_period_end=__import__('datetime').date(2026, 8, 24),
        current_service_amount=Decimal("294.41"),
        occupied_days=34,
        total_service_days=34,
        bill_back_amount=Decimal("294.41"),
        classification=AuditStatus.BILLABLE,
        decision_reason="billable",
        decision_status=DecisionStatus.ACTIVE,
        decided_at=FIXED_TIME,
    )
    return replace(base, **changes)


class TestBillBackDecisionModel(unittest.TestCase):
    def test_zero_classifications_require_zero_billback(self):
        with self.assertRaisesRegex(ValueError, "VACANT"):
            make_decision(classification=AuditStatus.VACANT, bill_back_amount=Decimal("1.00"))
        self.assertEqual(
            make_decision(classification=AuditStatus.COMMON_AREA, bill_back_amount=Decimal("0.00")).bill_back_amount,
            Decimal("0.00"),
        )

    def test_non_decision_audit_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a persistable"):
            make_decision(classification=AuditStatus.ANOMALY_DETECTED, bill_back_amount=Decimal("0.00"))


class TestSqliteDecisionRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = SqliteBillBackDecisionRepository(Path(self.tmp.name) / "aura.db")

    def test_same_provenance_and_same_payload_is_idempotent(self):
        first = self.repo.save(make_decision())
        second = self.repo.save(replace(make_decision(), decided_at=datetime(2026, 9, 10, tzinfo=timezone.utc)))
        self.assertEqual(first, second)
        self.assertEqual(len(self.repo.list_all()), 1)

    def test_same_provenance_with_changed_decision_fails(self):
        self.repo.save(make_decision())
        with self.assertRaises(NonDeterministicDecisionError):
            self.repo.save(make_decision(bill_back_amount=Decimal("293.41")))
        self.assertEqual(len(self.repo.list_all()), 1)

    def test_same_rule_version_with_different_hash_fails_explicitly(self):
        self.repo.save(make_decision())
        with self.assertRaises(RuleVersionConflictError):
            self.repo.save(make_decision(rules_hash="different"))

    def test_new_facts_version_creates_history_and_supersedes_old_active(self):
        old = self.repo.save(make_decision())
        new = self.repo.save(make_decision(
            decision_id="decision-2",
            source_facts_id="facts-2",
            source_facts_version=2,
            current_service_amount=Decimal("300.00"),
            bill_back_amount=Decimal("300.00"),
        ))
        self.assertEqual(old.decision_version, 1)
        self.assertEqual(new.decision_version, 2)
        history = self.repo.list_all()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].decision_status, DecisionStatus.SUPERSEDED)
        self.assertEqual(history[1].decision_status, DecisionStatus.ACTIVE)

    def test_money_is_stored_as_text_not_real(self):
        self.repo.save(make_decision())
        with sqlite3.connect(self.repo.path) as conn:
            row = conn.execute(
                "SELECT typeof(current_service_amount), typeof(bill_back_amount), current_service_amount FROM bill_back_decisions"
            ).fetchone()
        self.assertEqual(row, ("text", "text", "294.41"))


class TestP6EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.db = folder / "autostack.db"
        self.rent = folder / "rent.json"
        self.aura_db = folder / "aura.db"

        common = ["HSEB", "HSEE", "HSEG", "BLDG F LIGHTS", "BLDG C LIGHTS",
                  "BLDG D LIGHTS", "JLNDY", "HSEO", "KLNDY"]
        units = {f"V{i}": {"status": "Vacant-Unrented"} for i in range(29)}
        units.update({u: {"tenant": "Test tenant " + u, "status": "Current", "move_in": "2026-07-25"}
                      for u in ("D6", "H1")})
        self.rent.write_text(json.dumps({"Wingate Apartments": {"units": units}}), encoding="utf-8")

        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(SCHEMA)
            rows = [(f"vacant-{i}", f"V{i}", f"test-{i}", "10.00", "READY") for i in range(29)]
            rows += [(f"common-{i}", unit, f"common-{i}", "10.00", "READY") for i, unit in enumerate(common)]
            rows += [
                ("4f5f68bc-a316-4884-98cd-b5c2819f067d", "D6", "9385974335", "333.66", "READY"),
                ("b7fc2eee-be22-4044-bd23-8aa42819c5a6", "H1", "1006974233", "321.70", "READY"),
                ("wm-unresolved", "X", "wm-1", "10.00", "READY"),
            ]
            for invoice_id, unit, account, amount, status in rows:
                vendor = "WM" if invoice_id == "wm-unresolved" else "GEORGIA_POWER"
                property_code = "Wingate Apartments" if vendor == "WM" else "WG-4735-" + unit
                conn.execute(
                    "INSERT INTO invoices (id,sha256,file_name,source_type,status,vendor_code,account_number,property_code,received_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (invoice_id, invoice_id, "fixture.pdf", "EMAIL", status, vendor, account, property_code, "2026-08-25"),
                )
                conn.execute(
                    "INSERT INTO utility_invoice_details (invoice_id,vendor_code,account_number,service_period_start,service_period_end,amount,current_service_amount,total_due) VALUES (?,?,?,?,?,?,?,?)",
                    (invoice_id, vendor, account, "2026-07-21", "2026-08-23", "999.00", amount, "999.00"),
                )
            conn.commit()

        self.config = AuraRuntimeConfig(self.db, self.rent, ROOT / "config/utility_rules.json")
        self.run = create_service(self.config).run()
        rules = load_rules_metadata(ROOT / "config/utility_rules.json")
        self.repo = SqliteBillBackDecisionRepository(self.aura_db)
        self.persistence = PersistBillBackDecisions(
            BillBackDecisionFactory(rules, clock=lambda: FIXED_TIME), self.repo
        )

    def test_run_twice_is_idempotent_and_preserves_validated_billbacks(self):
        first = self.persistence.execute(self.run)
        second = self.persistence.execute(self.run)
        self.assertEqual(len(first.decisions), 40)
        self.assertEqual(len(second.decisions), 40)
        self.assertEqual(len(self.repo.list_all()), 40)

        active = self.repo.list_active()
        self.assertEqual(len(active), 40)
        counts = {status: sum(d.classification is status for d in active)
                  for status in (AuditStatus.VACANT, AuditStatus.COMMON_AREA, AuditStatus.BILLABLE)}
        self.assertEqual(counts, {
            AuditStatus.VACANT: 29,
            AuditStatus.COMMON_AREA: 9,
            AuditStatus.BILLABLE: 2,
        })
        billable = {d.unit_name: d.bill_back_amount for d in active if d.classification is AuditStatus.BILLABLE}
        self.assertEqual(billable, {"D6": Decimal("294.41"), "H1": Decimal("283.85")})
        self.assertEqual(sum(billable.values(), Decimal("0.00")), Decimal("578.26"))
        self.assertFalse(any(d.invoice_id == "wm-unresolved" for d in active))


class TestRulesMetadata(unittest.TestCase):
    def test_real_rules_are_versioned_and_hashed(self):
        metadata = load_rules_metadata(ROOT / "config/utility_rules.json")
        self.assertEqual(metadata.rule_version, "1")
        self.assertEqual(len(metadata.rules_hash), 64)


if __name__ == "__main__":
    unittest.main()
