import pandas as pd
import os
import re
import logging
import json
from typing import List, Dict

logger = logging.getLogger(__name__)

class DataExtractor:
    """
    Responsible for:
    - Address normalization
    - Match key generation
    - Cleaning AppFolio bills
    - Cleaning Rent Roll exports
    """

    DEFAULT_NON_BILLABLE_UNITS = [
        "office", "model", "storage", "maint", "guest", "shop"
    ]

    STREET_REPLACEMENTS = {
        "STREET": "ST",
        "AVENUE": "AVE",
        "DRIVE": "DR",
        "ROAD": "RD",
        "COURT": "CT",
        "BOULEVARD": "BLVD"
    }

    def __init__(
        self,
        data_path: str,
        non_billable_units: List[str] | None = None
    ):
        self.data_path = data_path
        self.non_billable_units = (
            non_billable_units
            if non_billable_units is not None
            else self.DEFAULT_NON_BILLABLE_UNITS
        )

        # cache de normalización (performance)
        self._normalize_cache: Dict[str, str] = {}

    # --------------------------------------------------
    # NORMALIZATION
    # --------------------------------------------------
    def normalize_address(self, text: str) -> str:
        """
        Normalize addresses to a deterministic alphanumeric key.
        Solves AppFolio duplications (e.g. West Street).
        """
        if not text or pd.isna(text):
            return ""

        raw = str(text).strip()
        if raw.lower() in {"nan", "none"}:
            return ""

        if raw in self._normalize_cache:
            return self._normalize_cache[raw]

        s = raw.upper()

        # Replace street suffixes
        for k, v in self.STREET_REPLACEMENTS.items():
            s = s.replace(k, v)

        # Remove non-alphanumeric chars
        s = re.sub(r"[^A-Z0-9 ]", " ", s)
        s = re.sub(r"(UNIT|STE|APT|BUILDING|BLDG)", "", s)

        # Deduplicate only sequential words (safer)
        tokens = s.split()
        normalized = [tokens[0]] if tokens else []

        for t in tokens[1:]:
            if t != normalized[-1]:
                normalized.append(t)

        result = "".join(normalized).strip()
        self._normalize_cache[raw] = result
        return result

    # --------------------------------------------------
    # MATCH KEY
    # --------------------------------------------------
    def generate_match_key(self, property_name: str, unit_name: str) -> str:
        prop = self.normalize_address(property_name)
        unit = self.normalize_address(unit_name)

        if not prop:
            return ""

        # Single-family or malformed unit
        if not unit or unit in prop:
            return prop

        return f"{prop}{unit}"

    # --------------------------------------------------
    # APPFOLIO BILLS
    # --------------------------------------------------
    def clean_appfolio_bills(self, file_name: str) -> pd.DataFrame:
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path):
            logger.warning("Bills file not found: %s", path)
            return pd.DataFrame()

        df = pd.read_csv(path, encoding="latin1")
        df.columns = [c.strip().lower() for c in df.columns]

        # Monetary cleanup
        for col in ("paid", "unpaid"):
            if col in df.columns:
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace(r"[$,]", "", regex=True)
                    .pipe(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                )

        df["appfolio_amount"] = df.get("paid", 0) + df.get("unpaid", 0)

        # Column mapping
        df = df.rename(columns={
            "property": "property_name",
            "unit": "unit_name",
            "bill date": "bill_date",
            "payee": "vendor_name",
            "vendor": "vendor_name"
        })

        # Forward fill merged cells
        for col in ("property_name", "unit_name", "bill_date", "vendor_name"):
            if col in df.columns:
                df[col] = df[col].replace(["", "nan", "None"], pd.NA).ffill()

        df["bill_date"] = pd.to_datetime(df["bill_date"], errors="coerce")

        # Match key (vectorized-ish)
        df["match_key"] = [
            self.generate_match_key(p, u)
            for p, u in zip(df["property_name"], df["unit_name"])
        ]

        before = len(df)
        df = df.dropna(subset=["match_key", "bill_date"])
        dropped = before - len(df)

        if dropped:
            logger.info("Dropped %s bill rows due to missing keys/dates", dropped)

        return df

    def clean_rent_roll(self, file_name: str) -> pd.DataFrame:
        path = os.path.join(self.data_path, file_name)
        if not os.path.exists(path): return pd.DataFrame()

        # 0. LECTURA SEGURA (Soporte dual de encoding)
        try:
            df = pd.read_csv(path, encoding="utf-8", dtype=str)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin1", dtype=str)
            
        df.columns = [str(c).strip().lower() for c in df.columns]

        # 1. LIMPIEZA INICIAL: Quitar espacios en blanco y unificar nulos
        df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
        df = df.fillna("")

        # Variables para la máscara (en mayúsculas solo para la comparación lógica)
        unit_upper = df["unit"].str.upper()
        tenant_upper = df.get("tenant", pd.Series(dtype=str)).str.upper()
        status_upper = df.get("status", pd.Series(dtype=str)).str.upper()
        
        vacia = {"", "NAN", "NONE", "NAT"}

        # 2. IDENTIFICACIÓN DE PROPIEDADES (Lógica Vectorizada ultrarrápida)
        # Creamos una "máscara" booleana: True si es Propiedad, False si es Inquilino o Vacío
        is_property_mask = (~unit_upper.isin(vacia)) & (tenant_upper.isin(vacia)) & (status_upper.isin(vacia))

        # Donde la máscara es True, ponemos el nombre de la unidad (propiedad). Donde es False, ponemos NA
        df["property_name"] = df["unit"].where(is_property_mask, pd.NA)

        # LA MAGIA DE PANDAS: ffill() "arrastra" el último nombre válido hacia abajo a los inquilinos
        df["property_name"] = df["property_name"].ffill()

        # 3. RENOMBRAR Y FILTRAR
        df = df.rename(columns={
            "unit": "unit_name", "tenant": "tenant_name", "status": "unit_status",
            "move-in": "move_in_date", "move-out": "move_out_date"
        })

        # Solo nos quedamos con filas que tengan inquilinos (descartamos las cabeceras que ya procesamos)
        df = df[~df["tenant_name"].str.upper().isin(vacia)]

        # 4. GENERAR MATCH KEY (Aplicamos tu función normalizadora solo a las filas filtradas)
        df["match_key"] = [self.generate_match_key(p, u) for p, u in zip(df["property_name"], df["unit_name"])]
        
        # Convertir fechas después de limpiar
        df["move_in_date"] = pd.to_datetime(df["move_in_date"], errors="coerce")
        df["move_out_date"] = pd.to_datetime(df["move_out_date"], errors="coerce")

        return df
    # --------------------------------------------------
    # RENT ROLL JSON LOADER
    # --------------------------------------------------
    def load_rent_roll_json(self, file_name: str) -> pd.DataFrame:
        """
        Carga el Rent Roll desde el formato JSON jerárquico y lo aplana.
        """
        import json
        path = os.path.join(self.data_path, file_name)
        
        if not os.path.exists(path):
            print(f"[!] ERROR: Archivo JSON no encontrado: {path}")
            return pd.DataFrame()

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # BLINDAJE: Si el archivo es una lista vieja, avisamos al usuario
        if isinstance(data, list):
            print("[!] ERROR DE FORMATO: El archivo rent_roll.json actual es una lista antigua.")
            print("    -> Solución: Ejecuta 'python src/converter.py' para generar el nuevo formato.")
            return pd.DataFrame()
        
        flat_data = []
        for prop_address, content in data.items():
            units_dict = content.get('units', {})
            for unit_id, details in units_dict.items():
                flat_data.append({
                    "property_name": prop_address,
                    "unit_name": unit_id,
                    "tenant_name": details.get('tenant', ''),
                    "unit_status": details.get('status', ''),
                    "move_in_date": pd.to_datetime(details.get('move_in', ''), errors='coerce'),
                    "move_out_date": pd.to_datetime(details.get('lease_to', ''), errors='coerce'),
                    "match_key": self.generate_match_key(prop_address, unit_id)
                })
        
        df = pd.DataFrame(flat_data)
        print(f"[*] Rent Roll JSON aplanado: {len(df)} inquilinos listos para auditoría.")
        return df

    def is_single_family(self, property_name: str) -> bool:
        """Detecta si la propiedad es una casa individual basada en la longitud de la dirección."""
        return len(str(property_name)) > 15

    def validate_unit_consistency(self, property_name: str, unit_type: str) -> str:
        """Si es Single Family, forzamos que sea UNIT para evitar falsos positivos de áreas comunes."""
        if self.is_single_family(property_name) and unit_type == "COMMON_AREA":
            return "UNIT"
        return unit_type