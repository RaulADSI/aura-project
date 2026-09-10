import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, Mapping, Sequence, Tuple


class UnitResolutionStatus(str, Enum):
    EXACT_UNIT = "EXACT_UNIT"
    NORMALIZED_UNIT = "NORMALIZED_UNIT"
    PROPERTY_ONLY_SINGLE_UNIT = "PROPERTY_ONLY_SINGLE_UNIT"
    EXPLICIT_ALIAS = "EXPLICIT_ALIAS"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class UnitResolution:
    status: UnitResolutionStatus
    input_unit_name: str
    canonical_unit_name: str | None = None
    candidates: Tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status in {
            UnitResolutionStatus.EXACT_UNIT,
            UnitResolutionStatus.NORMALIZED_UNIT,
            UnitResolutionStatus.PROPERTY_ONLY_SINGLE_UNIT,
            UnitResolutionStatus.EXPLICIT_ALIAS,
        }


_PREFIX_RE = re.compile(r"^(?:APT\.?|UNIT|#|STE\.?|SUITE)\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^0+(\d+)$")


def normalize_unit_name(value: object) -> str:
    """Normalize unit syntax without guessing semantic aliases."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""
    cleaned = _PREFIX_RE.sub("", raw).strip()
    cleaned = _SPACE_RE.sub("", cleaned).upper()
    numeric = _NUMERIC_RE.fullmatch(cleaned)
    if numeric:
        cleaned = numeric.group(1)
    return cleaned


class UnitResolver:
    """Deterministically resolve historical units within an already-resolved property.

    No fuzzy matching is used. Optional aliases are explicit and property-scoped.
    """

    def __init__(
        self,
        units_by_property: Mapping[str, Iterable[str]],
    ) -> None:
        self._units_by_property: Dict[str, Tuple[str, ...]] = {
            str(prop): tuple(dict.fromkeys("" if u is None else str(u).strip() for u in units))
            for prop, units in units_by_property.items()
        }

    def resolve(self, canonical_property_name: str, unit_name: str) -> UnitResolution:
        prop = str(canonical_property_name or "").strip()
        raw = str(unit_name or "").strip()
        units = self._units_by_property.get(prop)
        if units is None:
            return UnitResolution(UnitResolutionStatus.UNRESOLVED, raw)

        # Exact identity first (trimmed, case-insensitive), preserving canonical spelling.
        exact = self._unique(u for u in units if u.casefold() == raw.casefold())
        if len(exact) == 1:
            return UnitResolution(UnitResolutionStatus.EXACT_UNIT, raw, exact[0], tuple(exact))
        if len(exact) > 1:
            return UnitResolution(UnitResolutionStatus.AMBIGUOUS, raw, None, tuple(exact))

        normalized_input = normalize_unit_name(raw)

        normalized_candidates = self._unique(
            u for u in units if normalize_unit_name(u) == normalized_input and normalized_input != ""
        )
        if len(normalized_candidates) == 1:
            return UnitResolution(
                UnitResolutionStatus.NORMALIZED_UNIT,
                raw,
                normalized_candidates[0],
                tuple(normalized_candidates),
            )
        if len(normalized_candidates) > 1:
            return UnitResolution(
                UnitResolutionStatus.AMBIGUOUS,
                raw,
                None,
                tuple(normalized_candidates),
            )

        # Single-unit/single-family fallback: identity is already constrained by property.
        if len(units) == 1:
            return UnitResolution(
                UnitResolutionStatus.PROPERTY_ONLY_SINGLE_UNIT,
                raw,
                units[0],
                tuple(units),
            )

        return UnitResolution(UnitResolutionStatus.UNRESOLVED, raw)

    @staticmethod
    def from_explicit_alias(input_unit_name: str, canonical_unit_name: str) -> UnitResolution:
        canonical = str(canonical_unit_name).strip()
        return UnitResolution(
            UnitResolutionStatus.EXPLICIT_ALIAS,
            str(input_unit_name or "").strip(),
            canonical,
            (canonical,),
        )

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(values))
