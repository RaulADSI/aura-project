from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, auto
from typing import Optional, Tuple


class AuditStatus(Enum):
    BILLABLE = auto()
    NON_BILLABLE = auto()
    OWNER_EXPENSE = auto()
    COMMON_AREA = auto()
    VACANT = auto()
    ILLEGAL_GL = auto()
    ANOMALY_DETECTED = auto()


class AuditAnomalyFlag(Enum):
    INVALID_SERVICE_PERIOD = auto()
    MISSING_SERVICE_DATE = auto()
    INVALID_OCCUPANCY_PERIOD = auto()
    OVERLAPPING_TENANTS = auto()
    MISSING_RENT_ROLL_CONTEXT = auto()


@dataclass(frozen=True)
class InvoiceData:
    invoice_id: str
    invoice_number: Optional[str]
    account_number: str
    vendor_name: str
    service_start_date: Optional[date]
    service_end_date: Optional[date]
    amount: Decimal


@dataclass(frozen=True)
class PropertyContext:
    property_id: Optional[str]
    property_name: str
    unit_name: str
    unit_type: str = "UNIT"


@dataclass(frozen=True)
class OccupancyContext:
    tenant_name: Optional[str] = None
    unit_status: Optional[str] = None
    move_in_date: Optional[date] = None
    move_out_date: Optional[date] = None


@dataclass(frozen=True)
class AccountingContext:
    appfolio_amount_paid: Decimal = Decimal("0.00")
    gl_account: Optional[str] = None


@dataclass(frozen=True)
class AuditRequest:
    invoice: InvoiceData
    property: PropertyContext
    occupancy: OccupancyContext
    accounting: AccountingContext


@dataclass(frozen=True)
class AuditResult:
    request: AuditRequest
    status: AuditStatus
    calculated_bill_back: Decimal
    total_service_days: int
    occupied_days: int
    anomalies: Tuple[AuditAnomalyFlag, ...] = ()
    notes: str = ""