import json
import os
import re
from decimal import Decimal
from typing import Any, Dict, Tuple
import pandas as pd

from src.domain.models import AccountingContext, OccupancyContext, PropertyContext
from src.domain.normalization import generate_match_key


class AppFolioAdapter:

    MONEY_QUANTUM = Decimal("0.01")

    def __init__(self, data_path: str):
        self.data_path = data_path

    # ------------------------------------------------------------------
    # 1. RENT ROLL CONTEXTS
    # ------------------------------------------------------------------
    def load_rent_roll_contexts(
        self, file_name: str = "rent_roll.json"
    ) -> Dict[str, Tuple[PropertyContext, OccupancyContext]]:
        """
        Carga el Rent Roll y mapea a Contextos de Dominio por match_key.
        Sin dependencias de DataExtractor ni validación de negocio legacy.
        """
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path):
            return {}

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            raise ValueError(f"Formato legacy detectado en {file_name}. Se requiere diccionario jerárquico.")

        contexts: Dict[str, Tuple[PropertyContext, OccupancyContext]] = {}

        for prop_address, content in data.items():
            units_dict = content.get("units", {})
            for unit_id, details in units_dict.items():
                match_key = generate_match_key(prop_address, unit_id)
                if not match_key:
                    continue

                m_in = pd.to_datetime(details.get("move_in", ""), errors="coerce")
                m_out = pd.to_datetime(details.get("lease_to", ""), errors="coerce")

                unit_name = unit_id if unit_id else "UNIT"

                prop_ctx = PropertyContext(
                    property_id=None,
                    property_name=prop_address,
                    unit_name=unit_name,
                    unit_type=details.get("unit_type", "UNIT"),
                )

                occ_ctx = OccupancyContext(
                    tenant_name=details.get("tenant") or None,
                    unit_status=details.get("status") or None,
                    move_in_date=m_in.date() if pd.notna(m_in) else None,
                    move_out_date=m_out.date() if pd.notna(m_out) else None,
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
        Carga y agrega AppFolio Bills en AccountingContext mapeados por match_key.
        Filtra y prioriza cuentas GL de utilidades (58XX) cuando existen múltiples líneas.
        """
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path):
            return {}

        df = pd.read_csv(path, encoding="latin1")
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

        for col in ("property_name", "unit_name", "bill_date", "vendor_name"):
            if col in df.columns:
                df[col] = df[col].replace(["", "nan", "None"], pd.NA).ffill()

        df["bill_date"] = pd.to_datetime(df["bill_date"], errors="coerce")

        df["match_key"] = [
            generate_match_key(str(p), str(u))
            for p, u in zip(df["property_name"], df["unit_name"])
        ]

        df = df.dropna(subset=["match_key"])

        accounting_map: Dict[str, AccountingContext] = {}

        gl_col = "gl account" if "gl account" in df.columns else "gl_account"

        for match_key, group in df.groupby("match_key"):
            group = group.copy()
            if gl_col in group.columns:
                group["gl_code"] = group[gl_col].apply(self._extract_gl_code)
            else:
                group["gl_code"] = ""

            # Priorizar cuentas de utilidades (código que comienza en 58)
            utility_rows = group[group["gl_code"].str.startswith("58", na=False)]

            if not utility_rows.empty:
                total_paid = utility_rows["appfolio_amount"].sum()
                primary_gl = utility_rows["gl_code"].iloc[0]
            else:
                total_paid = group["appfolio_amount"].sum()
                valid_gls = group["gl_code"][group["gl_code"] != ""]
                primary_gl = valid_gls.iloc[0] if not valid_gls.empty else None

            accounting_map[str(match_key)] = AccountingContext(
                appfolio_amount_paid=total_paid,
                gl_account=primary_gl,
            )

        return accounting_map

    # ------------------------------------------------------------------
    # HELPER UTILITIES
    # ------------------------------------------------------------------
    def _parse_currency(self, val: Any) -> Decimal:
        if val is None or pd.isna(val):
            return Decimal("0.00")
        s = str(val).replace("$", "").replace(",", "").strip()
        if not s or s.lower() in {"nan", "none"}:
            return Decimal("0.00")
        try:
            return Decimal(s).quantize(self.MONEY_QUANTUM)
        except Exception:
            return Decimal("0.00")

    @staticmethod
    def _extract_gl_code(val: Any) -> str:
        if not val or pd.isna(val):
            return ""
        match = re.search(r"\b\d{4}\b", str(val))
        return match.group(0) if match else str(val).strip()