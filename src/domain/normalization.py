import re
from typing import Optional


STREET_REPLACEMENTS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "DRIVE": "DR",
    "ROAD": "RD",
    "COURT": "CT",
    "BOULEVARD": "BLVD",
}


def normalize_address(text: Optional[str]) -> str:
    """
    Normalize addresses to a deterministic alphanumeric key.
    Pure Python implementation without Pandas dependency.
    """
    if text is None:
        return ""

    raw = str(text).strip()
    if not raw or raw.lower() in {"nan", "none", "null"}:
        return ""

    s = raw.upper()

    for k, v in STREET_REPLACEMENTS.items():
        s = s.replace(k, v)

    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(UNIT|STE|APT|BUILDING|BLDG)\b", "", s)

    tokens = s.split()
    if not tokens:
        return ""

    normalized = [tokens[0]]
    for t in tokens[1:]:
        if t != normalized[-1]:
            normalized.append(t)

    return "".join(normalized).strip()


def generate_match_key(property_name: str, unit_name: str) -> str:
    prop = normalize_address(property_name)
    unit = normalize_address(unit_name)

    if not prop:
        return ""

    if not unit or unit == "UNIT" or unit in prop:
        return prop

    return f"{prop}{unit}"
