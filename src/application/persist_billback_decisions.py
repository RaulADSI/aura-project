"""P6 application service: persist decisions from an already-computed BillBackRun."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.application.billback_decision_factory import BillBackDecisionFactory
from src.application.billback_service import BillBackRun
from src.domain.billback_decision import BillBackDecision
from src.domain.models import AuditStatus
from src.ports.billback_decisions import BillBackDecisionRepository


@dataclass(frozen=True)
class BillBackPersistenceResult:
    decisions: tuple[BillBackDecision, ...]

    @property
    def total_billable(self) -> Decimal:
        return sum(
            (d.bill_back_amount for d in self.decisions if d.classification is AuditStatus.BILLABLE),
            Decimal("0.00"),
        )


class PersistBillBackDecisions:
    def __init__(self, factory: BillBackDecisionFactory, repository: BillBackDecisionRepository) -> None:
        self.factory = factory
        self.repository = repository

    def execute(self, run: BillBackRun) -> BillBackPersistenceResult:
        stored = tuple(self.repository.save(decision) for decision in self.factory.from_run(run))
        return BillBackPersistenceResult(stored)
