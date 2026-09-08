from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AdapterValidationError(ValueError):
    """Indica que un payload externo no cumple el contrato requerido."""

    def __init__(
        self,
        message: str,
        *,
        source: Optional[str] = None,
        field: Optional[str] = None,
        record_id: Optional[str] = None,
        value: object = None,
    ) -> None:
        self.source = source
        self.field = field
        self.record_id = record_id
        self.value = value
        super().__init__(message)


NULL_LIKE_STRINGS = frozenset({
    "",
    "nan",
    "none",
    "null",
    "nat",
})

MONEY_QUANTUM = Decimal("0.01")


def sanitize_string(value: object) -> str:
    """
    Sanitiza un valor convirtiéndolo en cadena limpia.
    Representaciones nulas (None, "nan", "none", "null", "nat") retornan "".
    """
    if value is None:
        return ""

    normalized = str(value).strip()

    if normalized.lower() in NULL_LIKE_STRINGS:
        return ""

    return normalized


def require_string(
    value: object,
    *,
    field: str,
    record_id: Optional[str] = None,
    source: Optional[str] = None,
) -> str:
    """
    Exige una cadena no vacía sanitizada. Lanza AdapterValidationError si está ausente/vacía.
    """
    result = sanitize_string(value)

    if not result:
        raise AdapterValidationError(
            f"Field '{field}' is required",
            source=source,
            field=field,
            record_id=record_id,
            value=value,
        )

    return result


def parse_decimal(
    value: object,
    *,
    field: str,
    record_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Decimal:
    """
    Parseo estricto de dinero a Decimal.
    Rechaza explícitamente float para evitar contaminación de precisión.
    Acepta Decimal, int, o str sanitizado (ej. "$1,234.56", "(123.45)").
    """
    if isinstance(value, float):
        raise AdapterValidationError(
            f"Field '{field}' cannot be float to preserve monetary precision. Pass string or Decimal.",
            source=source,
            field=field,
            record_id=record_id,
            value=value,
        )

    cleaned = sanitize_string(value)

    if not cleaned:
        raise AdapterValidationError(
            f"Field '{field}' is required and cannot be empty",
            source=source,
            field=field,
            record_id=record_id,
            value=value,
        )

    # Formato contable entre paréntesis "(123.45)" -> "-123.45"
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    # Remover caracteres monetarios comunes
    cleaned = cleaned.replace("$", "").replace(",", "").strip()

    try:
        dec = Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError):
        raise AdapterValidationError(
            f"Field '{field}' must be a valid decimal string, got: {value!r}",
            source=source,
            field=field,
            record_id=record_id,
            value=value,
        )

    if not dec.is_finite():
        raise AdapterValidationError(
            f"Field '{field}' must be a finite decimal, got: {value!r}",
            source=source,
            field=field,
            record_id=record_id,
            value=value,
        )

    return dec.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def parse_optional_iso_date(
    value: object,
    *,
    field: str,
    record_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Optional[date]:
    """
    Parsea una fecha opcional.
    Valor ausente/vacío ("","nan","nat",None) -> retorna None (para manejo en dominio).
    Valor presente pero malformado ("01/99/foobar") -> lanza AdapterValidationError.
    """
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    cleaned = sanitize_string(value)

    if not cleaned:
        return None

    # Remover horas ISO si están presentes "2026-01-15T00:00:00"
    clean_date_str = cleaned.split("T")[0].split(" ")[0].strip()

    try:
        return date.fromisoformat(clean_date_str)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean_date_str, fmt).date()
        except ValueError:
            pass

    raise AdapterValidationError(
        f"Field '{field}' has invalid date format: {value!r}",
        source=source,
        field=field,
        record_id=record_id,
        value=value,
    )
