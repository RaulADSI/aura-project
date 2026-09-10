# P7 — Delivery

P7 is a read-only consumer of decisions already persisted by P6 in `aura.db`.
It does not calculate bill-backs, execute `AuditEngine`, resolve identity, read
`autostack.db`, or mutate decision state.

## Runtime

```bash
python -m aura.deliver
```

Optional paths:

```bash
python -m aura.deliver --aura-db storage/aura.db --output-dir data/04_output
```

Outputs:

- `bill_back_decisions.csv` — complete auditable detail for every ACTIVE decision.
- `bill_back_summary.json` — operational summary and BILLABLE decision list.

## Architectural invariant

`P7 = read + present/export`. Decision calculation belongs to P5.6 and durable
persistence belongs to P6.
