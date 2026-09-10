"""CSV delivery adapter for the complete auditable bill-back decision detail."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from src.application.billback_decision_query_service import BillBackDecisionReadModel


CSV_FIELDS = (
    "invoice_id",
    "property",
    "unit",
    "tenant",
    "vendor",
    "account_number",
    "service_period_start",
    "service_period_end",
    "bill_back_amount",
    "classification",
    "decision_reason",
    "rule_version",
    "rules_hash",
    "source_facts_id",
    "source_facts_version",
    "decision_version",
    "decision_id",
    "decided_at",
)


class CsvBillBackExporter:
    def export(self, decisions: Sequence[BillBackDecisionReadModel], path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for d in decisions:
                writer.writerow({
                    "invoice_id": d.invoice_id,
                    "property": d.property,
                    "unit": d.unit,
                    "tenant": d.tenant or "",
                    "vendor": d.vendor,
                    "account_number": d.account_number,
                    "service_period_start": d.service_period_start.isoformat(),
                    "service_period_end": d.service_period_end.isoformat(),
                    "bill_back_amount": format(d.bill_back_amount, ".2f"),
                    "classification": d.classification,
                    "decision_reason": d.decision_reason,
                    "rule_version": d.rule_version,
                    "rules_hash": d.rules_hash,
                    "source_facts_id": d.source_facts_id,
                    "source_facts_version": d.source_facts_version,
                    "decision_version": d.decision_version,
                    "decision_id": d.decision_id,
                    "decided_at": d.decided_at.isoformat(),
                })
        return output
