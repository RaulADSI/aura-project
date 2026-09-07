import os
import pandas as pd
from dotenv import load_dotenv
from extractor import DataExtractor
from auditor import AuditEngine
from reporter import AuditReporter
from invoice_ocr import UtilityOCR

# Cargar variables de entorno
load_dotenv()

# CONFIGURACIÓN DE RUTAS
SCANS_PATH = "data/01_raw_invoices"
DATA_PATH = "data/02_appfolio_reports/"
REPORT_PATH = "data/04_output/"
RULES_PATH = "config/utility_rules.json"
LOG_PATH = "data/03_output_log/"

os.makedirs(REPORT_PATH, exist_ok=True)

def run_aura_flow():
    print("\n" + "=" * 60)
    print("      AURA TRIPLE-MATCH & COMPLIANCE ENGINE")
    print("=" * 60 + "\n")

    # 1. INICIALIZAR OCR
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        ocr_engine = UtilityOCR(api_key=api_key)
    else:
        print("[!] Advertencia: GEMINI_API_KEY no encontrada en .env. Usando OCR básico.")
        ocr_engine = UtilityOCR()

    # 2. CARGAR MOTORES Y DATOS
    extractor = DataExtractor(DATA_PATH)
    engine = AuditEngine(rules_path=RULES_PATH)
    reporter = AuditReporter(output_path=REPORT_PATH)

    df_rent = extractor.load_rent_roll_json("rent_roll.json")
    df_bills = extractor.clean_appfolio_bills("appfolio_bills.csv")
    df_ocr = ocr_engine.get_dataframe(SCANS_PATH)

    if df_ocr.empty:
        print("[!] ERROR: No se encontraron datos extraídos de OCR.")
        return

    print(f"[*] Procesando {len(df_ocr)} facturas OCR contra Rent Roll y AppFolio...")
    
    processed_count = 0
    for _, invoice in df_ocr.iterrows():
        service_addr = str(invoice.get("service_address", ""))
        current_charge = invoice.get("current_cycle_charges", 0.0)
        ocr_unit_type = invoice.get("unit_type", "UNIT")
        account_number = str(invoice.get("account_number", ""))
        
        
        # --- Paso A: Normalizar Dirección OCR ---
        ocr_match_key = extractor.normalize_address(service_addr)

        # --- Paso B: Buscar pagos en AppFolio Bills ---
        appfolio_amount_paid = 0.0
        gl_account_used = None
        if not df_bills.empty:
            matched_bills = df_bills[df_bills['match_key'] == ocr_match_key]
            if not matched_bills.empty:
                appfolio_amount_paid = matched_bills['appfolio_amount'].sum()
                gl_account_used = matched_bills.iloc[0].get('gl account')

        # --- Paso C: BUSCAR INQUILINO PRIMERO ---
        tenant = engine.find_tenant_at_date(
            match_key=ocr_match_key,
            service_date=invoice.get("service_end"),
            df_rent_roll=df_rent,
            raw_ocr_address=service_addr
        )

        # Revisamos la base de datos global para saber si es una casa, sin importar si está vacía o si las fechas están mal.
        is_single_family = False
        matches_prop = df_rent[df_rent['match_key'] == ocr_match_key]
        if not matches_prop.empty:
            
            if str(matches_prop.iloc[0]['unit_name']).upper() == "UNIT":
                is_single_family = True

        if tenant is not None:
            prop_display_name = tenant.get("property_name", "UNKNOWN PROPERTY")
        else:
            # Si no hay inquilino por fechas, +-++rescatamos el nombre de la propiedad
            if not matches_prop.empty:
                prop_display_name = matches_prop.iloc[0]['property_name']
            else:
                # Limpieza estética para el Excel: Rescatamos la dirección base del OCR
                base_addr = str(service_addr)
                separators = [" apt ", " unit ", " #", " ste ", " suite "]
                
                for sep in separators:
                    if sep in base_addr.lower():
                        idx = base_addr.lower().find(sep)
                        base_addr = base_addr[:idx]
                        
                prop_display_name = f"VACANT / UNMAPPED: {base_addr.strip().upper()}"

        # --- Paso D: Aplicar Reglas de Compliance (Áreas Comunes y GL) ---
        is_common_area = False
        
        # ESCUDO SINGLE FAMILY: Si es una casa, NUNCA es área común.
        if not is_single_family:
            if engine.is_common_area_exception(service_addr):
                is_common_area = True
            elif ocr_unit_type == "COMMON_AREA" and tenant is None:
                is_common_area = True

        if is_common_area:
            reporter.add_record(
                invoice_id=account_number,
                property_name="COMMON AREA / OWNER EXPENSE",
                unit=service_addr,
                status="COMMON_AREA",
                expected=0.0,
                actual=appfolio_amount_paid,
                diff=round((current_charge or 0) - appfolio_amount_paid, 2),
                notes="Compliance: Factura de área común confirmada."
            )
            continue

        # Reglas de Cuentas GL
        charge_classification = engine.classify_charge(gl_account_used, description="")
        if charge_classification == "ILLEGAL":
            reporter.add_record(
                invoice_id=account_number,
                property_name="UNKNOWN (ILLEGAL GL)",
                unit=service_addr,
                status="ILLEGAL_CHARGE_ATTEMPT",
                expected=0.0,
                actual=appfolio_amount_paid,
                diff=round((current_charge or 0) - appfolio_amount_paid, 2),
                notes=f"Compliance: Cuenta GL ({gl_account_used}) no permitida."
            )
            continue
            
        if charge_classification == "OWNER_EXPENSE":
            reporter.add_record(
                invoice_id=account_number,
                property_name="OWNER EXPENSE",
                unit=service_addr,
                status="OWNER_EXPENSE",
                expected=0.0,
                actual=appfolio_amount_paid,
                diff=round((current_charge or 0) - appfolio_amount_paid, 2),
                notes=f"Compliance: Cuenta GL ({gl_account_used}) del propietario."
            )
            continue

        # --- Paso E: Calcular y Generar Bill-Back ---
        if tenant is not None and current_charge is not None:
            occupied_days = engine.calculate_occupied_days(
                invoice.get("service_start"),
                invoice.get("service_end"),
                tenant.get("move_in_date"),
                tenant.get("move_out_date")
            )

            try:
                s_start = pd.to_datetime(invoice.get("service_start"))
                s_end = pd.to_datetime(invoice.get("service_end"))
                real_service_days = (s_end - s_start).days + 1
            except Exception:
                real_service_days = 30 

            bill_back_amount = engine.calculate_bill_back(
                appfolio_amount=appfolio_amount_paid,
                service_days=real_service_days if real_service_days > 0 else 30,
                occupied_days=occupied_days,
                ocr_current_charge=current_charge
            )

            variance = round(current_charge - appfolio_amount_paid, 2)
            status_note = f"Tenant: {tenant.get('tenant_name', 'Unknown')} | Days: {occupied_days}"
            
            # Dejamos un rastro en las notas si la IA se equivocó
            if ocr_unit_type == "COMMON_AREA":
                status_note += " (IA corregida: Single Family)"

            reporter.add_record(
                invoice_id=account_number,
                property_name=prop_display_name,
                unit=service_addr,
                status="BILL_BACK_GENERATED",
                expected=bill_back_amount,
                actual=appfolio_amount_paid,
                diff=variance,
                notes=status_note
            )
            processed_count += 1
            
        else:
            reporter.add_record(
                invoice_id=account_number,
                property_name=prop_display_name,
                unit=service_addr,
                status="VACANT_OR_NO_MATCH",
                expected=0.0,
                actual=appfolio_amount_paid,
                diff=round((current_charge or 0) - appfolio_amount_paid, 2),
                notes="Unidad potencialmente cobrable, pero no se encontró inquilino en las fechas de servicio."
            )

    report_file = reporter.save_report("Final_Triple_Match_Audit.xlsx")
    email_file = reporter.generate_email_summary("Email_Summary.txt")
    
    print(f"\n[✔] ÉXITO: {processed_count} bill-backs generados correctamente.")
    print(f"[*] Reporte de Excel disponible en: {report_file}")
    if email_file:
        print(f"[*] Resumen para correo electrónico disponible en: {email_file}")

if __name__ == "__main__":
    run_aura_flow()