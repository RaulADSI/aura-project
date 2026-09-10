"""P7 read-only delivery CLI for persisted AURA bill-back decisions."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.adapters.sqlite_billback_decision_reader import SqliteBillBackDecisionReader
from src.application.billback_decision_query_service import BillBackDecisionQueryService
from src.application.operational_summary import build_operational_summary
from src.delivery.csv_exporter import CsvBillBackExporter
from src.delivery.json_exporter import JsonBillBackSummaryExporter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aura-db", default=os.environ.get("AURA_DB_PATH", "storage/aura.db"))
    parser.add_argument("--output-dir", default=os.environ.get("AURA_DELIVERY_OUTPUT_DIR", "data/04_output"))
    args = parser.parse_args(argv)

    reader = SqliteBillBackDecisionReader(args.aura_db)
    decisions = BillBackDecisionQueryService(reader).list_active()
    summary = build_operational_summary(decisions)

    output_dir = Path(args.output_dir)
    csv_path = CsvBillBackExporter().export(decisions, output_dir / "bill_back_decisions.csv")
    json_path = JsonBillBackSummaryExporter().export(summary, output_dir / "bill_back_summary.json")

    result = {
        "active_decisions": summary.active_decisions,
        "statuses": summary.statuses,
        "active_billable_total": format(summary.active_billable_total, ".2f"),
        "csv": str(csv_path),
        "json": str(json_path),
        "aura_db": str(Path(args.aura_db)),
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
