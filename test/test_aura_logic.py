import pandas as pd
from datetime import datetime
import sys
import os

# Agregamos la carpeta raíz del proyecto al PATH de Python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.auditor import AuditEngine # Ajusta 'src' si tu archivo está en otra carpeta
# O si auditor.py está directamente en la raíz, usa: from auditor import AuditEngine

def test_proration_logic():
    engine = AuditEngine(rules_path="config/utility_rules.json")
    
    # 1. Datos de prueba
    service_start = "2026-01-23"
    service_end = "2026-01-26"
    move_in = "2026-01-25" # El inquilino entra el día 21
    af_amount = 23.58
    
    # 2. Calcular días de servicio totales
    s_start_dt = datetime.strptime(service_start, "%Y-%m-%d")
    s_end_dt = datetime.strptime(service_end, "%Y-%m-%d")
    total_days = (s_end_dt - s_start_dt).days + 1 # Debería ser 30
    
    # 3. Calcular días ocupados usando tu función de solapamiento
    occupied_days = engine.calculate_occupied_days(
        service_start, service_end, move_in, move_out=None
    )
    
    # 4. Calcular el monto proporcional
    pro_rated_amount = engine.calculate_bill_back(
        af_amount, total_days, occupied_days
    )
    
    print(f"--- RESULTADO DEL TEST ---")
    print(f"Días Totales del Servicio: {total_days}")
    print(f"Días Ocupados por Inquilino: {occupied_days}")
    print(f"Monto Original: ${af_amount}")
    print(f"Monto Calculado (AURA): ${pro_rated_amount}")
    
    # Validación
    if pro_rated_amount == 40.0:
        print("\n✅ TEST PASADO: El prorrateo es exacto ($40.00).")
    else:
        print(f"\n❌ TEST FALLIDO: Se esperaba $40.00 pero obtuvimos ${pro_rated_amount}")

if __name__ == "__main__":
    test_proration_logic()