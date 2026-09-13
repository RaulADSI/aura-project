"""Service eligibility only: never calculate a tenant charge here."""
from dataclasses import dataclass
from enum import Enum


class UtilityEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    COMMON_AREA = "COMMON_AREA"
    NON_BILLABLE = "NON_BILLABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class EligibilityDecision:
    outcome: UtilityEligibility
    reason: str


class UtilityBillBackEligibilityPolicy:
    def __init__(self, non_billable_services=()):
        if not isinstance(non_billable_services, (list, tuple)):
            raise ValueError("non_billable_services must be a list")
        self._excluded = {}
        for entry in non_billable_services:
            if not isinstance(entry, dict) or set(entry) != {"vendor_code", "routing_key", "reason"}:
                raise ValueError("Non-billable service requires vendor_code, routing_key and reason")
            if any(not isinstance(v, str) or not v.strip() for v in entry.values()):
                raise ValueError("Non-billable service fields must be nonblank text")
            key = (entry["vendor_code"], entry["routing_key"])
            if key in self._excluded:
                raise ValueError(f"Duplicate non-billable service: {key}")
            self._excluded[key] = entry["reason"]

    def evaluate(self, *, vendor_code, routing_key, identity_type):
        if identity_type == "COMMON_AREA":
            return EligibilityDecision(UtilityEligibility.COMMON_AREA, "Configured common-area identifier")
        reason = self._excluded.get((vendor_code, routing_key))
        if reason is not None:
            return EligibilityDecision(UtilityEligibility.NON_BILLABLE, reason)
        if vendor_code == "GEORGIA_POWER" and identity_type == "UNIT":
            return EligibilityDecision(UtilityEligibility.ELIGIBLE, "Georgia Power residential unit")
        return EligibilityDecision(UtilityEligibility.REVIEW_REQUIRED, "Service not covered by bill-back policy")
