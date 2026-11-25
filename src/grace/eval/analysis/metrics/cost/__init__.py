"""Cost ledgers and amortisation (plan section 8; contracts.md, "Cost ledger"; task T030).

- `ledger`: the three ledgers per category, per-read charges and their reconciliation, and the
  quantities reported apart from the ledgers.
- `amortisation`: cumulative cost over reads, the measured full-history row, the cache ratio,
  payback over the cache ratio, cost per successful task.
- `plots`: figures and their CSV tables, written only into run directories.

Reads run-directory files only; imports nothing from `context/` or the other `eval/` groups.
"""
