import os, cv2, json, time, random, logging, warnings, re
import numpy as np
import pandas as pd
import pdfplumber
import easyocr
from pdf2image import convert_from_path
from google import genai
from google.api_core.exceptions import ResourceExhausted

warnings.filterwarnings("ignore", category=UserWarning)

CACHE_DIR = "data/03_output_log"
JSON_CACHE_FILE = os.path.join(CACHE_DIR, "ocr_extraction_data.json")

class UtilityOCR:
    def __init__(self, api_key=None):
        logging.info("Initializing Enhanced AURA OCR Engine...")
        self.reader = easyocr.Reader(['en'], gpu=False)
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.model_id = "gemini-2.0-flash"

    def _call_llm_safe(self, prompt, max_retries=8):
        for attempt in range(max_retries):
            try:
                return self.client.models.generate_content(model=self.model_id, contents=prompt)
            except ResourceExhausted:
                time.sleep(min((2 ** attempt), 45) + random.uniform(0.5, 1.5))
        raise RuntimeError("Gemini quota exhausted")

    def process_document(self, file_path):
        """
        NUEVA LÓGICA: Extrae texto por páginas completas. 
        No corta por TRIGGERS para no perder el contexto de las fechas.
        """
        pages_text = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    # Si la página es una imagen o el texto es muy pobre, aplicar OCR
                    if len(text.strip()) < 100:
                        img = convert_from_path(file_path, dpi=200, first_page=i+1, last_page=i+1)[0]
                        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                        text = " ".join(self.reader.readtext(img, detail=0))
                    pages_text.append(text)
        except Exception as e:
            logging.error(f"Error en PDF {file_path}: {e}")
            return []
        
        # Agrupamos el texto en bloques de ~10,000 caracteres para mantener el contexto
        full_text = "\n--- PAGE BREAK ---\n".join(pages_text)
        chunks = [full_text[i:i+10000] for i in range(0, len(full_text), 10000)]
        return chunks

    def analyze_text_with_llm(self, text, label):
        if not self.client or not text.strip(): return [self._empty_response(label)]
        
        # PROMPT REFORZADO PARA CAPTURA DE FECHAS
        prompt = f"""Return ONLY a valid JSON ARRAY of objects.
        
        INSTRUCTION:
        Extract utility billing data. If this is a CONSOLIDATED bill (like Gas South), extract EACH unit as a separate object.
        
        CRITICAL RULE FOR SERVICE DATES:
        1. Search for 'Service Period', 'Usage Period', 'Billing Cycle', or 'Dates of Service'.
        2. If 'service_start' is missing but you find 'service_end' (or Statement Date):
           - SET service_end = the found date.
           - SET service_start = service_end minus 30 days.
        3. If NO dates are found, look for meter read dates or the latest date on the page.
        4. Dates MUST be in YYYY-MM-DD format. Do not return null if any date exists.

        FINANCIAL RULES:
        - total_amount_due: Numeric value only. NO symbols ($, S), NO commas.
        - unit_type: Set to 'COMMON_AREA' if address contains Pool, Clubhouse, Leasing, or Laundry.

        Schema:
        [{{
          "utility_vendor": "string",
          "service_address": "string",
          "account_number": "string",
          "total_amount_due": number,
          "service_start": "YYYY-MM-DD",
          "service_end": "YYYY-MM-DD",
          "unit_type": "UNIT | COMMON_AREA"
        }}]

        TEXT:
        {text}"""

        try:
            response = self._call_llm_safe(prompt)
            raw = getattr(response, "text", "")
            data = self._safe_json_load(raw)
            if not data: return [self._empty_response(label)]
            
            if isinstance(data, dict): data = [data]
                
            results = []
            for item in data:
                # Limpieza final de seguridad para fechas y montos
                results.append({
                    "ocr_file": label,
                    "utility_vendor": str(item.get("utility_vendor", "UNKNOWN")).upper(),
                    "service_address": item.get("service_address"),
                    "account_number": item.get("account_number"),
                    "current_cycle_charges": self._clean_amount(item.get("total_amount_due")), 
                    "service_start": self._ensure_date_logic(item.get("service_start"), item.get("service_end"), "start"),
                    "service_end": self._ensure_date_logic(item.get("service_start"), item.get("service_end"), "end"),
                    "unit_type": item.get("unit_type", "UNIT")
                })
            return results
        except Exception as e:
            logging.error(f"LLM failure -> {label} | {e}")
            return [self._empty_response(label)]

    def _ensure_date_logic(self, start, end, target):
        """Lógica de respaldo si la IA devuelve nulos a pesar del prompt."""
        try:
            if not start and not end: return None
            # Si falta el inicio, estimar 30 días antes del fin
            if target == "start" and not start and end:
                return (pd.to_datetime(end) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            return start if target == "start" else end
        except:
            return start if target == "start" else end

    def _clean_amount(self, val):
        if val is None: return 0.0
        s = str(val).replace('$', '').replace(',', '').replace('S', '').strip()
        try: return float(s)
        except: return 0.0

    def _safe_json_load(self, raw):
        start = raw.find("[") if "[" in raw else raw.find("{")
        end = raw.rfind("]") if "[" in raw else raw.rfind("}")
        if start == -1 or end == -1: return None
        try: return json.loads(raw[start:end+1])
        except: return None

    def _empty_response(self, label):
        return {"ocr_file": label, "utility_vendor": "ERROR", "service_address": None, "current_cycle_charges": 0.0, "unit_type": "UNIT"}

    def get_dataframe(self, folder_path, file_list=None):
        if not file_list:
            file_list = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]
        
        results = []
        for file in file_list:
            logging.info(f"Processing -> {file}")
            chunks = self.process_document(os.path.join(folder_path, file))
            for i, chunk in enumerate(chunks):
                results.extend(self.analyze_text_with_llm(chunk, f"{file}_part_{i+1}"))
                
        df = pd.DataFrame(results)
        df.to_json(JSON_CACHE_FILE, orient="records", indent=2)
        return df