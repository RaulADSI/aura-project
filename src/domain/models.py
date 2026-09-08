from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum, auto
from typing import Optional, Tuple

MONEY_QUANTUM = Decimal("0.01")
ZERO_MONEY = Decimal("0.00")
MONEY_ROUNDING = ROUND_HALF_UP


def quantize_money(value: Decimal) -> Decimal:
    """
    Primitive para cuantizar valores monetarios a 2 decimales usando ROUND_HALF_UP.
    Aislada de cualquier modificación del contexto global de decimal.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"value must be Decimal, got {type(value).__name__}")
    return value.quantize(MONEY_QUANTUM, rounding=MONEY_ROUNDING)


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


ZERO_STATUSES = frozenset({
    AuditStatus.VACANT,
    AuditStatus.OWNER_EXPENSE,
    AuditStatus.ILLEGAL_GL,
    AuditStatus.COMMON_AREA,
    AuditStatus.ANOMALY_DETECTED,
    AuditStatus.NON_BILLABLE,
})


@dataclass(frozen=True)
class InvoiceData:
    invoice_id: str
    invoice_number: Optional[str]
    account_number: str
    vendor_name: str
    service_start_date: Optional[date]
    service_end_date: Optional[date]
    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"amount must be Decimal, got {type(self.amount).__name__}")
        if self.amount < ZERO_MONEY:
            raise ValueError("amount cannot be negative")


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

    def __post_init__(self) -> None:
        if not isinstance(self.appfolio_amount_paid, Decimal):
            raise TypeError(
                f"appfolio_amount_paid must be Decimal, got {type(self.appfolio_amount_paid).__name__}"
            )
        if self.appfolio_amount_paid < ZERO_MONEY:
            raise ValueError("appfolio_amount_paid cannot be negative")


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

    def __post_init__(self) -> None:
        if not isinstance(self.calculated_bill_back, Decimal):
            raise TypeError(
                f"calculated_bill_back must be Decimal, got {type(self.calculated_bill_back).__name__}"
            )

        if self.total_service_days < 0:
            raise ValueError("total_service_days cannot be negative")

        if self.occupied_days < 0:
            raise ValueError("occupied_days cannot be negative")

        if self.occupied_days > self.total_service_days:
            raise ValueError("occupied_days cannot exceed total_service_days")

        if self.total_service_days == 0 and self.occupied_days != 0:
            raise ValueError("occupied_days must be zero when total_service_days is zero")

        if self.status in ZERO_STATUSES:
            if quantize_money(self.calculated_bill_back) != ZERO_MONEY:
                raise ValueError(f"{self.status.name} requires zero bill-back")
