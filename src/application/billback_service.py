"""Compute decisions through the facts port; business rules stay in AuditEngine."""
from dataclasses import dataclass

from src.auditor import AuditEngine
from src.domain.models import AuditResult
from src.integration_autostack import AutoStackIdentityResult, AutoStackRoutingIdentityAdapter
from src.ports.invoice_facts import InvoiceFactsPort
from src.adapters.structured_audit_request_builder import StructuredAuditRequestBuilder
from src.domain.utility_billback_eligibility import UtilityBillBackEligibilityPolicy, UtilityEligibility


@dataclass(frozen=True)
class BillBackRun:
    selection: str
    identities: tuple[AutoStackIdentityResult, ...]
    results: tuple[AuditResult, ...]
    rejected: tuple[tuple[str, str], ...]


class BillBackService:
    def __init__(self, invoice_facts_port: InvoiceFactsPort,
                 identity_service: AutoStackRoutingIdentityAdapter,
                 request_builder: StructuredAuditRequestBuilder, audit_engine: AuditEngine,
                 eligibility_policy: UtilityBillBackEligibilityPolicy | None = None):
        self.invoice_facts_port = invoice_facts_port
        self.identity_service = identity_service
        self.request_builder = request_builder
        self.audit_engine = audit_engine
        self.eligibility_policy = eligibility_policy or UtilityBillBackEligibilityPolicy()

    def run(self, *, invoice_id: str | None = None,
            facts_version: int | None = None) -> BillBackRun:
        if (invoice_id is None) != (facts_version is None):
            raise ValueError("invoice_id and facts_version must be supplied together")
        invoices = (
            self.invoice_facts_port.list_canonical_snapshots() if invoice_id is None
            else (self.invoice_facts_port.get_exact_snapshot(invoice_id, facts_version),)
        )
        identities, results, rejected = [], [], []
        for invoice in invoices:
            identity = self.identity_service.resolve_snapshot(invoice)
            identities.append(identity)
            try:
                if not identity.audit_eligible:
                    raise ValueError(identity.eligibility.value)
                eligibility = self.eligibility_policy.evaluate(
                    vendor_code=invoice.vendor_code, routing_key=invoice.routing_key,
                    identity_type=identity.identity_type.value,
                )
                if eligibility.outcome is UtilityEligibility.REVIEW_REQUIRED:
                    raise ValueError("BILLBACK_ELIGIBILITY_REVIEW_REQUIRED: " + eligibility.reason)
                if eligibility.outcome in {UtilityEligibility.COMMON_AREA, UtilityEligibility.NON_BILLABLE}:
                    results.append(self.request_builder.build_zero_result(
                        invoice=invoice, identity=identity, eligibility=eligibility))
                    continue
                request = self.request_builder.build(invoice=invoice, identity=identity)
            except ValueError as exc:
                rejected.append((invoice.invoice_id, str(exc)))
                continue
            results.append(self.audit_engine.audit(request))
        return BillBackRun("canonical" if invoice_id is None else "exact",
                           tuple(identities), tuple(results), tuple(rejected))
