from typing import Any, Dict, List, Optional
from src.adapters.appfolio_adapter import AppFolioAdapter
from src.adapters.autostack_adapter import AutoStackAdapter
from src.domain.models import (
    AccountingContext,
    AuditRequest,
    InvoiceData,
    OccupancyContext,
    PropertyContext,
)
from src.domain.normalization import generate_match_key


class AuditRequestBuilder:
    """
    Composes AutoStack InvoiceData with AppFolio Property, Occupancy, and Accounting contexts.
    Uses property_name and unit_name from AutoStack items to generate the correlation match_key,
    ensuring deterministic assembly without guessing via utility account numbers.
    """

    def __init__(self, data_path: str):
        self.appfolio_adapter = AppFolioAdapter(data_path)
        self.autostack_adapter = AutoStackAdapter()

    def build_requests(
        self,
        raw_autostack_data: List[Dict[str, Any]],
        rent_roll_file: str = "rent_roll.json",
        bills_file: str = "appfolio_bills.csv",
    ) -> List[AuditRequest]:
        invoices: List[InvoiceData] = self.autostack_adapter.parse_invoice_payload(
            raw_autostack_data
        )
        rent_roll_map = self.appfolio_adapter.load_rent_roll_contexts(rent_roll_file)
        accounting_map = self.appfolio_adapter.load_accounting_contexts(bills_file)

        audit_requests: List[AuditRequest] = []

        for idx, item in enumerate(raw_autostack_data):
            inv = invoices[idx]

            # Correlate using property_name and unit_name provided by AutoStack
            prop_name = str(item.get("property_name", "")).strip()
            unit_name = str(item.get("unit_name", "")).strip()

            match_key = generate_match_key(prop_name, unit_name)

            if match_key and match_key in rent_roll_map:
                prop_ctx, occ_ctx = rent_roll_map[match_key]
            else:
                # Unmatched in Rent Roll
                prop_ctx = PropertyContext(
                    property_id=None,
                    property_name=prop_name if prop_name else "Unmatched Property",
                    unit_name=unit_name if unit_name else "UNKNOWN",
                    unit_type="UNIT",
                )
                occ_ctx = OccupancyContext()

            acc_ctx = accounting_map.get(
                match_key or "",
                AccountingContext()
            )

            request = AuditRequest(
                invoice=inv,
                property=prop_ctx,
                occupancy=occ_ctx,
                accounting=acc_ctx,
            )
            audit_requests.append(request)

        return audit_requests
