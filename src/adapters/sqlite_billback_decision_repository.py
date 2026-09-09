"""SQLite persistence adapter for AURA-owned bill-back decisions."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import sqlite3

from src.domain.billback_decision import BillBackDecision, DecisionStatus
from src.domain.models import AuditStatus


class NonDeterministicDecisionError(RuntimeError):
    pass


class RuleVersionConflictError(RuntimeError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS bill_back_decisions (
    decision_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    source_facts_id TEXT NOT NULL,
    source_facts_version INTEGER NOT NULL CHECK (source_facts_version > 0),
    rule_version TEXT NOT NULL,
    rules_hash TEXT NOT NULL,
    decision_version INTEGER NOT NULL CHECK (decision_version > 0),
    vendor TEXT NOT NULL,
    account_number TEXT NOT NULL,
    property_name TEXT NOT NULL,
    unit_name TEXT NOT NULL,
    tenant_name TEXT,
    service_period_start TEXT NOT NULL,
    service_period_end TEXT NOT NULL,
    current_service_amount TEXT NOT NULL,
    occupied_days INTEGER NOT NULL CHECK (occupied_days >= 0),
    total_service_days INTEGER NOT NULL CHECK (total_service_days >= 0),
    bill_back_amount TEXT NOT NULL,
    classification TEXT NOT NULL,
    decision_reason TEXT NOT NULL,
    decision_status TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    UNIQUE (invoice_id, source_facts_version, rule_version)
);
CREATE INDEX IF NOT EXISTS ix_bill_back_decisions_invoice
    ON bill_back_decisions (invoice_id, decision_version);
CREATE INDEX IF NOT EXISTS ix_bill_back_decisions_status
    ON bill_back_decisions (decision_status, classification);
"""


class SqliteBillBackDecisionRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)

    def save(self, decision: BillBackDecision) -> BillBackDecision:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing_row = conn.execute(
                """SELECT * FROM bill_back_decisions
                   WHERE invoice_id=? AND source_facts_version=? AND rule_version=?""",
                decision.provenance_key,
            ).fetchone()
            if existing_row is not None:
                existing = self._from_row(existing_row)
                if existing.rules_hash != decision.rules_hash:
                    raise RuleVersionConflictError(
                        f"rule_version {decision.rule_version!r} maps to a different rules_hash"
                    )
                if self._deterministic_payload(existing) != self._deterministic_payload(decision):
                    raise NonDeterministicDecisionError(
                        "same invoice + source facts version + rule version produced a different decision"
                    )
                return existing

            next_version = conn.execute(
                "SELECT COALESCE(MAX(decision_version), 0) + 1 FROM bill_back_decisions WHERE invoice_id=?",
                (decision.invoice_id,),
            ).fetchone()[0]
            stored = replace(decision, decision_version=int(next_version), decision_status=DecisionStatus.ACTIVE)

            conn.execute(
                """UPDATE bill_back_decisions
                   SET decision_status=?
                   WHERE invoice_id=? AND decision_status=?""",
                (DecisionStatus.SUPERSEDED.value, stored.invoice_id, DecisionStatus.ACTIVE.value),
            )
            conn.execute(
                """INSERT INTO bill_back_decisions (
                    decision_id, invoice_id, source_facts_id, source_facts_version,
                    rule_version, rules_hash, decision_version,
                    vendor, account_number, property_name, unit_name, tenant_name,
                    service_period_start, service_period_end, current_service_amount,
                    occupied_days, total_service_days, bill_back_amount,
                    classification, decision_reason, decision_status, decided_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                self._to_row(stored),
            )
            return stored

    def find_by_provenance(
        self, invoice_id: str, source_facts_version: int, rule_version: str
    ) -> BillBackDecision | None:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM bill_back_decisions
                   WHERE invoice_id=? AND source_facts_version=? AND rule_version=?""",
                (invoice_id, source_facts_version, rule_version),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_active(self) -> tuple[BillBackDecision, ...]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM bill_back_decisions WHERE decision_status=? ORDER BY invoice_id",
                (DecisionStatus.ACTIVE.value,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def list_all(self) -> tuple[BillBackDecision, ...]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM bill_back_decisions ORDER BY invoice_id, decision_version"
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _money(value: Decimal) -> str:
        # Never cross the SQLite boundary as REAL/float.
        return format(value, "f")

    @classmethod
    def _to_row(cls, d: BillBackDecision) -> tuple:
        return (
            d.decision_id, d.invoice_id, d.source_facts_id, d.source_facts_version,
            d.rule_version, d.rules_hash, d.decision_version,
            d.vendor, d.account_number, d.property_name, d.unit_name, d.tenant_name,
            d.service_period_start.isoformat(), d.service_period_end.isoformat(),
            cls._money(d.current_service_amount), d.occupied_days, d.total_service_days,
            cls._money(d.bill_back_amount), d.classification.name, d.decision_reason,
            d.decision_status.value, d.decided_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BillBackDecision:
        return BillBackDecision(
            decision_id=row["decision_id"], invoice_id=row["invoice_id"],
            source_facts_id=row["source_facts_id"], source_facts_version=int(row["source_facts_version"]),
            rule_version=row["rule_version"], rules_hash=row["rules_hash"],
            decision_version=int(row["decision_version"]), vendor=row["vendor"],
            account_number=row["account_number"], property_name=row["property_name"],
            unit_name=row["unit_name"], tenant_name=row["tenant_name"],
            service_period_start=date.fromisoformat(row["service_period_start"]),
            service_period_end=date.fromisoformat(row["service_period_end"]),
            current_service_amount=Decimal(row["current_service_amount"]),
            occupied_days=int(row["occupied_days"]), total_service_days=int(row["total_service_days"]),
            bill_back_amount=Decimal(row["bill_back_amount"]),
            classification=AuditStatus[row["classification"]], decision_reason=row["decision_reason"],
            decision_status=DecisionStatus(row["decision_status"]),
            decided_at=datetime.fromisoformat(row["decided_at"]),
        )

    @staticmethod
    def _deterministic_payload(d: BillBackDecision) -> tuple:
        return (
            d.source_facts_id,
            d.rules_hash,
            d.vendor,
            d.account_number,
            d.property_name,
            d.unit_name,
            d.tenant_name,
            d.service_period_start,
            d.service_period_end,
            d.current_service_amount,
            d.occupied_days,
            d.total_service_days,
            d.bill_back_amount,
            d.classification,
            d.decision_reason,
        )
