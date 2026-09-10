"""Runtime wiring regression; synthetic fixture is not proof of the live dataset."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import Mock

from src.application.billback_service import BillBackService
from src.runtime.run_billbacks import AuraRuntimeConfig, create_service, main, summarize
from test.test_p5_autostack_sqlite_adapter import SCHEMA


ROOT = Path(__file__).resolve().parents[1]


def assert_p56(case, run):
    identities = [i for i in run.identities if i.invoice.vendor_code == "GEORGIA_POWER"]
    ids = {i.invoice.invoice_id for i in identities}
    results = [r for r in run.results if r.request.invoice.invoice_id in ids]
    case.assertEqual(run.selection, "canonical")
    case.assertEqual(len(identities), 40)
    case.assertEqual(sum(i.audit_eligible for i in identities), 40)
    case.assertEqual(sum(i.identity_type.value == "UNIT" for i in identities), 31)
    case.assertEqual(sum(i.identity_type.value == "COMMON_AREA" for i in identities), 9)
    case.assertFalse([r for r in run.rejected if r[0] in ids])
    case.assertEqual(len(results), 40)
    case.assertEqual(sum(r.status.name == "VACANT" for r in results), 29)
    case.assertEqual(sum(r.status.name == "COMMON_AREA" for r in results), 9)
    billable = [r for r in results if r.status.name == "BILLABLE"]
    case.assertEqual(len(billable), 2)
    case.assertEqual({(r.request.invoice.invoice_id, r.request.invoice.account_number,
                       r.request.property.unit_name): r.calculated_bill_back for r in billable}, {
        ("4f5f68bc-a316-4884-98cd-b5c2819f067d", "9385974335", "D6"): Decimal("294.41"),
        ("b7fc2eee-be22-4044-bd23-8aa42819c5a6", "1006974233", "H1"): Decimal("283.85"),
    })
    case.assertEqual(sum((r.calculated_bill_back for r in results), Decimal("0.00")), Decimal("578.26"))


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = self.folder / "facts #1.db"
        self.rent = self.folder / "rent.json"
        common = ["HSEB", "HSEE", "HSEG", "BLDG F LIGHTS", "BLDG C LIGHTS",
                  "BLDG D LIGHTS", "JLNDY", "HSEO", "KLNDY"]
        units = {f"V{i}": {"status": "Vacant-Unrented"} for i in range(29)}
        units.update({u: {"tenant": "Test tenant " + u, "status": "Current",
                          "move_in": "2026-07-25"} for u in ("D6", "H1")})
        self.rent.write_text(json.dumps({"Wingate Apartments": {"units": units}}), encoding="utf-8")
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(SCHEMA)
            rows = [(f"vacant-{i}", f"V{i}", f"test-{i}", "10.00", "READY") for i in range(29)]
            rows += [(f"common-{i}", unit, f"common-{i}", "10.00", "READY") for i, unit in enumerate(common)]
            # Partial occupancy: 30 of 34 days; service charge != total due.
            rows += [("4f5f68bc-a316-4884-98cd-b5c2819f067d", "D6", "9385974335", "333.66", "READY"),
                     ("b7fc2eee-be22-4044-bd23-8aa42819c5a6", "H1", "1006974233", "321.70", "READY"),
                     ("review-only", "V0", "8923974278", "10.00", "REVIEW_REQUIRED")]
            for invoice_id, unit, account, amount, status in rows:
                conn.execute("INSERT INTO invoices (id,sha256,file_name,source_type,status,vendor_code,account_number,property_code,received_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (invoice_id, invoice_id, "fixture.pdf", "EMAIL", status, "GEORGIA_POWER", account, "WG-4735-" + unit, "2026-08-25"))
                conn.execute("INSERT INTO utility_invoice_details (invoice_id,vendor_code,account_number,service_period_start,service_period_end,amount,current_service_amount,total_due) VALUES (?,?,?,?,?,?,?,?)",
                             (invoice_id, "GEORGIA_POWER", account, "2026-07-21", "2026-08-23", "999.00", amount, "999.00"))
            conn.commit()
        self.config = AuraRuntimeConfig(self.db, self.rent, ROOT / "config/utility_rules.json")

    def test_synthetic_runtime_regression_through_sqlite(self):
        run = create_service(self.config).run()
        assert_p56(self, run)
        self.assertFalse(any(r.anomalies for r in run.results))

    def test_exact_snapshot_does_not_weaken_canonical_policy(self):
        service = create_service(self.config)
        self.assertEqual(len(service.run().identities), 40)
        exact = service.run(invoice_id="review-only", facts_version=1)
        self.assertEqual(len(exact.results), 1)
        self.assertEqual(exact.selection, "exact")
        self.assertIsNone(summarize(exact)["canonical_count"])
        with self.assertRaises(LookupError):
            service.run(invoice_id="review-only", facts_version=2)

    def test_port_methods_are_exclusive(self):
        port = Mock()
        port.list_canonical_snapshots.return_value = ()
        service = BillBackService(port, Mock(), Mock(), Mock())
        service.run()
        port.list_canonical_snapshots.assert_called_once_with()
        port.get_exact_snapshot.assert_not_called()
        with self.assertRaises(ValueError):
            service.run(invoice_id="x")

    def test_missing_current_charge_is_rejected_not_replaced(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE utility_invoice_details SET current_service_amount=NULL WHERE invoice_id='review-only'")
            conn.commit()
        run = create_service(self.config).run(invoice_id="review-only", facts_version=1)
        self.assertEqual(run.results, ())
        self.assertEqual(run.rejected, (("review-only", "Missing current_service_amount"),))

    def test_unresolved_identity_is_visible_and_not_audited(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE invoices SET property_code='UNKNOWN' WHERE id='review-only'")
            conn.commit()
        run = create_service(self.config).run(invoice_id="review-only", facts_version=1)
        self.assertEqual(run.results, ())
        self.assertEqual(run.rejected[0][1], "PROPERTY_UNRESOLVED")

    def test_cli_and_environment_use_same_application(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"AUTOSTACK_DB_PATH": str(self.db),
                                   "RENT_ROLL_PATH": str(self.rent),
                                   "UTILITY_RULES_PATH": str(self.config.utility_rules_path)}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([]), 0)
            self.assertEqual(json.loads(output.getvalue())["total_bill_back"], "578.26")

    def test_invalid_startup_config_fails(self):
        with self.assertRaisesRegex(ValueError, "autostack_db_path"):
            create_service(AuraRuntimeConfig(self.folder / "missing.db", self.rent,
                                             self.config.utility_rules_path))
        self.assertFalse((self.folder / "missing.db").exists())

    def test_csv_keeps_non_revenue_units_and_uses_move_out_not_lease_end(self):
        csv_path = self.folder / "rent.csv"
        catalog = json.loads(self.rent.read_text(encoding="utf-8"))["Wingate Apartments"]["units"]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Unit", "Tenant", "Status", "Move-in", "Move-out", "Lease To"])
            writer.writerow(["-> Wingate Apartments", "", "", "", "", ""])
            for unit, details in catalog.items():
                writer.writerow([unit, details.get("tenant", ""), details["status"],
                                 details.get("move_in", ""), "", "01/01/2026"])
            writer.writerow(["NR1", "", "Non-Revenue", "", "", ""])
        from src.adapters.rent_roll_csv_adapter import load_rent_roll_csv
        contexts = load_rent_roll_csv(csv_path)
        self.assertEqual(len(contexts), 32)
        self.assertTrue(any(p.unit_name == "NR1" for p, _ in contexts.values()))
        run = create_service(AuraRuntimeConfig(self.db, csv_path, self.config.utility_rules_path)).run()
        assert_p56(self, run)

    def test_csv_rejects_duplicate_unit_instead_of_overwriting_tenant(self):
        from src.adapters.rent_roll_csv_adapter import load_rent_roll_csv
        path = self.folder / "duplicate.csv"
        path.write_text("Unit,Tenant,Status,Move-in,Move-out\n-> Wingate Apartments,,,,\nD6,One,Current,2026-01-01,\nD6,Two,Current,2026-02-01,\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_rent_roll_csv(path)


@unittest.skipUnless(os.environ.get("P56_REGRESSION_DB_PATH"), "Set P56_REGRESSION_DB_PATH for the real acceptance dataset")
class TestRealP56Acceptance(unittest.TestCase):
    def test_validated_georgia_power_dataset(self):
        config = AuraRuntimeConfig(Path(os.environ["P56_REGRESSION_DB_PATH"]),
                                   Path(os.environ.get("RENT_ROLL_PATH", ROOT / "data/02_appfolio_reports/rent_roll.csv")),
                                   Path(os.environ.get("UTILITY_RULES_PATH", ROOT / "config/utility_rules.json")))
        assert_p56(self, create_service(config).run())
