"""Build P7 operational summaries from persisted decision read models only."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from src.application.billback_decision_query_service import BillBackDecisionReadModel


@dataclass(frozen=True)
class BillableSummaryItem:
    invoice_id: str
    property: str
    unit: str
    tenant: str | None
    amount: Decimal


@dataclass(frozen=True)
class OperationalSummary:
    active_decisions: int
    statuses: dict[str, int]
    active_billable_total: Decimal
    billable: tuple[BillableSummaryItem, ...]


def build_operational_summary(
    decisions: tuple[BillBackDecisionReadModel, ...],
) -> OperationalSummary:
    counts = Counter(decision.classification for decision in decisions)
    billable_decisions = tuple(d for d in decisions if d.classification == "BILLABLE")
    total = sum((d.bill_back_amount for d in billable_decisions), Decimal("0.00"))
    billable = tuple(
        BillableSummaryItem(
            invoice_id=d.invoice_id,
            property=d.property,
            unit=d.unit,
            tenant=d.tenant,
            amount=d.bill_back_amount,
        )
        for d in billable_decisions
    )
    return OperationalSummary(
        active_decisions=len(decisions),
        statuses=dict(counts),
        active_billable_total=total,
        billable=billable,
    )
