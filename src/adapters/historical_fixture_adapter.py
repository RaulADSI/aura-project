import re
from typing import Any, Dict, List, Optional, Tuple

from src.adapters.property_resolver import PropertyResolver


# Historical OCR/cache addresses embed unit identifiers inside service_address.
# Keep this parser intentionally conservative: only explicit unit markers are split.
UNIT_PATTERN = re.compile(
    r"(?:\bAPT\.?\s*|\bUNIT\s*|\bSTE\.?\s*|\bSUITE\s*|\bBLDG\s*|\bLOT\s*|#\s*)([A-Z0-9-]+)",
    re.IGNORECASE,
)


def parse_service_address(raw_address: str) -> Tuple[str, str]:
    if not raw_address:
        return "", ""

    address = re.sub(r"\s+", " ", str(raw_address)).strip()
    match = UNIT_PATTERN.search(address)
    if not match:
        return address, ""

    unit_name = match.group(1).strip()
    before = address[: match.start()].rstrip(" ,;:-")
    after = address[match.end() :].lstrip(" ,;:-")

    # Preserve a delimiter between the street portion and locality instead of
    # accidentally concatenating them (e.g. "AVE NEATLANTA").
    clean_property = ", ".join(part for part in (before, after) if part)
    clean_property = re.sub(r"\s+", " ", clean_property).strip(" ,")

    return clean_property, unit_name


class HistoricalFixtureAdapter:
    """Translate the frozen historical OCR fixture into the current AutoStack shape."""

    @staticmethod
    def transform_payload(raw_item: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(raw_item)

        # Respect already-normalized/current payloads.
        if payload.get("property_name"):
            payload.setdefault("unit_name", "")
            return payload

        raw_address = str(payload.get("service_address") or "")
        property_name, unit_name = parse_service_address(raw_address)
        payload["property_name"] = property_name
        payload["unit_name"] = unit_name
        return payload

    @classmethod
    def transform_batch(
        cls,
        raw_batch: List[Dict[str, Any]],
        property_resolver: Optional[PropertyResolver] = None,
    ) -> List[Dict[str, Any]]:
        transformed: List[Dict[str, Any]] = []
        for item in raw_batch:
            payload = cls.transform_payload(item)
            if property_resolver is not None:
                resolution = property_resolver.resolve(payload.get("property_name", ""))
                payload["property_resolution_status"] = resolution.status.value
                payload["property_resolution_candidates"] = list(resolution.candidates)
                if resolution.resolved and resolution.canonical_property_name:
                    payload["property_name"] = resolution.canonical_property_name
            transformed.append(payload)
        return transformed
