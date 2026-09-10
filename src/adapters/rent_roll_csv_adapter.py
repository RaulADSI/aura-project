"""Read hierarchical AppFolio rent roll CSV without dropping non-revenue units."""
import csv
from pathlib import Path

from src.adapters.utils import parse_optional_iso_date
from src.domain.models import OccupancyContext, PropertyContext
from src.domain.normalization import generate_match_key


def load_rent_roll_csv(path: str | Path):
    contexts = {}
    property_name = None
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Unit", "Tenant", "Status", "Move-in", "Move-out"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Rent roll CSV requires columns: " + ", ".join(sorted(required)))
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed rent roll CSV at line {reader.line_num}")
            row = {key: value.strip() for key, value in row.items()}
            if not any(row.values()):
                continue
            if row["Unit"].startswith("->"):
                property_name = row["Unit"]
                continue
            if not row["Status"]:
                # AppFolio summary/footer rows have no occupancy status.
                continue
            if property_name is None:
                raise ValueError(f"Unit before property header at line {reader.line_num}")
            unit = row["Unit"] or "UNIT"
            key = generate_match_key(property_name, unit)
            if key in contexts:
                raise ValueError(f"Duplicate rent roll unit at line {reader.line_num}: {unit}")
            def parsed_date(column):
                return parse_optional_iso_date(row[column], field=column,
                                               record_id=key, source="AppFolio Rent Roll CSV")
            contexts[key] = (
                PropertyContext(None, property_name, unit),
                OccupancyContext(row["Tenant"] or None, row["Status"] or None,
                                 parsed_date("Move-in"), parsed_date("Move-out")),
            )
    return contexts
