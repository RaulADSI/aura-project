import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Sequence, Tuple

from src.domain.normalization import normalize_address


class PropertyResolutionStatus(str, Enum):
    EXACT_NORMALIZED = "EXACT_NORMALIZED"
    ADDRESS_COMPONENT_MATCH = "ADDRESS_COMPONENT_MATCH"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class PropertyResolution:
    status: PropertyResolutionStatus
    input_property_name: str
    canonical_property_name: str | None = None
    candidates: Tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status in {
            PropertyResolutionStatus.EXACT_NORMALIZED,
            PropertyResolutionStatus.ADDRESS_COMPONENT_MATCH,
        }


_ARROW_RE = re.compile(r"^\s*->\s*")
_SPLIT_RE = re.compile(r"\s+-\s+|\s*;\s*")
_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}


class PropertyResolver:
    """Deterministically resolve external property strings to AppFolio property identities.

    Resolution never uses fuzzy/probabilistic similarity. A candidate is accepted only when
    an exact normalized alias or an unambiguous address-component signature matches.
    """

    def __init__(self, canonical_properties: Iterable[str]):
        properties = tuple(dict.fromkeys(str(p).strip() for p in canonical_properties if str(p).strip()))
        self._properties: Tuple[str, ...] = properties
        self._exact_index: Dict[str, List[str]] = {}
        self._component_index: Dict[Tuple[str, ...], List[str]] = {}

        for canonical in properties:
            for alias in self._catalog_aliases(canonical):
                normalized = normalize_address(alias)
                if normalized:
                    self._exact_index.setdefault(normalized, []).append(canonical)

                component = self._address_component_signature(alias)
                if component:
                    self._component_index.setdefault(component, []).append(canonical)

        self._dedupe_indexes()

    def resolve(self, property_name: str) -> PropertyResolution:
        raw = str(property_name or "").strip()
        if not raw:
            return PropertyResolution(PropertyResolutionStatus.UNRESOLVED, raw)

        exact_candidates: List[str] = []
        for alias in self._input_aliases(raw):
            normalized = normalize_address(alias)
            if normalized:
                exact_candidates.extend(self._exact_index.get(normalized, ()))

        exact_unique = self._unique(exact_candidates)
        if len(exact_unique) == 1:
            return PropertyResolution(
                PropertyResolutionStatus.EXACT_NORMALIZED,
                raw,
                exact_unique[0],
                tuple(exact_unique),
            )
        if len(exact_unique) > 1:
            return PropertyResolution(
                PropertyResolutionStatus.AMBIGUOUS,
                raw,
                None,
                tuple(exact_unique),
            )

        component_candidates: List[str] = []
        for alias in self._input_aliases(raw):
            signature = self._address_component_signature(alias)
            if signature:
                component_candidates.extend(self._component_index.get(signature, ()))

        component_unique = self._unique(component_candidates)
        if len(component_unique) == 1:
            return PropertyResolution(
                PropertyResolutionStatus.ADDRESS_COMPONENT_MATCH,
                raw,
                component_unique[0],
                tuple(component_unique),
            )
        if len(component_unique) > 1:
            return PropertyResolution(
                PropertyResolutionStatus.AMBIGUOUS,
                raw,
                None,
                tuple(component_unique),
            )

        return PropertyResolution(PropertyResolutionStatus.UNRESOLVED, raw)

    @classmethod
    def _catalog_aliases(cls, canonical: str) -> Sequence[str]:
        stripped = _ARROW_RE.sub("", canonical).strip()
        aliases = [canonical, stripped]
        aliases.extend(part.strip() for part in _SPLIT_RE.split(stripped) if part.strip())
        return cls._unique(aliases)

    @classmethod
    def _input_aliases(cls, raw: str) -> Sequence[str]:
        aliases = [raw]
        aliases.extend(part.strip() for part in _SPLIT_RE.split(raw) if part.strip())
        return cls._unique(aliases)

    @staticmethod
    def _address_component_signature(text: str) -> Tuple[str, ...] | None:
        """Return a conservative street signature: house number + first two street tokens.

        Direction-only tokens are ignored. This intentionally trades recall for auditability;
        collisions are surfaced as AMBIGUOUS instead of guessed.
        """
        normalized_text = str(text or "").upper()
        normalized_text = normalized_text.replace("STREET", "ST")
        normalized_text = normalized_text.replace("AVENUE", "AVE")
        normalized_text = normalized_text.replace("DRIVE", "DR")
        normalized_text = normalized_text.replace("ROAD", "RD")
        normalized_text = normalized_text.replace("COURT", "CT")
        normalized_text = normalized_text.replace("BOULEVARD", "BLVD")

        tokens = _TOKEN_RE.findall(normalized_text)
        if not tokens:
            return None

        number_idx = next((i for i, token in enumerate(tokens) if token.isdigit()), None)
        if number_idx is None:
            return None

        number = tokens[number_idx]
        street_tokens: List[str] = []
        for token in tokens[number_idx + 1 :]:
            if token in _DIRECTIONALS:
                continue
            if token.isdigit() and len(token) >= 5:
                break
            street_tokens.append(token)
            if len(street_tokens) == 2:
                break

        if len(street_tokens) < 2:
            return None

        return (number, *street_tokens)

    def _dedupe_indexes(self) -> None:
        for index in (self._exact_index, self._component_index):
            for key, values in list(index.items()):
                index[key] = self._unique(values)

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        return list(dict.fromkeys(v for v in values if v))
