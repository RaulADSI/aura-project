"""Read-only SQLite adapter for P7 bill-back delivery."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import sqlite3

from src.domain.billback_decision import BillBackDecision, DecisionStatus
from src.domain.models import AuditStatus


class SqliteBillBackDecisionReader:
    """Read ACTIVE decisions from an existing AURA database in SQLite read-only mode."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"AURA database not found: {self.path}")

    def _connect(self) -> sqlite3.Connection:
        # mode=ro is an architectural guardrail: P7 cannot mutate aura.db.
        conn = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_active(self) -> tuple[BillBackDecision, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM bill_back_decisions
                   WHERE decision_status=?
                   ORDER BY property_name, unit_name, invoice_id""",
                (DecisionStatus.ACTIVE.value,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BillBackDecision:
        return BillBackDecision(
            decision_id=row["decision_id"],
            invoice_id=row["invoice_id"],
            source_facts_id=row["source_facts_id"],
            source_facts_version=int(row["source_facts_version"]),
            rule_version=row["rule_version"],
            rules_hash=row["rules_hash"],
            decision_version=int(row["decision_version"]),
            vendor=row["vendor"],
            account_number=row["account_number"],
            property_name=row["property_name"],
            unit_name=row["unit_name"],
            tenant_name=row["tenant_name"],
            service_period_start=date.fromisoformat(row["service_period_start"]),
            service_period_end=date.fromisoformat(row["service_period_end"]),
            current_service_amount=Decimal(row["current_service_amount"]),
            occupied_days=int(row["occupied_days"]),
            total_service_days=int(row["total_service_days"]),
            bill_back_amount=Decimal(row["bill_back_amount"]),
            classification=AuditStatus[row["classification"]],
            decision_reason=row["decision_reason"],
            decision_status=DecisionStatus(row["decision_status"]),
            decided_at=datetime.fromisoformat(row["decided_at"]),
        )
