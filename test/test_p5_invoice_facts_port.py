import unittest
from decimal import Decimal
from typing import Sequence

from src.contracts import StructuredUtilityInvoice
from src.ports import InvoiceFactsPort


class FakeInvoiceFactsPort:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def get_exact_snapshot(self, invoice_id: str, facts_version: int) -> StructuredUtilityInvoice:
        return next(
            x
            for x in self._snapshots
            if x.invoice_id == invoice_id and x.facts_version == facts_version
        )

    def list_canonical_snapshots(self) -> Sequence[StructuredUtilityInvoice]:
        return tuple(self._snapshots)


class TestInvoiceFactsPort(unittest.TestCase):
    def test_structural_port_contract_has_no_storage_dependency(self):
        item = StructuredUtilityInvoice(
            invoice_id="INV-1",
            facts_id="F-1",
            facts_version=1,
            vendor_code="WM",
            account_number="A-1",
            invoice_amount=Decimal("0.00"),
            extraction_method="DETERMINISTIC_EXTRACTOR",
        )
        port = FakeInvoiceFactsPort([item])
        self.assertIsInstance(port, InvoiceFactsPort)
        self.assertEqual(port.get_exact_snapshot("INV-1", 1), item)
        self.assertEqual(tuple(port.list_canonical_snapshots()), (item,))


if __name__ == "__main__":
    unittest.main()
