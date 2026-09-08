import json
import logging
import os
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional

from src.domain.models import (
    AccountingContext,
    AuditAnomalyFlag,
    AuditRequest,
    AuditResult,
    AuditStatus,
    InvoiceData,
    OccupancyContext,
    PropertyContext,
    ZERO_MONEY,
    quantize_money,
)

logger = logging.getLogger(__name__)


class AuditEngine:

    def __init__(self, rules_path: str):
        """Inicializa el motor cargando las reglas de negocio desde utility_rules.json."""
        self.rules = {}
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                self.rules = json.load(f)
        else:
            logger.warning(f"No se encontró el archivo de reglas: {rules_path}")

    # ------------------------------------------------------------------
    # CORE AUDIT ENGINE (PURE DOMAIN DETERMINISTIC MACHINE)
    # ------------------------------------------------------------------
    def audit(self, request: AuditRequest) -> AuditResult:
        """
        Audita un AuditRequest individual de forma pura y determinista.
        Agnóstico de OCR, PDF, Pandas, regex de direcciones o fallbacks silenciosos.
        """
        anomalies: List[AuditAnomalyFlag] = []
        inv = request.invoice
        prop = request.property
        occ = request.occupancy
        acc = request.accounting

        # 1. Validar Periodo de Servicio
        if inv.service_start_date is None or inv.service_end_date is None:
            anomalies.append(AuditAnomalyFlag.MISSING_SERVICE_DATE)
            total_service_days = 0
            is_valid_period = False
        elif inv.service_start_date > inv.service_end_date:
            anomalies.append(AuditAnomalyFlag.INVALID_SERVICE_PERIOD)
            total_service_days = 0
            is_valid_period = False
        else:
            total_service_days = (inv.service_end_date - inv.service_start_date).days + 1
            is_valid_period = True

        # 2. Check Rent Roll Context
        if prop.property_name == "Unmatched Property" or prop.unit_name == "UNKNOWN":
            anomalies.append(AuditAnomalyFlag.MISSING_RENT_ROLL_CONTEXT)

        # Si el período de servicio es inválido/faltante -> ANOMALY_DETECTED inmediatamente
        if not is_valid_period:
            return AuditResult(
                request=request,
                status=AuditStatus.ANOMALY_DETECTED,
                calculated_bill_back=ZERO_MONEY,
                total_service_days=0,
                occupied_days=0,
                anomalies=tuple(anomalies),
                notes="Anomalía detectada: periodo de servicio inválido o incompleto.",
            )

        # 3. Validar / Clasificar GL
        gl_classification = self.classify_charge(acc.gl_account)
        if gl_classification == "OWNER_EXPENSE":
            return AuditResult(
                request=request,
                status=AuditStatus.OWNER_EXPENSE,
                calculated_bill_back=ZERO_MONEY,
                total_service_days=total_service_days,
                occupied_days=0,
                anomalies=tuple(anomalies),
                notes=f"Gasto del propietario (Cuenta GL: {acc.gl_account}).",
            )
        elif gl_classification == "ILLEGAL":
            return AuditResult(
                request=request,
                status=AuditStatus.ILLEGAL_GL,
                calculated_bill_back=ZERO_MONEY,
                total_service_days=total_service_days,
                occupied_days=0,
                anomalies=tuple(anomalies),
                notes=f"Cuenta GL no permitida para bill-back: {acc.gl_account}.",
            )

        # 4. Common Area
        is_common = (
            self.is_common_area_exception(prop.unit_name)
            or self.is_common_area_exception(prop.property_name)
            or prop.unit_type == "COMMON_AREA"
        )
        if is_common:
            return AuditResult(
                request=request,
                status=AuditStatus.COMMON_AREA,
                calculated_bill_back=ZERO_MONEY,
                total_service_days=total_service_days,
                occupied_days=0,
                anomalies=tuple(anomalies),
                notes="Unidad / Área común confirmada.",
            )

        # 5. Calcular occupied_days (Pure Date Logic)
        raw_occupied_days = self.calculate_occupied_days(
            inv.service_start_date,
            inv.service_end_date,
            occ.move_in_date,
            occ.move_out_date,
        )
        occupied_days = min(raw_occupied_days, total_service_days)

        # 6. Evaluate Vacant
        if occupied_days == 0 or occ.tenant_name is None:
            return AuditResult(
                request=request,
                status=AuditStatus.VACANT,
                calculated_bill_back=ZERO_MONEY,
                total_service_days=total_service_days,
                occupied_days=0,
                anomalies=tuple(anomalies),
                notes="Unidad vacante o sin ocupación durante el periodo de servicio.",
            )

        # 7. Bill-back calculation (BILLABLE)
        calculated_bill_back = self.calculate_bill_back(
            amount=inv.amount,
            service_days=total_service_days,
            occupied_days=occupied_days,
        )

        notes_str = f"Inquilino: {occ.tenant_name} | Días ocupados: {occupied_days}/{total_service_days}"
        if AuditAnomalyFlag.MISSING_RENT_ROLL_CONTEXT in anomalies:
            notes_str += " (Advertencia: propiedad no encontrada en Rent Roll)"

        return AuditResult(
            request=request,
            status=AuditStatus.BILLABLE,
            calculated_bill_back=calculated_bill_back,
            total_service_days=total_service_days,
            occupied_days=occupied_days,
            anomalies=tuple(anomalies),
            notes=notes_str,
        )

    # ------------------------------------------------------------------
    # PURE CALCULATIONS & HELPERS (NO PANDAS DEPENDENCY)
    # ------------------------------------------------------------------
    def is_common_area_exception(self, address: Optional[str]) -> bool:
        if not address:
            return False
        keywords = self.rules.get(
            "common_area_units",
            ["LNDRM", "PUMP", "HOUSE", "COMMON", "AREA"],
        )
        addr_upper = str(address).upper()
        return any(str(kw).upper() in addr_upper for kw in keywords)

    def classify_charge(self, gl_account: Any, description: str = "") -> str:
        if gl_account is None:
            return "UNKNOWN"
        gl_str = str(gl_account).strip()
        if not gl_str or gl_str.lower() in ["nan", "none"]:
            return "UNKNOWN"

        owner_gls = [str(g).strip() for g in self.rules.get("owner_expense_gl_accounts", [])]
        if gl_str in owner_gls:
            return "OWNER_EXPENSE"

        allowed_gls = [str(g).strip() for g in self.rules.get("allowed_gl_accounts", [])]
        if allowed_gls and gl_str not in allowed_gls:
            return "ILLEGAL"

        return "BILLABLE"

    def _to_date(self, val: Any) -> Optional[date]:
        """Convierte cadenas ISO o date/datetime en un objeto date puro."""
        if val is None:
            return None
        if isinstance(val, date):
            return val
        s_val = str(val).strip()
        if not s_val or s_val.lower() in ("none", "nan", "nat", "null"):
            return None
        try:
            parts = s_val.split("T")[0].split("-")
            if len(parts) == 3:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
        return None

    def calculate_occupied_days(
        self,
        s_start: Any,
        s_end: Any,
        m_in: Any,
        m_out: Any,
    ) -> int:
        """
        Calcula días ocupados entre s_start y s_end (inclusivo) usando tipos date puros.
        """
        start = self._to_date(s_start)
        end = self._to_date(s_end)
        tenant_in = self._to_date(m_in)
        tenant_out = self._to_date(m_out) if m_out is not None else None

        if start is None or end is None or tenant_in is None or start > end:
            return 0

        effective_out = tenant_out if tenant_out is not None else date.max

        overlap_start = max(start, tenant_in)
        overlap_end = min(end, effective_out)

        if overlap_start > overlap_end:
            return 0

        return (overlap_end - overlap_start).days + 1

    def calculate_bill_back(
        self,
        amount: Decimal,
        service_days: int,
        occupied_days: int,
    ) -> Decimal:
        """
        Cálculo puro de prorrateo en Decimal cuantizado mediante primitive de dominio.
        """
        if service_days <= 0 or occupied_days <= 0:
            return ZERO_MONEY

        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))

        if amount <= ZERO_MONEY:
            return ZERO_MONEY

        capped_occupied = min(occupied_days, service_days)
        result = (amount * Decimal(capped_occupied)) / Decimal(service_days)

        return quantize_money(result)
