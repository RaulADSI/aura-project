# P5.6 — Integration Runtime

Production entry point, from the repository root:

```powershell
python -m aura.run --autostack-db storage/autostack.db --rent-roll path/to/rent_roll.csv
```

Alternatively set `AUTOSTACK_DB_PATH`, `RENT_ROLL_PATH`, and
`UTILITY_RULES_PATH`, then run `python -m aura.run`. Defaults are
`storage/autostack.db`, `data/02_appfolio_reports/rent_roll.csv`, and
`config/utility_rules.json`. Paths are relative to the working directory.
Missing files fail startup. The CSV must include non-revenue units and the
columns Unit, Tenant, Status, Move-in, Move-out. Lease To is not a move-out date.
Hierarchical JSON remains supported explicitly for existing integrations.

`BillBackService` reads `InvoiceFactsPort`, resolves identity, builds requests,
and calls the unchanged `AuditEngine`. SQLite schema and canonical eligibility
remain in `AutoStackSqliteAdapter`. Current service charges are mapped to the
audit amount; absent charges are rejected without monetary fallback. Occupancy
comes from the rent roll. No OCR cache, invoice export, ledger, reconciliation,
or decision persistence participates.

Output is JSON on stdout, including snapshot provenance, counts, rejected inputs,
tenant, unit, status and amount for each decision. Exit codes: 0 complete, 1
rejections/anomalies, 2 startup or snapshot lookup error. Canonical execution
includes every vendor returned by the port; unresolved WM invoices remain
visible as rejections. It does not silently limit the database to Georgia Power.

Exact development execution requires the AutoStack **invoice UUID**, not the
utility account number, and an explicit facts version:

```powershell
python -m aura.run --invoice 54150b6d-9c0d-4dad-add7-b38274101dff --facts-version 1
```

This selects the reproccessed B4 snapshot only. It does not include it in the
canonical run or change operational eligibility.

## Verification and acceptance status — 2026-09-10

```powershell
python -X utf8 -m unittest discover -s test -q
$env:P56_REGRESSION_DB_PATH = $env:AUTOSTACK_DB_PATH
python -X utf8 -m unittest test.test_p56_runtime.TestRealP56Acceptance -v
```

The historical frozen regression fixture remains useful for validating the
original 40-invoice Georgia Power cut: 31 UNIT, 9 COMMON_AREA, 29 VACANT,
2 BILLABLE, and total bill-back of $578.26. Those counts are fixture-specific
and are not a production runtime invariant because the operational AutoStack
population is mutable.

Current runtime acceptance against the active AutoStack database produced
43 canonical snapshots: 38 Georgia Power and 5 WM. All 38 Georgia Power
identities resolved: 30 UNIT and 8 COMMON_AREA. Audit results were 28 VACANT,
8 COMMON_AREA, and 2 BILLABLE. The two tenant charges were:

| Invoice UUID | Account | Unit | Bill-back |
| --- | --- | --- | --- |
| 4f5f68bc-a316-4884-98cd-b5c2819f067d | 9385974335 | D6 | $294.41 |
| b7fc2eee-be22-4044-bd23-8aa42819c5a6 | 1006974233 | H1 | $283.85 |

Total is **$578.26**. The five WM snapshots remain visible as
`UNIT_UNRESOLVED` rejections and do not affect the validated Georgia Power
bill-back decisions.

**P5.6 acceptance is CLOSED.** The change from the original frozen 40-invoice
Georgia Power regression population to the current 38-invoice operational
population is explained by the mutable AutoStack dataset and must not be treated
as a runtime regression. P5.6 calculates decisions only; P6 persistence and P7
delivery are separate downstream milestones.
