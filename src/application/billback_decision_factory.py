"""Map completed P5.6 audit results to durable P6 decisions."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from src.application.billback_service import BillBackRun
from src.application.rules_metadata import RulesMetadata
from src.domain.billback_decision import BillBackDecision, DecisionStatus, PERSISTABLE_AUDIT_STATUSES


class BillBackDecisionFactory:
    def __init__(self, rules: RulesMetadata, *, clock=None) -> None:
        self.rules = rules
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def from_run(self, run: BillBackRun) -> tuple[BillBackDecision, ...]:
        identities = {identity.invoice.invoice_id: identity for identity in run.identities}
        decisions: list[BillBackDecision] = []

        for result in run.results:
            if result.status not in PERSISTABLE_AUDIT_STATUSES:
                continue
            invoice_id = result.request.invoice.invoice_id
            identity = identities.get(invoice_id)
            if identity is None:
                raise ValueError(f"Missing identity provenance for audit result {invoice_id}")
            snapshot = identity.invoice
            if snapshot.current_service_amount is None:
                raise ValueError(f"Missing current_service_amount for audited invoice {invoice_id}")
            if snapshot.service_period_start is None or snapshot.service_period_end is None:
                raise ValueError(f"Missing service period for audited invoice {invoice_id}")

            provenance = f"{invoice_id}|{snapshot.facts_version}|{self.rules.rule_version}"
            decision_id = str(uuid5(NAMESPACE_URL, f"aura:billback:{provenance}"))
            decisions.append(BillBackDecision(
                decision_id=decision_id,
                invoice_id=invoice_id,
                source_facts_id=snapshot.facts_id,
                source_facts_version=snapshot.facts_version,
                rule_version=self.rules.rule_version,
                rules_hash=self.rules.rules_hash,
                decision_version=1,  # repository assigns the historical sequence on first insert
                vendor=snapshot.vendor_code,
                account_number=snapshot.account_number,
                property_name=result.request.property.property_name,
                unit_name=result.request.property.unit_name,
                tenant_name=result.request.occupancy.tenant_name,
                service_period_start=snapshot.service_period_start,
                service_period_end=snapshot.service_period_end,
                current_service_amount=snapshot.current_service_amount,
                occupied_days=result.occupied_days,
                total_service_days=result.total_service_days,
                bill_back_amount=result.calculated_bill_back,
                classification=result.status,
                decision_reason=result.notes or result.status.name,
                decision_status=DecisionStatus.ACTIVE,
                decided_at=self._clock(),
            ))
        return tuple(decisions)
