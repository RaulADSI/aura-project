import json
import os
from src.adapters.audit_request_builder import AuditRequestBuilder
from src.auditor import AuditEngine
from src.reporter import AuditReporter

# CONFIGURACIÓN DE RUTAS
DATA_PATH = "data/02_appfolio_reports/"
REPORT_PATH = "data/04_output/"
RULES_PATH = "config/utility_rules.json"
CACHE_DATA_PATH = "data/03_output_log/ocr_extraction_data.json"

os.makedirs(REPORT_PATH, exist_ok=True)


def run_aura_flow(raw_autostack_payload=None):
    print("\n" + "=" * 60)
    print("      AURA TRIPLE-MATCH & COMPLIANCE ENGINE")
    print("=" * 60 + "\n")

    # 1. Cargar payload estructurado (simulado de AutoStack o cache de transición)
    if raw_autostack_payload is None:
        if os.path.exists(CACHE_DATA_PATH):
            with open(CACHE_DATA_PATH, "r", encoding="utf-8") as f:
                raw_autostack_payload = json.load(f)
        else:
            print("[!] ERROR: No se encontraron datos de entrada de AutoStack.")
            return

    # Normalización de nombres de campos de entrada hacia el contrato AutoStack
    formatted_payload = []
    for idx, item in enumerate(raw_autostack_payload):
        amt_val = item.get("current_cycle_charges", "0.00")
        if isinstance(amt_val, (int, float)):
            amt_str = f"{amt_val:.2f}"
        else:
            amt_str = str(amt_val)

        formatted_payload.append({
            "invoice_id": str(item.get("account_number") or f"INV-{idx+1}"),
            "invoice_number": item.get("ocr_file"),
            "account_number": str(item.get("account_number", "")),
            "vendor_name": str(item.get("utility_vendor", "UNKNOWN VENDOR")),
            "property_name": str(item.get("service_address", "")),
            "unit_name": "",
            "service_start_date": item.get("service_start"),
            "service_end_date": item.get("service_end"),
            "amount": amt_str,
        })

    # 2. Inicializar adaptadores, motor y reportero
    builder = AuditRequestBuilder(DATA_PATH)
    engine = AuditEngine(RULES_PATH)
    reporter = AuditReporter(REPORT_PATH)

    # 3. Construir solicitudes e ingresar al motor
    requests = builder.build_requests(formatted_payload)
    print(f"[*] Procesando {len(requests)} solicitudes de auditoría...")

    processed_count = 0
    for req in requests:
        result = engine.audit(req)
        reporter.add_audit_result(result)
        if result.calculated_bill_back > 0:
            processed_count += 1

    # 4. Generar reportes finales
    report_file = reporter.save_report("Final_Triple_Match_Audit.xlsx")
    email_file = reporter.generate_email_summary("Email_Summary.txt")

    print(f"\n[✔] ÉXITO: {processed_count} bill-backs calculados correctamente.")
    print(f"[*] Reporte de Excel disponible en: {report_file}")
    if email_file:
        print(f"[*] Resumen para correo electrónico disponible en: {email_file}")


if __name__ == "__main__":
    run_aura_flow()
