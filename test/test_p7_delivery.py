import csv
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from aura.deliver import main as deliver_main
from src.adapters.sqlite_billback_decision_reader import SqliteBillBackDecisionReader
from src.adapters.sqlite_billback_decision_repository import SqliteBillBackDecisionRepository
from src.application.billback_decision_query_service import BillBackDecisionQueryService
from src.application.operational_summary import build_operational_summary
from src.delivery.csv_exporter import CSV_FIELDS, CsvBillBackExporter
from src.delivery.json_exporter import JsonBillBackSummaryExporter
from src.domain.billback_decision import BillBackDecision, DecisionStatus
from src.domain.models import AuditStatus

FIXED_TIME = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def make_decision(
    index: int,
    *,
    classification: AuditStatus,
    amount: str,
    unit: str,
    tenant: str | None = None,
    decision_status: DecisionStatus = DecisionStatus.ACTIVE,
) -> BillBackDecision:
    return BillBackDecision(
        decision_id=f"decision-{index}",
        invoice_id=f"invoice-{index}",
        source_facts_id=f"facts-{index}",
        source_facts_version=1,
        rule_version="1",
        rules_hash="a" * 64,
        decision_version=1,
        vendor="GEORGIA_POWER",
        account_number=f"account-{index}",
        property_name="Wingate Apartments",
        unit_name=unit,
        tenant_name=tenant,
        service_period_start=date(2026, 7, 22),
        service_period_end=date(2026, 8, 24),
        current_service_amount=Decimal(amount) if classification is AuditStatus.BILLABLE else Decimal("10.00"),
        occupied_days=34 if classification is AuditStatus.BILLABLE else 0,
        total_service_days=34,
        bill_back_amount=Decimal(amount),
        classification=classification,
        decision_reason=classification.name,
        decision_status=decision_status,
        decided_at=FIXED_TIME,
    )


class P7Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "aura.db"
        self.out = self.root / "delivery"
        self.repo = SqliteBillBackDecisionRepository(self.db)

    def seed_acceptance_dataset(self):
        for i in range(28):
            self.repo.save(make_decision(i, classification=AuditStatus.VACANT, amount="0.00", unit=f"V{i}"))
        for i in range(28, 36):
            self.repo.save(make_decision(i, classification=AuditStatus.COMMON_AREA, amount="0.00", unit=f"COMMON-{i}"))
        self.repo.save(make_decision(36, classification=AuditStatus.BILLABLE, amount="294.41", unit="D6", tenant="Jasmine L. Wilson"))
        self.repo.save(make_decision(37, classification=AuditStatus.BILLABLE, amount="283.85", unit="H1", tenant="Shunterica N. Thomas"))


class TestSqliteBillBackDecisionReader(P7Fixture):
    def test_reads_only_active_decisions(self):
        self.repo.save(make_decision(1, classification=AuditStatus.BILLABLE, amount="10.00", unit="A1", tenant="Tenant"))
        # New facts version supersedes the previous ACTIVE row for the same invoice.
        newer = make_decision(1, classification=AuditStatus.BILLABLE, amount="11.00", unit="A1", tenant="Tenant")
        object.__setattr__(newer, "decision_id", "decision-new")
        object.__setattr__(newer, "source_facts_id", "facts-new")
        object.__setattr__(newer, "source_facts_version", 2)
        self.repo.save(newer)

        active = SqliteBillBackDecisionReader(self.db).list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].bill_back_amount, Decimal("11.00"))
        self.assertEqual(active[0].decision_status, DecisionStatus.ACTIVE)

    def test_missing_database_fails_without_creating_it(self):
        missing = self.root / "missing.db"
        with self.assertRaises(FileNotFoundError):
            SqliteBillBackDecisionReader(missing)
        self.assertFalse(missing.exists())


class TestP7SummaryAndExports(P7Fixture):
    def setUp(self):
        super().setUp()
        self.seed_acceptance_dataset()
        self.decisions = BillBackDecisionQueryService(SqliteBillBackDecisionReader(self.db)).list_active()
        self.summary = build_operational_summary(self.decisions)

    def test_operational_summary_matches_p6_acceptance(self):
        self.assertEqual(self.summary.active_decisions, 38)
        self.assertEqual(self.summary.statuses, {"BILLABLE": 2, "COMMON_AREA": 8, "VACANT": 28})
        self.assertEqual(self.summary.active_billable_total, Decimal("578.26"))
        billable = {item.unit: item.amount for item in self.summary.billable}
        self.assertEqual(billable, {"D6": Decimal("294.41"), "H1": Decimal("283.85")})

    def test_csv_contains_complete_auditable_detail(self):
        path = CsvBillBackExporter().export(self.decisions, self.out / "bill_back_decisions.csv")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(tuple(rows[0].keys()), CSV_FIELDS)
        self.assertEqual(len(rows), 38)
        d6 = next(row for row in rows if row["unit"] == "D6")
        self.assertEqual(d6["tenant"], "Jasmine L. Wilson")
        self.assertEqual(d6["bill_back_amount"], "294.41")
        self.assertEqual(d6["classification"], "BILLABLE")
        self.assertEqual(d6["rule_version"], "1")
        self.assertEqual(d6["source_facts_version"], "1")
        self.assertEqual(d6["decision_version"], "1")

    def test_json_is_summary_contract_not_full_fact_copy(self):
        path = JsonBillBackSummaryExporter().export(self.summary, self.out / "bill_back_summary.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["active_decisions"], 38)
        self.assertEqual(payload["statuses"], {"BILLABLE": 2, "COMMON_AREA": 8, "VACANT": 28})
        self.assertEqual(payload["active_billable_total"], "578.26")
        self.assertEqual(
            {(row["unit"], row["amount"]) for row in payload["billable"]},
            {("D6", "294.41"), ("H1", "283.85")},
        )
        self.assertNotIn("current_service_amount", payload)


class TestP7RuntimeAcceptance(P7Fixture):
    def test_p6_db_to_p7_is_read_only_and_preserves_578_26(self):
        self.seed_acceptance_dataset()
        before_bytes = self.db.read_bytes()
        before_hash = hashlib.sha256(before_bytes).hexdigest()
        before_mtime = self.db.stat().st_mtime_ns

        exit_code = deliver_main(["--aura-db", str(self.db), "--output-dir", str(self.out)])
        self.assertEqual(exit_code, 0)

        after_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        after_mtime = self.db.stat().st_mtime_ns
        self.assertEqual(after_hash, before_hash)
        self.assertEqual(after_mtime, before_mtime)

        summary = json.loads((self.out / "bill_back_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["active_decisions"], 38)
        self.assertEqual(summary["active_billable_total"], "578.26")
        self.assertTrue((self.out / "bill_back_decisions.csv").is_file())

    def test_p7_modules_do_not_import_calculation_or_autostack_components(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "aura" / "deliver.py",
            root / "src" / "application" / "billback_decision_query_service.py",
            root / "src" / "application" / "operational_summary.py",
            root / "src" / "ports" / "billback_decision_reader.py",
            root / "src" / "adapters" / "sqlite_billback_decision_reader.py",
            root / "src" / "delivery" / "csv_exporter.py",
            root / "src" / "delivery" / "json_exporter.py",
        ]
        forbidden = (
            "AuditEngine",
            "BillBackService",
            "AutoStackSqliteAdapter",
            "InvoiceFactsPort",
            "autostack.db",
        )
        source = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for name in forbidden:
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
