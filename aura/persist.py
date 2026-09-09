"""Calculate through P5.6, then persist P6 bill-back decisions into AURA-owned SQLite."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path

from src.adapters.sqlite_billback_decision_repository import SqliteBillBackDecisionRepository
from src.application.billback_decision_factory import BillBackDecisionFactory
from src.application.persist_billback_decisions import PersistBillBackDecisions
from src.application.rules_metadata import load_rules_metadata
from src.domain.models import AuditStatus
from src.runtime.run_billbacks import AuraRuntimeConfig, create_service


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autostack-db", default=os.environ.get("AUTOSTACK_DB_PATH", "storage/autostack.db"))
    parser.add_argument("--aura-db", default=os.environ.get("AURA_DB_PATH", "storage/aura.db"))
    parser.add_argument("--rent-roll", default=os.environ.get("RENT_ROLL_PATH", "data/02_appfolio_reports/rent_roll.csv"))
    parser.add_argument("--utility-rules", default=os.environ.get("UTILITY_RULES_PATH", "config/utility_rules.json"))
    args = parser.parse_args(argv)

    config = AuraRuntimeConfig(Path(args.autostack_db), Path(args.rent_roll), Path(args.utility_rules))
    run = create_service(config).run()
    rules = load_rules_metadata(args.utility_rules)
    repository = SqliteBillBackDecisionRepository(args.aura_db)
    before_count = len(repository.list_all())
    persisted = PersistBillBackDecisions(BillBackDecisionFactory(rules), repository).execute(run)
    after_count = len(repository.list_all())
    active = repository.list_active()
    summary = {
        "processed_decisions": len(persisted.decisions),
        "created_decisions": after_count - before_count,
        "active_decisions": len(active),
        "statuses": dict(Counter(d.classification.name for d in active)),
        "active_billable_total": str(sum(
            (d.bill_back_amount for d in active if d.classification is AuditStatus.BILLABLE),
            Decimal("0.00"),
        )),
        "aura_db": str(Path(args.aura_db)),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
