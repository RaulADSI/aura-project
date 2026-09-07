import pandas as pd
import json
import os
import re
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class AuditEngine:
    def __init__(self, rules_path: str):
        """Inicializa el motor cargando las reglas de negocio (Cuentas GL, Áreas Comunes)"""
        self.rules = {}
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                self.rules = json.load(f)
        else:
            logger.warning(f"No se encontró el archivo de reglas: {rules_path}")

    def is_common_area_exception(self, address: str) -> bool:
        """Verifica si la dirección contiene palabras clave de áreas comunes de nuestro JSON."""
        if not address: return False
        
        # Leemos la lista exacta de tu archivo utility_rules.json
        keywords = self.rules.get("common_area_units", [
            "LNDRM", "PUMP", "HOUSE", "COMMON", "AREA"
        ])
        
        addr_upper = str(address).upper()
        # Si alguna de las unidades especiales (Ej: "AHSE", "LED LTS") está en el OCR, es Área Común
        return any(str(kw).upper() in addr_upper for kw in keywords)

    def classify_charge(self, gl_account: Any, description: str = "") -> str:
        """Determina si un gasto es cobrable según las listas GL de AppFolio."""
        gl_str = str(gl_account).strip()
        if not gl_str or gl_str.lower() in ['nan', 'none']:
            return "UNKNOWN"
            
        # 1. ¿Es un gasto exclusivo del dueño? (Ej: 5810, 5820)
        owner_gls = self.rules.get("owner_expense_gl_accounts", [])
        if gl_str in owner_gls:
            return "OWNER_EXPENSE"
            
        # 2. ¿Es un gasto estrictamente permitido para Bill-Back? (Ej: 5815, 5825)
        allowed_gls = self.rules.get("allowed_gl_accounts", [])
        if allowed_gls and gl_str not in allowed_gls:
            # Si hay una lista de permitidos y esta cuenta NO está ahí, la bloqueamos
            return "ILLEGAL" 
            
        return "BILLABLE"

    def find_tenant_at_date(self, match_key: str, service_date: Any, df_rent_roll: pd.DataFrame, raw_ocr_address: str = "") -> Optional[pd.Series]:
        """Motor de búsqueda blindado con Ancla Numérica para evitar cruces de propiedades."""
        if df_rent_roll.empty: return None
        
        # 1. INTENTO DE MATCH DIRECTO (Usando la llave generada)
        matches = df_rent_roll[df_rent_roll['match_key'] == match_key]
        
        # 2. MOTOR DE TOKENS (Si el match directo falla)
        if matches.empty and raw_ocr_address:
            # Limpiar OCR
            ocr_clean = re.sub(r"(?i)(GA|GEORGIA|ATLANTA|FOREST PARK|LAWRENCEVILLE|CUMMING|CLARKSTON|STONE MOUNTAIN|DECATUR|JONESBORO|\d{5})", "", str(raw_ocr_address))
            ocr_clean = re.sub(r"[^A-Z0-9 ]", " ", ocr_clean.upper())
            ocr_tokens = set(ocr_clean.split())
            
            # Palabras que NO suman puntos
            stop_words = {"DR", "ST", "AVE", "LN", "BLVD", "RD", "CT", "WAY", "CIR", "PL", "DRIVE", "ROAD", "LANE", "STREET", "COURT", "APT", "UNIT", "STE", "SUITE", "NE", "NW", "SE", "SW"}
            ocr_tokens_strong = ocr_tokens - stop_words
            
            best_score = 0
            best_idx = None
            
            for idx, row in df_rent_roll.iterrows():
                rr_prop = str(row.get('property_name', '')).upper()
                rr_unit = str(row.get('unit_name', '')).upper()
                
                # --- Limpieza estricta de APT y UNIT ---
                rr_unit_clean = re.sub(r"\b(APT|UNIT|STE|SUITE|#)\b", "", rr_unit).strip()
                unit_num = re.sub(r"[^A-Z0-9]", "", rr_unit_clean)
                
                # --- Tokens de la Propiedad ---
                rr_prop_clean = re.sub(r"(?i)(GA|GEORGIA|ATLANTA|FOREST PARK|LAWRENCEVILLE|CUMMING|CLARKSTON|STONE MOUNTAIN|DECATUR|JONESBORO|\d{5})", "", rr_prop)
                rr_prop_tokens = set(re.sub(r"[^A-Z0-9 ]", " ", rr_prop_clean).split()) - stop_words
                
                prop_intersection = ocr_tokens_strong.intersection(rr_prop_tokens)
                
                if len(prop_intersection) == 0:
                    continue
                    
                # --- EL ANCLA NUMÉRICA DE LA PROPIEDAD ---
                ocr_numbers = {t for t in ocr_tokens_strong if any(c.isdigit() for c in t)}
                prop_numbers = {t for t in rr_prop_tokens if any(c.isdigit() for c in t)}
                
                # ¿Tienen el mismo número de calle principal?
                has_number_match = len(ocr_numbers.intersection(prop_numbers)) > 0
                
                # --- LÓGICA DE UNIDADES ESTRICTA ---
                is_unit_match = False
                
                # Extraemos posibles números de apartamento del OCR (que no sean el número de la calle)
                ocr_potential_units = ocr_numbers - prop_numbers

                if unit_num == "" or unit_num == "UNIT": 
                    # Es una casa (Single Family)
                    is_unit_match = True 
                elif unit_num in ocr_potential_units or unit_num in ocr_tokens:
                    # Match exacto de apartamento (ej. "11" in {"11"})
                    is_unit_match = True
                elif unit_num.endswith("AR") and "A" in ocr_tokens:
                    is_unit_match = True
                elif unit_num.endswith("BR") and "B" in ocr_tokens:
                    is_unit_match = True
                else:
                    # MATCH ESTRICTO: Si el Rent Roll dice Apt 11, y en el OCR no está el 11, RECHAZAR.
                    is_unit_match = False

                # --- CONDICIÓN DE VICTORIA ESTRICTA ---
                if len(prop_numbers) > 0:
                    valid_prop_match = has_number_match and len(prop_intersection) >= 2
                else:
                    valid_prop_match = len(prop_intersection) >= 2
                
                if is_unit_match and valid_prop_match:
                    score = len(prop_intersection) + (5 if has_number_match else 0) + (10 if unit_num and unit_num in ocr_tokens else 0)
                    if score > best_score:
                        best_score = score
                        best_idx = idx

            if best_idx is not None:
                matches = df_rent_roll.loc[[best_idx]]

        # Si después de todo no hay un match claro de propiedad y unidad, retorna None
        if matches.empty: 
            return None
        
        # 3. VERIFICACIÓN DE FECHAS ESTRICTA
        try:
            # Si no hay fecha de servicio, no podemos auditar, pero asumimos que el match es el inquilino actual
            if pd.isna(service_date) or not str(service_date).strip():
                return matches.iloc[0]

            s_date = pd.to_datetime(service_date)
            m_in = pd.to_datetime(matches['move_in_date'], errors='coerce').fillna(pd.Timestamp.min)
            
            # Muchos inquilinos current no tienen move_out_date, lo rellenamos con el futuro
            m_out = pd.to_datetime(matches['move_out_date'], errors='coerce').fillna(pd.Timestamp.max)
            
            date_mask = (m_in <= s_date) & (m_out >= s_date)
            final_matches = matches[date_mask]
            
            if final_matches.empty:
                # ¡AQUÍ ESTABA EL ERROR CRÍTICO! 
                # Antes retornaba matches.iloc[0] (el inquilino incorrecto). Ahora retorna None (Vacante)
                return None
            
            return final_matches.iloc[0]
        except Exception as e:
            # Si las fechas están totalmente corruptas, preferimos reportarlo como vacante a cobrarle al vecino
            return None

    def validate_classification(self, property_name: str, unit_name: str, current_type: str, df_rent_roll: pd.DataFrame) -> str:
        """Cruza los datos para asegurar que no facturamos áreas comunes por error."""
        if self.is_common_area_exception(unit_name):
            return "COMMON_AREA"
        return current_type

    def calculate_occupied_days(self, s_start: Any, s_end: Any, m_in: Any, m_out: Any) -> int:
        """Calcula cuántos días vivió realmente el inquilino durante el ciclo de facturación."""
        try:
            start = pd.to_datetime(s_start)
            end = pd.to_datetime(s_end)
            tenant_in = pd.to_datetime(m_in)
            tenant_out = pd.to_datetime(m_out) if pd.notna(m_out) and str(m_out).strip() else pd.Timestamp.max
            
            # --- SEGURO ANTI-ALUCINACIÓN DE FECHAS ---
            # Si Gemini invirtió las fechas (ej. Start: Feb 2, End: Jan 30), las enderezamos
            if pd.notna(start) and pd.notna(end) and start > end:
                start, end = end, start
                
            if pd.isna(start) or pd.isna(end):
                return 30 # Fallback: Si no hay fechas, asumimos ciclo estándar
                
            overlap_start = max(start, tenant_in)
            overlap_end = min(end, tenant_out)
            
            if overlap_start > overlap_end:
                return 0
                
            return (overlap_end - overlap_start).days + 1
        except Exception:
            return 30 # En caso de error crítico con los formatos, asumimos el mes completo

    def calculate_bill_back(self, appfolio_amount: float, service_days: int, occupied_days: int, ocr_current_charge: float) -> float:
        """Calcula el monto proporcional en dólares ($) para cobrar al inquilino."""
        # --- PARCHE PARA CICLOS MENSUALES SIN FECHA ---
        # Si la resta de fechas de la IA dio 0 o negativo, forzamos un ciclo mensual de 30 días
        if service_days <= 0:
            service_days = 30  
            
        if occupied_days <= 0:
            return 0.0
            
        base_amount = ocr_current_charge if ocr_current_charge > 0 else appfolio_amount
        if base_amount <= 0:
            return 0.0
            
        daily_rate = base_amount / service_days
        
        # Tope de seguridad: Nunca cobrarle a alguien más días de los que tiene el ciclo
        final_occupied = min(occupied_days, service_days)
        
        return round(daily_rate * final_occupied, 2)
    
   