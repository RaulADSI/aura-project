"""Durable AURA bill-back decision model.

P6 consumes a completed P5.6 BillBackRun.  It does not recalculate bill-back
logic; it records the deterministic business decision together with the
minimum provenance required to audit and reproduce it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from src.domain.models import AuditStatus, ZERO_MONEY, quantize_money


class DecisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


PERSISTABLE_AUDIT_STATUSES = frozenset({
    AuditStatus.BILLABLE,
    AuditStatus.VACANT,
    AuditStatus.COMMON_AREA,
})


def _require_nonblank(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


@dataclass(frozen=True)
class BillBackDecision:
    decision_id: str

    invoice_id: str
    source_facts_id: str
    source_facts_version: int

    rule_version: str
    rules_hash: str
    decision_version: int

    vendor: str
    account_number: str
    property_name: str
    unit_name: str
    tenant_name: str | None

    service_period_start: date
    service_period_end: date
    current_service_amount: Decimal
    occupied_days: int
    total_service_days: int
    bill_back_amount: Decimal

    classification: AuditStatus
    decision_reason: str
    decision_status: DecisionStatus
    decided_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id", "invoice_id", "source_facts_id", "rule_version",
            "rules_hash", "vendor", "account_number", "property_name", "unit_name",
            "decision_reason",
        ):
            _require_nonblank(getattr(self, field_name), field_name)

        if not isinstance(self.source_facts_version, int) or isinstance(self.source_facts_version, bool):
            raise TypeError("source_facts_version must be int")
        if self.source_facts_version <= 0:
            raise ValueError("source_facts_version must be greater than zero")
        if not isinstance(self.decision_version, int) or isinstance(self.decision_version, bool):
            raise TypeError("decision_version must be int")
        if self.decision_version <= 0:
            raise ValueError("decision_version must be greater than zero")

        if self.tenant_name is not None:
            if not isinstance(self.tenant_name, str):
                raise TypeError("tenant_name must be str or None")
            if not self.tenant_name.strip():
                raise ValueError("tenant_name must be None instead of blank")

        if not isinstance(self.service_period_start, date) or not isinstance(self.service_period_end, date):
            raise TypeError("service period values must be date")
        if self.service_period_start > self.service_period_end:
            raise ValueError("service_period_start cannot be after service_period_end")

        for field_name in ("current_service_amount", "bill_back_amount"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
            if value < ZERO_MONEY:
                raise ValueError(f"{field_name} cannot be negative")

        if self.occupied_days < 0 or self.total_service_days < 0:
            raise ValueError("day counts cannot be negative")
        if self.occupied_days > self.total_service_days:
            raise ValueError("occupied_days cannot exceed total_service_days")

        if self.classification not in PERSISTABLE_AUDIT_STATUSES:
            raise ValueError(f"classification {self.classification.name} is not a persistable bill-back decision")
        if self.classification in {AuditStatus.VACANT, AuditStatus.COMMON_AREA}:
            if quantize_money(self.bill_back_amount) != ZERO_MONEY:
                raise ValueError(f"{self.classification.name} decision requires zero bill-back")

        if not isinstance(self.decision_status, DecisionStatus):
            raise TypeError("decision_status must be DecisionStatus")
        if not isinstance(self.decided_at, datetime):
            raise TypeError("decided_at must be datetime")

    @property
    def provenance_key(self) -> tuple[str, int, str]:
        return (self.invoice_id, self.source_facts_version, self.rule_version)
