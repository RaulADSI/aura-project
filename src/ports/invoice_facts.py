"""Port through which AURA consumes persisted invoice facts.

The port deliberately exposes no SQLite, AutoStack repository, dispatch,
quality-gate, CAS, SMTP, or state-machine types.
"""

from typing import Protocol, Sequence, runtime_checkable

from src.contracts import StructuredUtilityInvoice


class InvoiceFactsNotFoundError(LookupError):
    """Raised when an explicitly requested facts snapshot does not exist."""


@runtime_checkable
class InvoiceFactsPort(Protocol):
    """Stable input boundary for persisted utility invoice facts.

    ``get_exact_snapshot`` is intentionally version-explicit. Implementations
    must never interpret it as "latest available".

    ``list_canonical_snapshots`` is the operational path. The adapter owns the
    policy that determines which AutoStack invoices are eligible and which
    facts version is canonical. AURA receives only validated contract objects.
    """

    def get_exact_snapshot(
        self,
        invoice_id: str,
        facts_version: int,
    ) -> StructuredUtilityInvoice:
        ...

    def list_canonical_snapshots(self) -> Sequence[StructuredUtilityInvoice]:
        ...
