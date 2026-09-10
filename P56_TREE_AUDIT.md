# Auditoría del working tree — P5.6

Fecha: 2026-09-09. Rama inspeccionada: `feature/aura-production-reconciliation`.
Índice vacío. No se hizo staging, commit, descarte ni modificación del código
durante esta auditoría. Se compararon los cinco archivos tracked modificados
contra HEAD, los imports del runtime y las responsabilidades de las pruebas.

## Conclusión

P5.6 se puede separar como una selección de archivos nuevos sobre HEAD.
No necesita ninguno de los cinco diffs de archivos tracked actuales.
El working tree contiene cuatro grupos de código: fundamentos P5 compartidos,
runtime P5.6, integración histórica de aliases y reconciliación. El rent roll
es una dependencia de ocupación del runtime; no debe clasificarse por sí mismo
como reconciliación.

## Selección concreta para P5/P5.6

| Grupo | Archivos nuevos que incluir |
| --- | --- |
| Contrato y port P5 | `src/contracts/__init__.py`, `src/contracts/structured_utility_invoice.py`, `src/ports/__init__.py`, `src/ports/invoice_facts.py` |
| Infrastructure P5 | `src/adapters/autostack_sqlite_adapter.py` |
| Identidad P5/P5.5, requerida por P5.6 | `src/adapters/unit_resolver.py`, `src/integration_autostack.py` |
| Adaptadores P5.6 | `src/adapters/rent_roll_csv_adapter.py`, `src/adapters/structured_audit_request_builder.py` |
| Aplicación y runtime P5.6 | `src/application/__init__.py`, `src/application/billback_service.py`, `src/runtime/__init__.py`, `src/runtime/run_billbacks.py` |
| Comando público | `aura/__init__.py`, `aura/run.py` |
| Pruebas de fundamentos | `test/test_p5_contract.py`, `test/test_p5_invoice_facts_port.py`, `test/test_p5_autostack_sqlite_adapter.py`, `test/test_p5_aura_integration.py`, `test/test_unit_resolver.py` |
| Pruebas y documentación runtime | `test/test_p56_runtime.py`, `P56_RUNTIME.md` |

La tabla contiene 22 archivos. Este informe de auditoría es documentación
adicional opcional; no es una dependencia del runtime.

Dependencias ya versionadas que permanecen en HEAD: `PropertyResolver`,
`AppFolioAdapter` para entrada JSON explícita, utilidades de parsing y
normalización, modelos de auditoría, `AuditEngine`, `config/utility_rules.json`.
El runtime CSV sigue importando AppFolioAdapter y por ello pandas; no ejecuta su
carga de accounting. No necesita los modelos nuevos de reconciliación.

## Trabajo que conservar fuera de esa selección

| Grupo | Archivos / diffs | Evidencia |
| --- | --- | --- |
| Compatibilidad histórica de aliases | `src/adapters/unit_alias_registry.py`, `config/unit_aliases.json`, `test/test_unit_alias_registry.py` | Consumidos por el flujo histórico; el runtime P5.6 no carga el registro ni el JSON. |
| Compatibilidad histórica de aliases | Diffs completos de `src/adapters/historical_fixture_adapter.py`, `src/main.py`, `test/test_historical_fixture_adapter.py` | Añaden UnitResolver y fallback de alias al OCR histórico. No son reconciliación ni necesarios para el comando `aura.run`. |
| Reconciliación | Diff completo de `src/domain/models.py` | Añade exclusivamente VarianceReason, Severity, ReconciliationResult y ReconciliationSummary; los modelos AuditRequest/AuditResult de HEAD bastan para P5.6. |
| Reconciliación | Diff completo de `src/reporter.py` | Añade tipos, columnas, acciones recomendadas y `add_reconciliation_result`. P5.6 emite JSON y no importa este reporter. |
| Reconciliación | `src/reconciliation.py`, `test/test_reconciliation.py`, `test/test_reconciliation_reporter.py` | Comparación de decisiones con cargos AppFolio y reporte de variancias. |

UnitResolver es compartido: incluirlo en fundamentos P5 permite que la mejora
histórica de aliases lo use posteriormente. La presencia del estado
EXPLICIT_ALIAS y su prueba en UnitResolver no obliga a cargar UnitAliasRegistry.

## Pruebas: capas complementarias

No hay dos arquitecturas de integración que mantener en los tests P5/P5.6.
Todos prueban los mismos módulos productivos:

- Contrato: tipos, inmutabilidad, versión y separación semántica de importes.
- Port: conformidad estructural independiente de almacenamiento.
- SQLite: canonical policy, lookup exacto, facts ausentes y conversión.
- Identidad: rutas, precedencia, áreas comunes y unidades sin resolución.
- UnitResolver: normalización y ambigüedad.
- Runtime: composición completa, CSV, CLI, selección exacta y resultados.

`test_p56_runtime.py` importa `SCHEMA` desde el test del adaptador SQLite.
Esto es un acoplamiento de fixtures entre módulos de pruebas, no una segunda
arquitectura. Una extracción posterior a un módulo común de fixtures sería
razonable, pero no es necesaria para separar el commit.

## Artefactos y datos locales

- `test/test_p5_aura_integration.py.tmp`: archivo vacío de 0 bytes; excluir.
- `data/01_raw_invoices/`: PDFs de entrada; excluir de código P5.6.
- `data/03_output_log/`: cache OCR y logs; excluir.
- `data/04_output/`: diagnósticos CSV, XLSX, resumen y resultados JSON reales;
  evidencia generada, no fixtures portables de aceptación; excluir del commit.
- `data/02_appfolio_reports/`: datos operativos de entrada no versionados;
  no añadir todo el directorio para conseguir una suite verde.

## Verificación de aislamiento

Se extrajo HEAD mediante `git archive` a una carpeta temporal y se copiaron
únicamente los 22 archivos listados. Ninguno de los cinco archivos tracked
modificados ni los archivos de reconciliación/aliases se copiaron.

1. Tests P5/P5.6 y UnitResolver sin datos locales: **52 ejecutados,
   51 aprobados, 1 omitido** (aceptación externa).
2. Suite completa de HEAD + P5.6 sin datos locales: **153 ejecutados,
   5 fallos, 1 omitido**. Los cinco fallos provienen de pruebas antiguas de
   AppFolio y AuditRequestBuilder que leen datos locales no versionados.
3. Copiando exclusivamente `rent_roll.json` y `appfolio_bills.csv` existentes
   a esa carpeta temporal: **153 ejecutados, 152 aprobados, 1 omitido**.

Esto verifica que las modificaciones tracked y reconciliación no son requisitos
ocultos del runtime. También demuestra que un checkout limpio todavía no ofrece
una suite completa autosuficiente. Antes de exigir verde en CI, conviene convertir
esas pruebas antiguas en fixtures mínimos sintéticos propios, en un cambio
separado y sin incorporar los datos operativos reales al repositorio.

La prueba de aceptación real no se volvió a ejecutar en esta auditoría: sigue
vigente la evidencia anterior de 38 frente a 40 snapshots Georgia Power y total
$578.26. Separar código no resuelve los facts canonical ausentes ni cierra P5.6.

## Orden propuesto de commits (sin ejecutar)

1. Fundamentos P5/P5.5: contrato, port, SQLite, UnitResolver, identidad y sus tests.
2. P5.6: builder estructurado, CSV, servicio, runtime, comando, test runtime y doc.
3. Independiente: compatibilidad histórica de aliases y sus tres diffs tracked.
4. Independiente y fuera de P5.6: reconciliación, sus dos diffs tracked y tests.

También se pueden combinar 1 y 2 en un commit de integración con los 22 archivos
indicados. No hace falta staging parcial de los cinco archivos modificados para
preparar esa selección. Conservar el resto del trabajo sin descartarlo.
