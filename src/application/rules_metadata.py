"""Read versioned rule metadata without changing AuditEngine behavior."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RulesMetadata:
    rule_version: str
    rules_hash: str


def load_rules_metadata(path: str | Path) -> RulesMetadata:
    rules_path = Path(path)
    raw = rules_path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    rule_version = data.get("rule_version")
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("utility_rules.rule_version must be a nonblank string")
    return RulesMetadata(
        rule_version=rule_version.strip(),
        rules_hash=hashlib.sha256(raw).hexdigest(),
    )
