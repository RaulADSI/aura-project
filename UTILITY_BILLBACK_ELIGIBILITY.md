# AURA Utility Bill-Back Eligibility — primer corte

AURA termina en decisión, persistencia y exportación. No crea cargos en
AppFolio, cobra, aplica al ledger ni envía comunicaciones.

## Matriz implementada

Después de resolver la identidad, `UtilityBillBackEligibilityPolicy` determina:

| Condición | Resultado | Tratamiento |
| --- | --- | --- |
| Identidad COMMON_AREA configurada | COMMON_AREA | Decisión $0.00 con motivo |
| Vendor y routing explícitamente excluidos | NON_BILLABLE | Decisión $0.00 con motivo |
| GEORGIA_POWER e identidad UNIT | ELIGIBLE | Builder de ocupación/importe y AuditEngine |
| Otro servicio | REVIEW_REQUIRED | Rechazo visible; no decisión persistible |

La clasificación de áreas comunes tiene precedencia sobre exclusiones. Una
exclusión explícita tiene precedencia sobre Georgia Power. Este primer corte
trata las unidades resueltas del catálogo residencial como UNIT. No introduce
una clasificación nueva de inmuebles comerciales o múltiples servicios.

La policy no recibe importes, fechas de ocupación ni `bill_type`. Por eso FINAL
no modifica la elegibilidad. El proveedor se compara por el código estructurado
exacto, sin inferencias ni matching difuso.

Las identidades no resueltas conservan su motivo de rechazo previo. Para una
identidad resuelta con servicio no contemplado, el runtime comunica
`BILLBACK_ELIGIBILITY_REVIEW_REQUIRED`. Unknown nunca se convierte en elegible
ni en una decisión de cero.

## Configuración y versión

`config/utility_rules.json` pasa a `rule_version: "2"` por este cambio funcional.
`non_billable_services` comienza vacío: no se inventaron exclusiones de negocio.
Cada exclusión autorizada debe contener exactamente:

```json
{
  "vendor_code": "CODIGO_DEL_PROVEEDOR",
  "routing_key": "RUTA_EXACTA_DEL_SERVICIO",
  "reason": "Motivo de negocio de la exclusión"
}
```

La configuración rechaza campos vacíos, entradas duplicadas o estructuras
incorrectas. Los cambios futuros deben respetar el versionado/hash de reglas.
La versión 2 no reescribe las decisiones versión 1 ni corrige retrospectivamente
el conflicto de hash previamente observado. La siguiente persistencia explícita
creará historia bajo la nueva procedencia para las facturas procesadas.

## Decisiones de cero sin inventar facts

COMMON_AREA y NON_BILLABLE se materializan antes de consultar ocupación o exigir
`current_service_amount`. No llaman a AuditEngine. Producen un AuditResult con
importe calculado cero, tenant no consultado, días cero y motivo de la policy.

El request de ese resultado usa importe de cálculo cero; no sustituye los facts
originales, que permanecen en la identidad del run. P6 siempre toma el importe
y fechas de origen de ese snapshot. Si faltan, guarda NULL, no cero ni fechas
artificiales. Los campos ausentes solo se admiten en decisiones COMMON_AREA y
NON_BILLABLE; BILLABLE y VACANT mantienen sus requisitos anteriores.

Las facturas ELIGIBLE siguen usando exclusivamente current_service_amount,
ocupación y el AuditEngine sin modificaciones. No se suman balances anteriores,
pagos ni total_due. La policy canonical de AutoStack permanece intacta.

## Persistencia, migración y exportación

- P6 admite NON_BILLABLE y conserva su motivo e idempotencia.
- Al abrir el repositorio para escritura, se detecta el esquema anterior y se
  migra transaccionalmente la tabla para permitir facts opcionales en cero.
  Se copian las decisiones y se recrean los índices. La migración se probó con
  una base temporal anterior; no se ejecutó sobre las bases reales.
- P6/P7 cierran explícitamente sus conexiones SQLite.
- P7 exporta las nuevas clasificaciones, motivos y fechas ausentes como campos
  vacíos. Su resumen incluye NON_BILLABLE en los conteos y no en el total billable.
- `aura.persist` muestra los rechazos y devuelve código 1 cuando hay rechazos o
  anomalías, aunque haya guardado otras decisiones válidas. No equivale a una
  transacción única para todo el lote.

## Validación realizada

Suite completa: **204 ejecutados, 203 aprobados y 1 omitido**. La omisión es la
aceptación externa del corte histórico de 40 Georgia Power; no se rebajaron sus
assertions. El milestone prueba GP sin tipo, STANDARD y FINAL, mantiene $578.26
en el fixture de regresión, verifica desconocidos, exclusiones, ausencia de
importe/fechas/tenant para cero, idempotencia, migración y exportación.

Runtime real en lectura con el rent roll actualizado disponible: 51 snapshots,
41 decisiones (29 VACANT, 8 COMMON_AREA, 4 BILLABLE), 10 rechazos, total $751.20.
Cargos: D6 $294.41 y $35.96; H1 $283.85 y $136.98.

No se persistieron decisiones reales, modificaron estados de AutoStack ni
añadieron lectores de subcuentas. Gas South consolidado continúa fuera del
cálculo; su contrato 1:N y reglas de importes quedan para otro milestone.
