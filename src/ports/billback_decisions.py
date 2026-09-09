"""Output port for durable AURA bill-back decisions."""
from __future__ import annotations

from typing import Protocol, Sequence

from src.domain.billback_decision import BillBackDecision


class BillBackDecisionRepository(Protocol):
    def save(self, decision: BillBackDecision) -> BillBackDecision:
        ...

    def find_by_provenance(
        self, invoice_id: str, source_facts_version: int, rule_version: str
    ) -> BillBackDecision | None:
        ...

    def list_active(self) -> Sequence[BillBackDecision]:
        ...
