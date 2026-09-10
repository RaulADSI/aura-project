"""P7 application query service over persisted ACTIVE bill-back decisions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.domain.billback_decision import BillBackDecision
from src.ports.billback_decision_reader import BillBackDecisionReader


@dataclass(frozen=True)
class BillBackDecisionReadModel:
    invoice_id: str
    property: str
    unit: str
    tenant: str | None
    vendor: str
    account_number: str
    service_period_start: date
    service_period_end: date
    bill_back_amount: Decimal
    classification: str
    decision_reason: str
    rule_version: str
    rules_hash: str
    source_facts_id: str
    source_facts_version: int
    decision_version: int
    decision_id: str
    decided_at: datetime


class BillBackDecisionQueryService:
    def __init__(self, reader: BillBackDecisionReader) -> None:
        self.reader = reader

    def list_active(self) -> tuple[BillBackDecisionReadModel, ...]:
        return tuple(self._to_read_model(decision) for decision in self.reader.list_active())

    @staticmethod
    def _to_read_model(decision: BillBackDecision) -> BillBackDecisionReadModel:
        return BillBackDecisionReadModel(
            invoice_id=decision.invoice_id,
            property=decision.property_name,
            unit=decision.unit_name,
            tenant=decision.tenant_name,
            vendor=decision.vendor,
            account_number=decision.account_number,
            service_period_start=decision.service_period_start,
            service_period_end=decision.service_period_end,
            bill_back_amount=decision.bill_back_amount,
            classification=decision.classification.name,
            decision_reason=decision.decision_reason,
            rule_version=decision.rule_version,
            rules_hash=decision.rules_hash,
            source_facts_id=decision.source_facts_id,
            source_facts_version=decision.source_facts_version,
            decision_version=decision.decision_version,
            decision_id=decision.decision_id,
            decided_at=decision.decided_at,
        )
