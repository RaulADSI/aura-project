import json
import os
import re
from decimal import Decimal
from typing import Any, Dict, Tuple, Optional
import pandas as pd

from src.adapters.utils import (
    AdapterValidationError,
    parse_decimal,
    parse_optional_iso_date,
    sanitize_string,
)
from src.domain.models import AccountingContext, OccupancyContext, PropertyContext
from src.domain.normalization import generate_match_key


class AppFolioAdapter:

    MONEY_QUANTUM = Decimal("0.01")
    SOURCE_NAME = "AppFolio"

    def __init__(self, data_path: str):
        self.data_path = data_path

    # ------------------------------------------------------------------
    # 1. RENT ROLL CONTEXTS
    # ------------------------------------------------------------------
    def load_rent_roll_contexts(
        self, file_name: str = "rent_roll.json"
    ) -> Dict[str, Tuple[PropertyContext, OccupancyContext]]:
        """
        Loads Rent Roll data and maps it to Domain Contexts by match_key.
        Completely decoupled from DataExtractor or legacy business validation.
        """
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise AdapterValidationError(
                f"Failed to parse JSON rent roll file '{file_name}': {e}",
                source=self.SOURCE_NAME,
            ) from e

        if isinstance(data, list):
            raise AdapterValidationError(
                f"Legacy array format detected in {file_name}. Expected hierarchical dict.",
                source=self.SOURCE_NAME,
            )

        if not isinstance(data, dict):
            raise AdapterValidationError(
                f"Rent roll file '{file_name}' must be a dictionary.",
                source=self.SOURCE_NAME,
            )

        contexts: Dict[str, Tuple[PropertyContext, OccupancyContext]] = {}

        for prop_address, content in data.items():
            if not isinstance(content, dict):
                continue
            units_dict = content.get("units", {})
            if not isinstance(units_dict, dict):
                continue

            for unit_id, details in units_dict.items():
                if not isinstance(details, dict):
                    details = {}

                clean_prop = self._clean_text(prop_address)
                clean_unit = self._clean_text(unit_id)

                match_key = generate_match_key(clean_prop, clean_unit)
                if not match_key:
                    continue

                m_in = parse_optional_iso_date(
                    details.get("move_in"),
                    field="move_in",
                    record_id=match_key,
                    source=self.SOURCE_NAME,
                )
                m_out = parse_optional_iso_date(
                    details.get("lease_to") or details.get("move_out"),
                    field="move_out",
                    record_id=match_key,
                    source=self.SOURCE_NAME,
                )

                unit_name_clean = sanitize_string(unit_id)
                unit_name = unit_name_clean if unit_name_clean else "UNIT"

                tenant_clean = sanitize_string(details.get("tenant"))
                unit_status_clean = sanitize_string(details.get("status"))

                prop_ctx = PropertyContext(
                    property_id=None,
                    property_name=prop_address,
                    unit_name=unit_name,
                    unit_type=sanitize_string(details.get("unit_type")) or "UNIT",
                )

                occ_ctx = OccupancyContext(
                    tenant_name=tenant_clean or None,
                    unit_status=unit_status_clean or None,
                    move_in_date=m_in,
                    move_out_date=m_out,
                )

                contexts[match_key] = (prop_ctx, occ_ctx)

        return contexts

    # ------------------------------------------------------------------
    # 2. ACCOUNTING CONTEXTS
    # ------------------------------------------------------------------
    def load_accounting_contexts(
        self, file_name: str = "appfolio_bills.csv"
    ) -> Dict[str, AccountingContext]:
        """
        Loads and aggregates AppFolio Bills into AccountingContext mapped by match_key.
        Generates both unit-level and property-level match keys.
        """
        df = self._load_and_normalize_bills_df(file_name)
        if df is None or df.empty:
            return {}

        accounting_map: Dict[str, AccountingContext] = {}
        gl_col = "gl account" if "gl account" in df.columns else "gl_account"

        # Indexing by unit-level match key
        for unit_key, group in df.groupby("unit_key"):
            if not unit_key:
                continue
            accounting_map[str(unit_key)] = self._build_accounting_context(group, gl_col)

        # Indexing by property-level match key (aggregating all rows for that property)
        for prop_key, group in df.groupby("property_key"):
            if not prop_key:
                continue
            # If unit-level charging exists, property_key shouldn't overwrite unit_key unless unit_key wasn't set
            if str(prop_key) not in accounting_map:
                accounting_map[str(prop_key)] = self._build_accounting_context(group, gl_col)

        return accounting_map

    # ------------------------------------------------------------------
    # HELPER SUB-METHODS
    # ------------------------------------------------------------------
    def _load_and_normalize_bills_df(self, file_name: str) -> Optional[pd.DataFrame]:
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path):
            return None

        try:
            df = pd.read_csv(path, encoding="latin1")
        except Exception as e:
            raise AdapterValidationError(
                f"Failed to read CSV bills file '{file_name}': {e}",
                source=self.SOURCE_NAME,
            ) from e

        df.columns = [c.strip().lower() for c in df.columns]

        df["paid_dec"] = df.get("paid", 0).apply(self._parse_currency)
        df["unpaid_dec"] = df.get("unpaid", 0).apply(self._parse_currency)
        df["appfolio_amount"] = df["paid_dec"] + df["unpaid_dec"]

        df = df.rename(columns={
            "property": "property_name",
            "unit": "unit_name",
            "bill date": "bill_date",
            "payee": "vendor_name",
            "vendor": "vendor_name"
        })

        # Apply ffill ONLY to hierarchical headers (property, bill_date, vendor_name)
        # NEVER ffill unit_name to prevent property-level charges from inheriting units
        for col in ("property_name", "bill_date", "vendor_name"):
            if col in df.columns:
                df[col] = df[col].replace(["", "nan", "None", "null", "NaT", "<NA>", "<na>"], pd.NA).ffill()

        if "unit_name" in df.columns:
            df["unit_name"] = df["unit_name"].replace(["", "nan", "None", "null", "NaT", "<NA>", "<na>"], pd.NA)

        df["property_key"] = [
            generate_match_key(self._clean_text(p), "")
            for p in df.get("property_name", [])
        ]

        df["unit_key"] = [
            generate_match_key(self._clean_text(p), self._clean_text(u))
            for p, u in zip(df.get("property_name", []), df.get("unit_name", []))
        ]

        return df

    def _build_accounting_context(
        self,
        group: pd.DataFrame,
        gl_col: str,
    ) -> AccountingContext:

        group = group.copy()
        if gl_col in group.columns:
            group["gl_code"] = group[gl_col].apply(self._extract_gl_code)
        else:
            group["gl_code"] = ""

        utility_rows = group[group["gl_code"].str.startswith("58", na=False)]

        if not utility_rows.empty:
            valid_utility_gls = sorted(
                gl for gl in utility_rows["gl_code"].dropna().unique() if gl
            )
            primary_gl = valid_utility_gls[0] if valid_utility_gls else None
            primary_rows = utility_rows[utility_rows["gl_code"] == primary_gl]
            total_paid = primary_rows["appfolio_amount"].sum()
        else:
            valid_gls = sorted(
                gl for gl in group["gl_code"].dropna().unique() if gl
            )
            primary_gl = valid_gls[0] if valid_gls else None
            if primary_gl:
                primary_rows = group[group["gl_code"] == primary_gl]
                total_paid = primary_rows["appfolio_amount"].sum()
            else:
                total_paid = group["appfolio_amount"].sum()

        return AccountingContext(
            appfolio_amount_paid=Decimal(total_paid),
            gl_account=primary_gl if primary_gl else None,
        )

    def _parse_currency(self, val: Any) -> Decimal:
        if val is None or pd.isna(val):
            return Decimal("0.00")

        if isinstance(val, float):
            s_val = f"{val:.2f}"
        else:
            s_val = str(val)

        cleaned = self._clean_text(s_val)
        if not cleaned:
            return Decimal("0.00")

        try:
            return parse_decimal(
                cleaned,
                field="currency",
                source=self.SOURCE_NAME,
            )
        except AdapterValidationError as e:
            # If currency string is non-empty but malformed (e.g. "$xyz"), raise AdapterValidationError
            raise e

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""

        val_str = str(value).strip()
        if val_str.lower() in {"", "nan", "none", "null", "nat", "<na>"}:
            return ""

        return val_str

    @classmethod
    def _extract_gl_code(cls, val: Any) -> str:
        cleaned = cls._clean_text(val)
        if not cleaned:
            return ""
        match = re.search(r"\b\d{4}\b", cleaned)
        return match.group(0) if match else cleaned
