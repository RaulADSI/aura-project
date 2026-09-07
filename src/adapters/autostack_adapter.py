from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List
import pandas as pd

from src.domain.models import InvoiceData


class AdapterValidationError(ValueError):
    """Indica que un payload externo no cumple el contrato requerido."""
    pass


class AutoStackAdapter:

    MONEY_QUANTUM = Decimal("0.01")

    REQUIRED_FIELDS = (
        "invoice_id",
        "account_number",
        "vendor_name",
        "amount",
    )

    def parse_invoice_payload(
        self,
        raw_data: List[Dict[str, Any]],
    ) -> List[InvoiceData]:
        invoices: List[InvoiceData] = []

        for index, item in enumerate(raw_data):
            self._validate_required_fields(item, index)

            invoice_id = str(item["invoice_id"]).strip()
            invoice_number = item.get("invoice_number")
            account_number = str(item["account_number"]).strip()
            vendor_name = str(item["vendor_name"]).strip()

            service_start = self._parse_date(
                item.get("service_start_date")
            )
            service_end = self._parse_date(
                item.get("service_end_date")
            )

            amount = self._parse_amount(item["amount"], index)

            invoices.append(
                InvoiceData(
                    invoice_id=invoice_id,
                    invoice_number=(
                        str(invoice_number).strip()
                        if invoice_number is not None
                        else None
                    ),
                    account_number=account_number,
                    vendor_name=vendor_name,
                    service_start_date=service_start,
                    service_end_date=service_end,
                    amount=amount,
                )
            )

        return invoices

    def _validate_required_fields(
        self,
        item: Dict[str, Any],
        index: int,
    ) -> None:
        if not isinstance(item, dict):
            raise AdapterValidationError(
                f"AutoStack record {index} must be a dictionary"
            )

        missing = []

        for field in self.REQUIRED_FIELDS:
            value = item.get(field)

            if value is None:
                missing.append(field)
                continue

            if isinstance(value, str) and not value.strip():
                missing.append(field)

        if missing:
            raise AdapterValidationError(
                f"AutoStack record {index} missing required fields: "
                f"{', '.join(missing)}"
            )

    def _parse_amount(
        self,
        value: Any,
        index: int,
    ) -> Decimal:
        try:
            amount = Decimal(str(value).strip())
        except (InvalidOperation, AttributeError):
            raise AdapterValidationError(
                f"AutoStack record {index} has invalid amount: {value!r}"
            )

        if not amount.is_finite():
            raise AdapterValidationError(
                f"AutoStack record {index} has non-finite amount: {value!r}"
            )

        return amount.quantize(
            self.MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    def _parse_date(self, value: Any) -> date | None:
        if value is None:
            return None

        parsed = pd.to_datetime(value, errors="coerce")

        if pd.isna(parsed):
            return None

        return parsed.date()