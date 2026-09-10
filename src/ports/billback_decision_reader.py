"""Read-only input port for persisted AURA bill-back decisions.

P7 consumes decisions already persisted by P6. Implementations of this port
must not calculate, mutate, supersede, or otherwise change decisions.
"""
from __future__ import annotations

from typing import Protocol, Sequence

from src.domain.billback_decision import BillBackDecision


class BillBackDecisionReader(Protocol):
    def list_active(self) -> Sequence[BillBackDecision]:
        """Return only ACTIVE persisted bill-back decisions."""
        ...
