"""P5.5 integration boundary from AutoStack persisted facts into AURA identity resolution.

This module deliberately contains no audit or reconciliation logic.  It consumes
AURA-owned ``StructuredUtilityInvoice`` objects through ``InvoiceFactsPort`` and
translates AutoStack routing hints into deterministic property/unit candidates
before delegating identity decisions to the existing ``PropertyResolver`` and
``UnitResolver``.

The current AutoStack routing vocabulary contains Wingate building codes such as
``WG-4735-D8``, ``HC-4671-E4`` and ``BW-4685-B4``.  Those codes are integration
metadata, not AURA domain identities, so their interpretation remains isolated
here rather than leaking into the core resolvers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence, Tuple

from src.adapters.property_resolver import PropertyResolution, PropertyResolver
from src.adapters.unit_resolver import UnitResolution, UnitResolutionStatus, UnitResolver
from src.contracts import StructuredUtilityInvoice
from src.ports.invoice_facts import InvoiceFactsPort


class AuraInputEligibility(str, Enum):
    IDENTITY_RESOLVED = "IDENTITY_RESOLVED"
    PROPERTY_UNRESOLVED = "PROPERTY_UNRESOLVED"
    UNIT_UNRESOLVED = "UNIT_UNRESOLVED"


class IdentityType(str, Enum):
    UNIT = "UNIT"
    COMMON_AREA = "COMMON_AREA"


@dataclass(frozen=True)
class AutoStackIdentityResult:
    invoice: StructuredUtilityInvoice
    property_resolution: PropertyResolution
    unit_resolution: UnitResolution | None
    eligibility: AuraInputEligibility
    identity_type: IdentityType | None
    identity_identifier: str | None
    property_hint: str
    unit_hints: Tuple[str, ...]

    @property
    def audit_eligible(self) -> bool:
        return self.eligibility is AuraInputEligibility.IDENTITY_RESOLVED


@dataclass(frozen=True)
class RoutingIdentityHints:
    property_hint: str
    unit_hints: Tuple[str, ...]


# Explicit integration vocabulary observed in the current AutoStack routing
# catalogue.  These aliases all describe sections/buildings of the canonical
# Wingate Apartments property; they are not added to PropertyResolver itself.
_WINGATE_CODE_RE = re.compile(
    r"^(?P<section>WG|HC|BW)\s*-?\s*(?P<building>4671|4685|4735|4737|4767)\s*-?\s*(?P<unit>.*)$",
    re.IGNORECASE,
)
_WINGATE_TEXT_RE = re.compile(r"WINGATE\s*APARTMENTS", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")

class CommonAreaClassifier:
    """Classify explicit service identifiers from AURA utility rules.

    This is an integration identity classifier, not accounting logic.  It only
    answers whether a routing unit hint is explicitly declared as a common-area
    identity and preserves the matched identifier for downstream provenance.
    """

    def __init__(self, identifiers: Iterable[str]) -> None:
        normalized: dict[str, str] = {}
        for identifier in identifiers:
            display = _SPACE_RE.sub(" ", str(identifier or "").strip()).upper()
            if display:
                normalized[self._normalize(display)] = display
        self._identifiers = normalized

    @classmethod
    def from_rules_file(cls, path: str | Path) -> "CommonAreaClassifier":
        with Path(path).open("r", encoding="utf-8") as handle:
            rules = json.load(handle)
        identifiers = rules.get("common_area_units", ())
        if not isinstance(identifiers, list):
            raise ValueError("utility_rules.common_area_units must be a list")
        return cls(identifiers)

    @staticmethod
    def _normalize(value: str) -> str:
        return _SPACE_RE.sub(" ", value.strip()).upper()

    def classify(self, hints: Iterable[str]) -> str | None:
        for hint in hints:
            normalized = self._normalize(str(hint or ""))
            matched = self._identifiers.get(normalized)
            if matched is not None:
                return matched
        return None


class AutoStackRoutingIdentityAdapter:
    """Map AURA contract snapshots into the existing AURA identity pipeline."""

    WINGATE_PROPERTY_HINT = "Wingate Apartments"

    def __init__(
        self,
        facts_port: InvoiceFactsPort,
        property_resolver: PropertyResolver,
        unit_resolver: UnitResolver,
        common_area_classifier: CommonAreaClassifier | None = None,
    ) -> None:
        self._facts_port = facts_port
        self._property_resolver = property_resolver
        self._unit_resolver = unit_resolver
        self._common_area_classifier = common_area_classifier

    def resolve_canonical_snapshots(self) -> Sequence[AutoStackIdentityResult]:
        return tuple(self.resolve_snapshot(snapshot) for snapshot in self._facts_port.list_canonical_snapshots())

    def resolve_snapshot(self, snapshot: StructuredUtilityInvoice) -> AutoStackIdentityResult:
        hints = self.routing_hints(snapshot.routing_key)
        property_resolution = self._property_resolver.resolve(hints.property_hint)
        if not property_resolution.resolved or not property_resolution.canonical_property_name:
            return AutoStackIdentityResult(
                invoice=snapshot,
                property_resolution=property_resolution,
                unit_resolution=None,
                eligibility=AuraInputEligibility.PROPERTY_UNRESOLVED,
                identity_type=None,
                identity_identifier=None,
                property_hint=hints.property_hint,
                unit_hints=hints.unit_hints,
            )

        common_area_identifier = (
            self._common_area_classifier.classify(hints.unit_hints)
            if self._common_area_classifier is not None
            else None
        )
        if common_area_identifier is not None:
            return AutoStackIdentityResult(
                invoice=snapshot,
                property_resolution=property_resolution,
                unit_resolution=None,
                eligibility=AuraInputEligibility.IDENTITY_RESOLVED,
                identity_type=IdentityType.COMMON_AREA,
                identity_identifier=common_area_identifier,
                property_hint=hints.property_hint,
                unit_hints=hints.unit_hints,
            )

        unit_resolution = self._resolve_unit_candidates(
            property_resolution.canonical_property_name,
            hints.unit_hints,
        )
        eligibility = (
            AuraInputEligibility.IDENTITY_RESOLVED
            if unit_resolution.resolved
            else AuraInputEligibility.UNIT_UNRESOLVED
        )
        return AutoStackIdentityResult(
            invoice=snapshot,
            property_resolution=property_resolution,
            unit_resolution=unit_resolution,
            eligibility=eligibility,
            identity_type=IdentityType.UNIT if unit_resolution.resolved else None,
            identity_identifier=(unit_resolution.canonical_unit_name if unit_resolution.resolved else None),
            property_hint=hints.property_hint,
            unit_hints=hints.unit_hints,
        )

    @classmethod
    def routing_hints(cls, routing_key: str | None) -> RoutingIdentityHints:
        raw = _SPACE_RE.sub(" ", str(routing_key or "").strip())
        if not raw:
            return RoutingIdentityHints("", ())

        if _WINGATE_TEXT_RE.search(raw):
            return RoutingIdentityHints(cls.WINGATE_PROPERTY_HINT, ())

        match = _WINGATE_CODE_RE.match(raw)
        if not match:
            # For normal routing keys (e.g. explicit street/property strings),
            # pass the value directly into the existing PropertyResolver.
            return RoutingIdentityHints(raw, ())

        section = match.group("section").upper()
        building = match.group("building")
        suffix = match.group("unit").strip(" -")
        unit_hints: list[str] = []

        if suffix:
            normalized_suffix = _SPACE_RE.sub(" ", suffix).strip().upper()

            # Section-prefixed Rent Roll units are canonical for HC/BW wings.
            if section in {"HC", "BW"} and not normalized_suffix.startswith("BLDG"):
                unit_hints.append(f"{section} {normalized_suffix}")

            # WG route codes normally correspond to direct unit identifiers.
            # 4767-R* is represented canonically as "Wingate Phase 2-R*".
            if section == "WG" and building == "4767" and re.fullmatch(r"[RS]\d+", normalized_suffix):
                unit_hints.append(f"Wingate Phase 2-{normalized_suffix}")

            unit_hints.append(normalized_suffix)

        return RoutingIdentityHints(
            cls.WINGATE_PROPERTY_HINT,
            tuple(dict.fromkeys(unit_hints)),
        )

    def _resolve_unit_candidates(self, canonical_property: str, unit_hints: Iterable[str]) -> UnitResolution:
        """Resolve ordered routing hints by specificity.

        The hints are generated in deterministic precedence order.  For example,
        ``HC-4671-E4`` yields ``HC E4`` before the fallback ``E4``.  The first
        structurally resolved hint wins; fallback hints are consulted only when
        the more-specific interpretation is truly unresolved.  An ambiguity at
        a more-specific level is surfaced instead of bypassed.
        """
        hints = tuple(unit_hints)
        if not hints:
            return self._unit_resolver.resolve(canonical_property, "")

        for hint in hints:
            result = self._unit_resolver.resolve(canonical_property, hint)
            if result.resolved or result.status is UnitResolutionStatus.AMBIGUOUS:
                return result

        return UnitResolution(UnitResolutionStatus.UNRESOLVED, " | ".join(hints))

