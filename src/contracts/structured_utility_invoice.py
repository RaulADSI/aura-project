"""AURA-owned contract for persisted utility invoice facts.

This module intentionally contains no AutoStack persistence or operational types.
It represents only facts AURA is allowed to consume.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


CONTRACT_VERSION = 1
ZERO_MONEY = Decimal("0.00")


def _require_nonblank(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _validate_optional_string(value: Optional[str], field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str or None, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field_name} must be None instead of blank")


def _validate_optional_date(value: Optional[date], field_name: str) -> None:
    if value is not None and not isinstance(value, date):
        raise TypeError(f"{field_name} must be date or None, got {type(value).__name__}")


def _validate_money(value: Optional[Decimal], field_name: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal or None, got {type(value).__name__}")
    if value < ZERO_MONEY:
        raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True)
class StructuredUtilityInvoice:
    """Versioned, immutable invoice-facts snapshot consumable by AURA.

    Semantics:
    - ``None`` means the fact was not determined / evidence is absent.
    - ``Decimal("0.00")`` means the value was explicitly determined as zero.
    - Monetary fields are independent facts. In particular, ``invoice_amount``,
      ``current_service_amount`` and ``total_due`` MUST NOT be substituted for
      one another as fallback values.
    - ``invoice_id + facts_id + facts_version`` identifies the exact facts
      snapshot audited by AURA.
    """

    invoice_id: str
    facts_id: str
    facts_version: int

    vendor_code: str
    account_number: str
    invoice_amount: Decimal

    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    service_period_start: Optional[date] = None
    service_period_end: Optional[date] = None

    previous_bill_amount: Optional[Decimal] = None
    payment_received_amount: Optional[Decimal] = None
    past_due_amount: Optional[Decimal] = None
    current_service_amount: Optional[Decimal] = None
    total_due: Optional[Decimal] = None

    routing_key: Optional[str] = None
    property_id: Optional[str] = None
    unit_hint: Optional[str] = None

    extraction_method: str = "UNKNOWN"
    extractor_version: Optional[str] = None
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_nonblank(self.invoice_id, "invoice_id")
        _require_nonblank(self.facts_id, "facts_id")
        _require_nonblank(self.vendor_code, "vendor_code")
        _require_nonblank(self.account_number, "account_number")
        _require_nonblank(self.extraction_method, "extraction_method")

        if not isinstance(self.facts_version, int) or isinstance(self.facts_version, bool):
            raise TypeError(
                f"facts_version must be int, got {type(self.facts_version).__name__}"
            )
        if self.facts_version <= 0:
            raise ValueError("facts_version must be greater than zero")

        if not isinstance(self.contract_version, int) or isinstance(self.contract_version, bool):
            raise TypeError(
                f"contract_version must be int, got {type(self.contract_version).__name__}"
            )
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(
                f"unsupported contract_version {self.contract_version}; expected {CONTRACT_VERSION}"
            )

        _validate_money(self.invoice_amount, "invoice_amount", required=True)
        for field_name in (
            "previous_bill_amount",
            "payment_received_amount",
            "past_due_amount",
            "current_service_amount",
            "total_due",
        ):
            _validate_money(getattr(self, field_name), field_name)

        for field_name in (
            "invoice_number",
            "routing_key",
            "property_id",
            "unit_hint",
            "extractor_version",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)

        for field_name in (
            "invoice_date",
            "service_period_start",
            "service_period_end",
        ):
            _validate_optional_date(getattr(self, field_name), field_name)

        if (
            self.service_period_start is not None
            and self.service_period_end is not None
            and self.service_period_start > self.service_period_end
        ):
            raise ValueError("service_period_start cannot be after service_period_end")
