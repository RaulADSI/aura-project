import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Tuple

from src.adapters.unit_resolver import normalize_unit_name


class UnitAliasRegistryError(ValueError):
    """Raised when the unit alias registry violates a load-time invariant."""


@dataclass(frozen=True)
class UnitAliasMatch:
    property_name: str
    input_unit_name: str
    canonical_unit_name: str


class UnitAliasRegistry:
    """Validated, property-scoped registry of audited historical unit aliases.

    The registry is intentionally dumb: it performs exact lookup after the same
    deterministic unit normalization used by UnitResolver. It never guesses.
    """

    def __init__(
        self,
        aliases: Mapping[str, Mapping[str, str]],
        units_by_property: Mapping[str, Tuple[str, ...] | list[str]],
    ) -> None:
        self._units_by_property: Dict[str, Tuple[str, ...]] = {
            str(prop).strip(): tuple(str(unit).strip() for unit in units)
            for prop, units in units_by_property.items()
        }
        self._aliases: Dict[str, Dict[str, str]] = {}
        self._validate_and_load(aliases)

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        units_by_property: Mapping[str, Tuple[str, ...] | list[str]],
    ) -> "UnitAliasRegistry":
        path = Path(path)
        if not path.exists():
            raise UnitAliasRegistryError(f"Unit alias registry not found: {path}")
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text, object_pairs_hook=_reject_duplicate_object_keys)
        except json.JSONDecodeError as exc:
            raise UnitAliasRegistryError(f"Invalid JSON in unit alias registry: {path}") from exc
        if not isinstance(data, dict):
            raise UnitAliasRegistryError("Unit alias registry root must be an object")
        return cls(data, units_by_property)

    def resolve(self, canonical_property_name: str, unit_name: str) -> UnitAliasMatch | None:
        prop = str(canonical_property_name or "").strip()
        normalized_alias = normalize_unit_name(unit_name)
        if not prop or not normalized_alias:
            return None
        target = self._aliases.get(prop, {}).get(normalized_alias)
        if target is None:
            return None
        return UnitAliasMatch(prop, str(unit_name or "").strip(), target)

    def _validate_and_load(self, aliases: Mapping[str, Mapping[str, str]]) -> None:
        for raw_prop, raw_aliases in aliases.items():
            prop = str(raw_prop).strip()
            if not prop:
                raise UnitAliasRegistryError("Alias property name cannot be blank")
            if prop not in self._units_by_property:
                raise UnitAliasRegistryError(f"Alias property does not exist in canonical Rent Roll: {prop}")
            if not isinstance(raw_aliases, Mapping):
                raise UnitAliasRegistryError(f"Aliases for property must be an object: {prop}")

            canonical_units = self._units_by_property[prop]
            canonical_by_casefold: Dict[str, list[str]] = {}
            for unit in canonical_units:
                canonical_by_casefold.setdefault(unit.casefold(), []).append(unit)

            loaded: Dict[str, str] = {}
            for raw_alias, raw_target in raw_aliases.items():
                alias = normalize_unit_name(raw_alias)
                target = str(raw_target).strip()
                if not alias:
                    raise UnitAliasRegistryError(f"Unit alias cannot be blank for property: {prop}")
                if not target:
                    raise UnitAliasRegistryError(
                        f"Alias target cannot be blank for property {prop!r}, alias {raw_alias!r}"
                    )

                matches = canonical_by_casefold.get(target.casefold(), [])
                if len(matches) != 1:
                    raise UnitAliasRegistryError(
                        f"Alias target must resolve to exactly one canonical unit for property {prop!r}: "
                        f"alias={raw_alias!r}, target={target!r}"
                    )
                canonical_target = matches[0]

                existing = loaded.get(alias)
                if existing is not None and existing.casefold() != canonical_target.casefold():
                    raise UnitAliasRegistryError(
                        f"Conflicting 1:N unit alias for property {prop!r}: alias={raw_alias!r}"
                    )
                loaded[alias] = canonical_target

            self._aliases[prop] = loaded


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UnitAliasRegistryError(f"Duplicate JSON key in unit alias registry: {key!r}")
        result[key] = value
    return result
