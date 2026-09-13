import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.adapters.autostack_sqlite_adapter import (
    AutoStackSqliteAdapter,
    AutoStackSqliteContractError,
)
from src.ports.invoice_facts import InvoiceFactsNotFoundError


SCHEMA = """
CREATE TABLE invoices (
 id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL,
 source_type TEXT NOT NULL, status TEXT NOT NULL, vendor_code TEXT,
 account_number TEXT, invoice_number TEXT, invoice_date TEXT, amount REAL,
 assessment_status TEXT, overall_confidence REAL, property_code TEXT,
 appfolio_email TEXT, sender_email_key TEXT, routing_reason TEXT,
 review_reason TEXT, received_at TEXT NOT NULL, processed_at TEXT,
 dispatched_at TEXT, dispatch_attempts INTEGER NOT NULL DEFAULT 0,
 dispatch_claimed_at TEXT, last_dispatch_error TEXT
);
CREATE TABLE utility_invoice_details (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id TEXT NOT NULL UNIQUE,
 vendor_code TEXT NOT NULL,
 bill_type TEXT,
 account_number TEXT,
 service_period_start DATE,
 service_period_end DATE,
 amount DECIMAL(10,2),
 previous_bill_amount DECIMAL(10,2),
 payment_received_amount DECIMAL(10,2),
 past_due_amount DECIMAL(10,2),
 current_service_amount DECIMAL(10,2),
 total_due DECIMAL(10,2),
 raw_billing_summary TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(invoice_id) REFERENCES invoices(id)
);
"""


class TestAutoStackSqliteAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "autostack.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_invoice(self, *, invoice_id="inv-1", status="READY", amount=Decimal("10.00"),
                        detail=True, detail_amount=Decimal("10.00"), current=None, total=None,
                        account="A-1"):
        conn = sqlite3.connect(self.db)
        conn.execute(
            """INSERT INTO invoices
               (id,sha256,file_name,source_type,status,vendor_code,account_number,
                invoice_number,invoice_date,amount,received_at,property_code)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (invoice_id, f"sha-{invoice_id}", "x.pdf", "EMAIL", status, "FPL",
             account, "N-1", "2026-09-01", str(amount) if amount is not None else None,
             "2026-09-01T00:00:00Z", "PROP-1"),
        )
        if detail:
            conn.execute(
                """INSERT INTO utility_invoice_details
                   (invoice_id,vendor_code,account_number,service_period_start,
                    service_period_end,amount,current_service_amount,total_due)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (invoice_id, "FPL", account, 1785560400000, 1788152400000,
                 str(detail_amount) if detail_amount is not None else None,
                 str(current) if current is not None else None,
                 str(total) if total is not None else None),
            )
        conn.commit()
        conn.close()

    def test_ready_valid_facts_exact_and_canonical(self):
        self._insert_invoice(current=Decimal("7.50"), total=Decimal("10.00"))
        adapter = AutoStackSqliteAdapter(self.db)
        exact = adapter.get_exact_snapshot("inv-1", 1)
        self.assertEqual(exact.invoice_amount, Decimal("10"))
        self.assertEqual(exact.current_service_amount, Decimal("7.5"))
        self.assertEqual(exact.total_due, Decimal("10"))
        self.assertEqual(len(adapter.list_canonical_snapshots()), 1)

    def test_amount_zero_is_preserved_not_missing(self):
        self._insert_invoice(amount=Decimal("0.00"), detail_amount=Decimal("0.00"))
        dto = AutoStackSqliteAdapter(self.db).get_exact_snapshot("inv-1", 1)
        self.assertEqual(dto.invoice_amount, Decimal("0"))

    def test_missing_detail_facts_not_found_and_excluded(self):
        self._insert_invoice(detail=False)
        adapter = AutoStackSqliteAdapter(self.db)
        with self.assertRaises(InvoiceFactsNotFoundError):
            adapter.get_exact_snapshot("inv-1", 1)
        self.assertEqual(adapter.list_canonical_snapshots(), ())

    def test_missing_required_detail_amount_is_structural_error_and_excluded(self):
        self._insert_invoice(detail_amount=None)
        adapter = AutoStackSqliteAdapter(self.db)
        with self.assertRaises(AutoStackSqliteContractError):
            adapter.get_exact_snapshot("inv-1", 1)
        self.assertEqual(adapter.list_canonical_snapshots(), ())

    def test_exact_lookup_ignores_operational_status(self):
        self._insert_invoice(status="REVIEW_REQUIRED")
        adapter = AutoStackSqliteAdapter(self.db)
        self.assertEqual(adapter.get_exact_snapshot("inv-1", 1).invoice_id, "inv-1")
        self.assertEqual(adapter.list_canonical_snapshots(), ())

    def test_failed_and_dead_are_excluded(self):
        self._insert_invoice(invoice_id="failed", status="FAILED")
        self._insert_invoice(invoice_id="dead", status="DEAD")
        self.assertEqual(AutoStackSqliteAdapter(self.db).list_canonical_snapshots(), ())

    def test_dispatched_is_canonical_for_current_real_schema(self):
        self._insert_invoice(status="DISPATCHED")
        snapshots = AutoStackSqliteAdapter(self.db).list_canonical_snapshots()
        self.assertEqual([s.invoice_id for s in snapshots], ["inv-1"])

    def test_nonexistent_version_is_not_found_not_latest(self):
        self._insert_invoice()
        with self.assertRaises(InvoiceFactsNotFoundError):
            AutoStackSqliteAdapter(self.db).get_exact_snapshot("inv-1", 2)

    def test_current_service_missing_does_not_fallback_to_total_due(self):
        self._insert_invoice(current=None, total=Decimal("10.00"))
        dto = AutoStackSqliteAdapter(self.db).get_exact_snapshot("inv-1", 1)
        self.assertIsNone(dto.current_service_amount)
        self.assertEqual(dto.total_due, Decimal("10"))

    def test_account_missing_is_rejected(self):
        self._insert_invoice(account=None)
        adapter = AutoStackSqliteAdapter(self.db)
        with self.assertRaises(AutoStackSqliteContractError):
            adapter.get_exact_snapshot("inv-1", 1)
        self.assertEqual(adapter.list_canonical_snapshots(), ())

    def test_gp_final_preserves_metadata_without_changing_eligibility(self):
        from contextlib import closing
        for status in ("READY", "DISPATCHING", "DISPATCHED", "REVIEW_REQUIRED"):
            self._insert_invoice(invoice_id=status, status=status,
                                 current=Decimal("136.98"), total=Decimal("420.83"))
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE utility_invoice_details SET vendor_code='GEORGIA_POWER', bill_type='FINAL'")
            conn.execute("UPDATE invoices SET vendor_code='GEORGIA_POWER', invoice_number=NULL, invoice_date=NULL")
            conn.commit()
        adapter = AutoStackSqliteAdapter(self.db)
        self.assertEqual({x.invoice_id for x in adapter.list_canonical_snapshots()},
                         {"READY", "DISPATCHING", "DISPATCHED"})
        for status in ("READY", "DISPATCHING", "DISPATCHED", "REVIEW_REQUIRED"):
            snapshot = adapter.get_exact_snapshot(status, 1)
            self.assertEqual(snapshot.bill_type, "FINAL")
            self.assertEqual(snapshot.current_service_amount, Decimal("136.98"))
            self.assertEqual(snapshot.total_due, Decimal("420.83"))
            self.assertIsNone(snapshot.invoice_number)
            self.assertIsNone(snapshot.invoice_date)

    def test_bill_type_absent_blank_and_unknown_are_not_inferred(self):
        from contextlib import closing
        self._insert_invoice()
        adapter = AutoStackSqliteAdapter(self.db)
        for value, expected in ((None, None), ("", None), ("  ", None), ("STANDARD", "STANDARD"), ("CORRECTED_FINAL", "CORRECTED_FINAL"), (" corrected_Final ", " corrected_Final ")):
            with self.subTest(value=value):
                with closing(sqlite3.connect(self.db)) as conn:
                    conn.execute("UPDATE utility_invoice_details SET bill_type=?, raw_billing_summary='FINAL BILL'", (value,))
                    conn.commit()
                self.assertEqual(adapter.get_exact_snapshot("inv-1", 1).bill_type, expected)
                self.assertEqual(adapter.list_canonical_snapshots()[0].bill_type, expected)

    def test_gas_south_review_is_excluded_and_new_charges_are_not_current_service(self):
        from contextlib import closing
        self._insert_invoice(status="REVIEW_REQUIRED", current=None, total=Decimal("330.37"))
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("ALTER TABLE utility_invoice_details ADD COLUMN new_charges_amount DECIMAL(10,2)")
            conn.execute("UPDATE invoices SET vendor_code='GAS_SOUTH'")
            conn.execute("UPDATE utility_invoice_details SET vendor_code='GAS_SOUTH', new_charges_amount=35.96, raw_billing_summary='current_service_amount=35.96; reconciled=true'")
            conn.commit()
        adapter = AutoStackSqliteAdapter(self.db)
        self.assertEqual(adapter.list_canonical_snapshots(), ())
        snapshot = adapter.get_exact_snapshot("inv-1", 1)
        self.assertIsNone(snapshot.current_service_amount)
        self.assertIsNone(snapshot.bill_type)

    def test_legacy_schema_without_bill_type_remains_readable(self):
        from contextlib import closing
        self._insert_invoice()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("ALTER TABLE utility_invoice_details DROP COLUMN bill_type")
            conn.commit()
        adapter = AutoStackSqliteAdapter(self.db)
        self.assertIsNone(adapter.get_exact_snapshot("inv-1", 1).bill_type)
        self.assertIsNone(adapter.list_canonical_snapshots()[0].bill_type)


if __name__ == "__main__":
    unittest.main()
