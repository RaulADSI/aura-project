"""Translate validated facts and resolved identity into the existing audit model."""
from src.contracts import StructuredUtilityInvoice
from src.domain.models import AccountingContext, AuditRequest, InvoiceData, OccupancyContext, PropertyContext
from src.domain.normalization import generate_match_key
from src.integration_autostack import AutoStackIdentityResult, IdentityType


class StructuredAuditRequestBuilder:
    def __init__(self, rent_roll_contexts):
        self.rent_roll_contexts = rent_roll_contexts

    def build(self, *, invoice: StructuredUtilityInvoice,
              identity: AutoStackIdentityResult) -> AuditRequest:
        if identity.invoice != invoice:
            raise ValueError("Identity belongs to a different facts snapshot")
        if not identity.audit_eligible:
            raise ValueError(identity.eligibility.value)
        # Bill-back uses current service charges only. Missing is not zero,
        # and neither total_due nor invoice_amount is a substitute.
        if invoice.current_service_amount is None:
            raise ValueError("Missing current_service_amount")
        property_name = identity.property_resolution.canonical_property_name
        unit_name = identity.identity_identifier
        if identity.identity_type is IdentityType.COMMON_AREA:
            prop = PropertyContext(None, property_name, unit_name, "COMMON_AREA")
            occ = OccupancyContext(unit_status="COMMON_AREA")
        else:
            key = generate_match_key(property_name, unit_name)
            if key not in self.rent_roll_contexts:
                raise ValueError("Missing rent roll context for resolved unit")
            prop, occ = self.rent_roll_contexts[key]
        return AuditRequest(
            InvoiceData(invoice.invoice_id, invoice.invoice_number, invoice.account_number,
                        invoice.vendor_code, invoice.service_period_start,
                        invoice.service_period_end, invoice.current_service_amount),
            prop, occ, AccountingContext(),
        )
