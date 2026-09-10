"""AutoStack DB -> AURA -> bill-back, without intermediate invoice files."""
import argparse
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

from src.adapters.appfolio_adapter import AppFolioAdapter
from src.adapters.rent_roll_csv_adapter import load_rent_roll_csv
from src.adapters.autostack_sqlite_adapter import AutoStackSqliteAdapter
from src.adapters.property_resolver import PropertyResolver
from src.adapters.unit_resolver import UnitResolver
from src.adapters.structured_audit_request_builder import StructuredAuditRequestBuilder
from src.application.billback_service import BillBackService
from src.auditor import AuditEngine
from src.integration_autostack import AutoStackRoutingIdentityAdapter, CommonAreaClassifier


@dataclass(frozen=True)
class AuraRuntimeConfig:
    autostack_db_path: Path
    rent_roll_path: Path
    utility_rules_path: Path

    def validate(self):
        for name in ("autostack_db_path", "rent_roll_path", "utility_rules_path"):
            if not Path(getattr(self, name)).is_file():
                raise ValueError(f"{name}: file not found: {getattr(self, name)}")


def create_service(config: AuraRuntimeConfig) -> BillBackService:
    config.validate()
    rent_path = Path(config.rent_roll_path)
    contexts = (load_rent_roll_csv(rent_path) if rent_path.suffix.lower() == ".csv"
                else AppFolioAdapter(str(rent_path.parent)).load_rent_roll_contexts(rent_path.name))
    if not contexts:
        raise ValueError("Rent roll contains no unit contexts")
    units = {}
    for prop, _ in contexts.values():
        units.setdefault(prop.property_name, []).append(prop.unit_name)
    classifier = CommonAreaClassifier.from_rules_file(config.utility_rules_path)
    port = AutoStackSqliteAdapter(config.autostack_db_path)
    identity = AutoStackRoutingIdentityAdapter(port, PropertyResolver(units),
                                             UnitResolver(units), classifier)
    return BillBackService(port, identity, StructuredAuditRequestBuilder(contexts),
                           AuditEngine(str(config.utility_rules_path)))


def summarize(run):
    return {
        "selection": run.selection,
        "snapshot_count": len(run.identities),
        "canonical_count": len(run.identities) if run.selection == "canonical" else None,
        "identity_classified": sum(i.audit_eligible for i in run.identities),
        "identity_types": dict(Counter(i.identity_type.value for i in run.identities if i.identity_type)),
        "vendors": dict(Counter(i.invoice.vendor_code for i in run.identities)),
        "snapshots": [dict(invoice_id=i.invoice.invoice_id, facts_id=i.invoice.facts_id,
                           facts_version=i.invoice.facts_version, vendor=i.invoice.vendor_code,
                           eligibility=i.eligibility.value) for i in run.identities],
        "statuses": dict(Counter(r.status.name for r in run.results)),
        "total_bill_back": str(sum((r.calculated_bill_back for r in run.results), Decimal("0.00"))),
        "rejected": [{"invoice_id": i, "reason": reason} for i, reason in run.rejected],
        "results": [dict(invoice_id=r.request.invoice.invoice_id,
                         account_number=r.request.invoice.account_number,
                         property=r.request.property.property_name,
                         unit=r.request.property.unit_name, tenant=r.request.occupancy.tenant_name,
                         status=r.status.name, bill_back=str(r.calculated_bill_back),
                         anomalies=[a.name for a in r.anomalies]) for r in run.results],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autostack-db", default=os.environ.get("AUTOSTACK_DB_PATH", "storage/autostack.db"))
    parser.add_argument("--rent-roll", default=os.environ.get("RENT_ROLL_PATH", "data/02_appfolio_reports/rent_roll.csv"))
    parser.add_argument("--utility-rules", default=os.environ.get("UTILITY_RULES_PATH", "config/utility_rules.json"))
    parser.add_argument("--invoice", help="Exact AutoStack invoice_id (not account number)")
    parser.add_argument("--facts-version", type=int)
    args = parser.parse_args(argv)
    if (args.invoice is None) != (args.facts_version is None):
        parser.error("--invoice and --facts-version must be supplied together")
    try:
        service = create_service(AuraRuntimeConfig(Path(args.autostack_db), Path(args.rent_roll), Path(args.utility_rules)))
        run = service.run(invoice_id=args.invoice, facts_version=args.facts_version)
    except (ValueError, OSError, LookupError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(summarize(run), indent=2, ensure_ascii=True))
    return 1 if run.rejected or any(r.anomalies for r in run.results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
