import pandas as pd
import numpy as np
import json
import os

def convert_rent_roll_to_json(csv_filename, json_filename):
    base_path = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_path)
    csv_path = os.path.join(project_root, "data", "02_appfolio_reports", csv_filename)
    json_output = os.path.join(project_root, "data", "02_appfolio_reports", json_filename)

    if not os.path.exists(csv_path):
        print(f"[!] Error: No se encontró el archivo CSV en: {csv_path}")
        return

    # 1. LECTURA SEGURA (Soporte dual de encoding)
    try:
        df = pd.read_csv(csv_path, encoding="utf-8", dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="latin1", dtype=str)

    df = df.fillna("")
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Limpieza masiva de espacios en toda la tabla
    df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

    # Unificar nulos textuales a cadenas vacías
    vacia = ["nan", "none", ""]
    df.replace(to_replace=vacia, value="", inplace=True)

    has_prop_col = 'property' in df.columns

    # 2. LÓGICA DE JERARQUÍA VECTORIZADA (Identificar Propiedades)
    if has_prop_col:
        df['property_name'] = df['property'].replace("", "UNKNOWN PROPERTY")
    else:
        # Detectar cabeceras: Unidad existe, pero Inquilino y BD/BA están vacíos
        is_header = (df['unit'] != "") & (df['tenant'] == "") & (df.get('bd/ba', pd.Series(dtype=str)) == "")
        df['property_name'] = df['unit'].where(is_header, pd.NA)
        # Arrastramos el nombre de la propiedad hacia abajo
        df['property_name'] = df['property_name'].ffill().fillna("UNKNOWN PROPERTY")

    # Filtramos cabeceras y filas sin inquilino (Limpieza instantánea)
    df = df[df['tenant'] != ""]

    # Si el DataFrame quedó vacío, salimos
    if df.empty:
        print("[!] Advertencia: No se encontraron inquilinos en el CSV.")
        return

    # 3. REGLAS DE CASAS Y UNIDADES (IF/ELSE ultrarrápido con numpy.where)
    # Condición 1: Es casa si la unidad es mayor a 15 caracteres y tiene un espacio
    is_house = (df['unit'].str.len() > 15) & (df['unit'].str.contains(" "))
    # Condición 2: El nombre de la propiedad es exactamente el mismo que la unidad
    is_same_as_prop = df['property_name'] == df['unit']
    
    needs_unit_override = is_house | is_same_as_prop

    # Asignamos la propiedad y unidad final simultáneamente en todas las filas
    df['final_prop'] = np.where(needs_unit_override, df['unit'], df['property_name'])
    df['final_unit'] = np.where(needs_unit_override, "UNIT", df['unit'])

    # 4. CONSTRUCCIÓN DEL JSON MÚLTIPLE (Ultra Rápido)
    # Convertimos a una lista de diccionarios (Iterar dicts nativos es miles de veces más rápido que iterar df.iterrows)
    records = df.to_dict(orient="records")
    
    rent_roll_structured = {}
    
    for row in records:
        prop = row['final_prop']
        unit = row['final_unit']
        
        if prop not in rent_roll_structured:
            rent_roll_structured[prop] = {"units": {}}
            
        rent_roll_structured[prop]["units"][unit] = {
            "tenant": row.get('tenant', ''),
            "status": row.get('status', ''),
            "move_in": row.get('move-in', ''),
            "lease_to": row.get('lease to', '')
        }

    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump(rent_roll_structured, f, indent=4, ensure_ascii=False)
        
    print(f"[✔] ÉXITO: {len(rent_roll_structured)} propiedades y {sum(len(p['units']) for p in rent_roll_structured.values())} inquilinos guardados.")

if __name__ == "__main__":
    convert_rent_roll_to_json('appfolio_rent_roll.csv', 'rent_roll.json')