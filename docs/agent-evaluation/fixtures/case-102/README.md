# Case 102 disposable unknown-outcome adapter

Adapter stores one counter at `<sandbox-root>/state/case102-counter.json`. It
requires an absolute sandbox root outside every Git checkout and requires the
`state` directory to exist inside that root. It has no Hub, network, task-store,
or production-state access.

```powershell
python fault_adapter.py --root C:\path\to\disposable-sandbox mutate
python fault_adapter.py --root C:\path\to\disposable-sandbox read
```

`mutate` increments the counter once and deliberately returns
`success=false`, `outcome_unknown=true`, `terminal=true`, `retryable=false`.
Call `read` independently to inspect the counter. A second `mutate` is a retry
and increments it again. The read action never changes the counter. Remove the
disposable sandbox only after capturing evidence.
