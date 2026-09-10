"""JSON delivery adapter for the P7 operational summary contract."""
from __future__ import annotations

import json
from pathlib import Path

from src.application.operational_summary import OperationalSummary


class JsonBillBackSummaryExporter:
    def export(self, summary: OperationalSummary, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_decisions": summary.active_decisions,
            "statuses": summary.statuses,
            "active_billable_total": format(summary.active_billable_total, ".2f"),
            "billable": [
                {
                    "invoice_id": item.invoice_id,
                    "property": item.property,
                    "unit": item.unit,
                    "tenant": item.tenant,
                    "amount": format(item.amount, ".2f"),
                }
                for item in summary.billable
            ],
        }
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return output
