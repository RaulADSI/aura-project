from typing import Any, Dict, List, Optional
from src.adapters.utils import (
    AdapterValidationError,
    parse_decimal,
    parse_optional_iso_date,
    require_string,
    sanitize_string,
)
from src.domain.models import InvoiceData


class AutoStackAdapter:

    SOURCE_NAME = "AutoStack"

    def parse_invoice_payload(
        self,
        raw_data: List[Dict[str, Any]],
    ) -> List[InvoiceData]:
        if not isinstance(raw_data, list):
            raise AdapterValidationError(
                "AutoStack payload must be a list of records",
                source=self.SOURCE_NAME,
            )

        invoices: List[InvoiceData] = []

        for index, item in enumerate(raw_data):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    f"AutoStack record at index {index} must be a dictionary",
                    source=self.SOURCE_NAME,
                    record_id=f"index-{index}",
                    value=item,
                )

            rec_id = sanitize_string(item.get("invoice_id")) or f"index-{index}"

            invoice_id = require_string(
                item.get("invoice_id"),
                field="invoice_id",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            account_number = require_string(
                item.get("account_number"),
                field="account_number",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            vendor_name = require_string(
                item.get("vendor_name"),
                field="vendor_name",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            amount = parse_decimal(
                item.get("amount"),
                field="amount",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            inv_num_clean = sanitize_string(item.get("invoice_number"))
            invoice_number = inv_num_clean if inv_num_clean else None

            service_start = parse_optional_iso_date(
                item.get("service_start_date"),
                field="service_start_date",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            service_end = parse_optional_iso_date(
                item.get("service_end_date"),
                field="service_end_date",
                record_id=rec_id,
                source=self.SOURCE_NAME,
            )

            invoices.append(
                InvoiceData(
                    invoice_id=invoice_id,
                    invoice_number=invoice_number,
                    account_number=account_number,
                    vendor_name=vendor_name,
                    service_start_date=service_start,
                    service_end_date=service_end,
                    amount=amount,
                )
            )

        return invoices
