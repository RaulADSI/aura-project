"""SQLite infrastructure adapter for AutoStack persisted utility invoice facts.

This module is the only AURA component allowed to know the current AutoStack
SQLite schema.  It maps the persisted ``invoices`` + ``utility_invoice_details``
rows into the AURA-owned :class:`StructuredUtilityInvoice` contract.

Current-schema compatibility policy
-----------------------------------
The supplied AutoStack schema stores exactly one ``utility_invoice_details`` row
per invoice (``invoice_id`` is UNIQUE) and does not persist a ``facts_version``
column.  P5 therefore exposes that singleton persisted snapshot as
``facts_version = 1``.  A request for any other version is a deterministic
``InvoiceFactsNotFoundError``.  This is an explicit compatibility policy, not a
"latest row" heuristic.

Canonical eligibility policy
----------------------------
``list_canonical_snapshots`` accepts invoices in successful operational states
``READY``, ``DISPATCHING`` and ``DISPATCHED``.  ``REVIEW_REQUIRED``, ``FAILED``
and ``DEAD`` are excluded.  Every included row must also have a structurally
valid ``utility_invoice_details`` record that can be mapped to the AURA contract.

``get_exact_snapshot`` deliberately ignores operational eligibility and returns
the exact singleton snapshot when it exists and is structurally valid.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Sequence

from src.contracts import StructuredUtilityInvoice
from src.ports.invoice_facts import InvoiceFactsNotFoundError


LEGACY_SINGLETON_FACTS_VERSION = 1
CANONICAL_ELIGIBLE_STATUSES = frozenset({"READY", "DISPATCHING", "DISPATCHED"})
PERSISTED_EXTRACTION_METHOD = "AUTOSTACK_PERSISTED_FACTS"


class AutoStackSqliteContractError(ValueError):
    """Raised when a persisted row exists but violates the AURA input contract."""


class AutoStackSqliteAdapter:
    """Implementation of ``InvoiceFactsPort`` backed by AutoStack SQLite."""

    _SELECT_BASE = """
        SELECT
            i.id AS invoice_id,
            i.status AS invoice_status,
            i.invoice_number AS invoice_number,
            i.invoice_date AS invoice_date,
            i.property_code AS property_code,
            i.vendor_code AS invoice_vendor_code,
            i.account_number AS invoice_account_number,
            u.id AS facts_id,
            u.vendor_code AS facts_vendor_code,
            u.account_number AS facts_account_number,
            u.service_period_start AS service_period_start,
            u.service_period_end AS service_period_end,
            CAST(u.amount AS TEXT) AS invoice_amount_text,
            CAST(u.previous_bill_amount AS TEXT) AS previous_bill_amount_text,
            CAST(u.payment_received_amount AS TEXT) AS payment_received_amount_text,
            CAST(u.past_due_amount AS TEXT) AS past_due_amount_text,
            CAST(u.current_service_amount AS TEXT) AS current_service_amount_text,
            CAST(u.total_due AS TEXT) AS total_due_text
        FROM invoices AS i
        JOIN utility_invoice_details AS u ON u.invoice_id = i.id
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"AutoStack SQLite database not found: {self.db_path}")

    def get_exact_snapshot(
        self,
        invoice_id: str,
        facts_version: int,
    ) -> StructuredUtilityInvoice:
        if not isinstance(invoice_id, str) or not invoice_id.strip():
            raise ValueError("invoice_id must be a non-blank string")
        if not isinstance(facts_version, int) or isinstance(facts_version, bool):
            raise TypeError("facts_version must be int")
        if facts_version != LEGACY_SINGLETON_FACTS_VERSION:
            raise InvoiceFactsNotFoundError(
                f"AutoStack schema exposes only facts_version=1; requested {facts_version} "
                f"for invoice {invoice_id!r}"
            )

        with closing(self._connect()) as conn:
            row = conn.execute(
                self._SELECT_BASE + " WHERE i.id = ?",
                (invoice_id,),
            ).fetchone()

        if row is None:
            raise InvoiceFactsNotFoundError(
                f"facts snapshot not found for invoice {invoice_id!r}, version {facts_version}"
            )
        return self._map_row(row)

    def list_canonical_snapshots(self) -> Sequence[StructuredUtilityInvoice]:
        placeholders = ",".join("?" for _ in CANONICAL_ELIGIBLE_STATUSES)
        sql = (
            self._SELECT_BASE
            + f" WHERE i.status IN ({placeholders}) ORDER BY i.received_at, i.id"
        )
        statuses = tuple(sorted(CANONICAL_ELIGIBLE_STATUSES))

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, statuses).fetchall()

        snapshots = []
        for row in rows:
            try:
                snapshots.append(self._map_row(row))
            except (TypeError, ValueError) as exc:
                # Canonical listing is a safe consumption surface: malformed
                # persisted rows are not exposed to the AURA core.
                # Exact lookup still surfaces their structural error explicitly.
                continue
        return tuple(snapshots)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _map_row(self, row: sqlite3.Row) -> StructuredUtilityInvoice:
        vendor_code = self._required_text(
            row["facts_vendor_code"] or row["invoice_vendor_code"], "vendor_code"
        )
        account_number = self._required_text(
            row["facts_account_number"] or row["invoice_account_number"], "account_number"
        )

        try:
            return StructuredUtilityInvoice(
                invoice_id=self._required_text(row["invoice_id"], "invoice_id"),
                facts_id=self._required_text(str(row["facts_id"]), "facts_id"),
                facts_version=LEGACY_SINGLETON_FACTS_VERSION,
                vendor_code=vendor_code,
                account_number=account_number,
                invoice_amount=self._money(row["invoice_amount_text"], "invoice_amount", required=True),
                invoice_number=self._optional_text(row["invoice_number"]),
                invoice_date=self._date_value(row["invoice_date"], "invoice_date"),
                service_period_start=self._date_value(
                    row["service_period_start"], "service_period_start"
                ),
                service_period_end=self._date_value(
                    row["service_period_end"], "service_period_end"
                ),
                previous_bill_amount=self._money(
                    row["previous_bill_amount_text"], "previous_bill_amount"
                ),
                payment_received_amount=self._money(
                    row["payment_received_amount_text"], "payment_received_amount"
                ),
                past_due_amount=self._money(row["past_due_amount_text"], "past_due_amount"),
                current_service_amount=self._money(
                    row["current_service_amount_text"], "current_service_amount"
                ),
                total_due=self._money(row["total_due_text"], "total_due"),
                routing_key=self._optional_text(row["property_code"]),
                property_id=None,
                unit_hint=None,
                extraction_method=PERSISTED_EXTRACTION_METHOD,
                extractor_version=None,
            )
        except (TypeError, ValueError) as exc:
            raise AutoStackSqliteContractError(
                f"invalid persisted facts for invoice {row['invoice_id']!r}: {exc}"
            ) from exc

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        if value is None:
            raise AutoStackSqliteContractError(f"{field} is required")
        text = str(value).strip()
        if not text:
            raise AutoStackSqliteContractError(f"{field} is required")
        return text

    @staticmethod
    def _optional_text(value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _money(value: object, field: str, *, required: bool = False) -> Optional[Decimal]:
        if value is None:
            if required:
                raise AutoStackSqliteContractError(f"{field} is required")
            return None
        text = str(value).strip()
        if not text:
            if required:
                raise AutoStackSqliteContractError(f"{field} is required")
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise AutoStackSqliteContractError(
                f"{field} must be a valid decimal, got {value!r}"
            ) from exc

    @staticmethod
    def _date_value(value: object, field: str) -> Optional[date]:
        if value is None:
            return None

        # Current AutoStack/JDBC persistence stores DATE values as epoch
        # milliseconds even though SQLite declares the columns as DATE.
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
            except (OverflowError, OSError, ValueError) as exc:
                raise AutoStackSqliteContractError(
                    f"{field} contains invalid epoch milliseconds: {value!r}"
                ) from exc

        text = str(value).strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise AutoStackSqliteContractError(
                f"{field} must be ISO date or epoch milliseconds, got {value!r}"
            ) from exc
