# P6 — Bill-back Decision Persistence

P6 persists the business decisions already calculated by the closed P5.6 runtime.
It does **not** recalculate bill-backs and does not add AppFolio, Vendor Ledger,
delivery, email, or reconciliation behavior.

## Boundary

```text
AutoStack SQLite
    ↓
P5.6 BillBackService
    ↓
BillBackRun
    ↓
BillBackDecisionFactory
    ↓
BillBackDecisionRepository
    ↓
AURA-owned SQLite (storage/aura.db)
```

## Provenance and idempotency

The deterministic provenance key is:

```text
(invoice_id, source_facts_version, rule_version)
```

`decision_version` is historical metadata and is intentionally **not** part of
that uniqueness constraint.

Behavior:

- same provenance + same deterministic payload → return existing decision / no duplicate;
- same provenance + different payload → `NonDeterministicDecisionError`;
- same `rule_version` + different `rules_hash` → `RuleVersionConflictError`;
- new facts/rules provenance → new historical decision and the previous active
  decision for that invoice becomes `SUPERSEDED` without being deleted.

`BILLABLE`, `VACANT`, and `COMMON_AREA` are persisted because `$0.00` is also a
business decision. Identity-unresolved records are not decisions and are not persisted.

## Storage

AURA writes its own database (default `storage/aura.db`). It never writes to
AutoStack's operational database.

Money is stored as canonical decimal text, never SQLite `REAL`.

## Rules provenance

`config/utility_rules.json` now contains:

```json
"rule_version": "1"
```

P6 also stores the SHA-256 hash of the exact rules file used by the run.
Changing the rules file without changing `rule_version` is treated as a versioning conflict.

## Run

P5.6 calculation only remains:

```bash
python -m aura.run
```

P6 calculate + persist:

```bash
python -m aura.persist \
  --autostack-db storage/autostack.db \
  --aura-db storage/aura.db \
  --rent-roll data/02_appfolio_reports/rent_roll.csv \
  --utility-rules config/utility_rules.json
```

Running the same command twice must create no duplicate rows. The second run
reports `created_decisions: 0` while preserving the same active bill-back total.
