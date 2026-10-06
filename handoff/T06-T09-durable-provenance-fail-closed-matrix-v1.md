# T06 durable provenance fail-closed matrix

| Case | Broker record | T09 completion result |
|---|---|---|
| Actual broker test succeeds; artifact and typed receipt persist; record survives restart | Valid, matching bindings | Accept only after evidence and receipt comparisons pass |
| Caller submits fabricated receipt/artifact with self-consistent fields | Missing | Reject |
| Cache hit, coalesced result, `cache_*` ID | No new record | Reject as command verification |
| Broker command fails, times out, cancels, or has `outcome_unknown` | Missing | Reject |
| Record missing after restart, expired externally, truncated, malformed, or digest mismatch | Unavailable/invalid | Reject |
| Command ID, task, tenant, owner, criterion, evidence ID, receipt hash, command hash/classification, root/hash, revision, mutation generation, or project binding differs | Mismatch | Reject |
| Public `coord verify_receipt` submission without broker execution | Missing | Reject |
| Correct matching durable record and fetched evidence | Valid | Accept if all current T09 pass/freshness/revision rules also pass |

Receipt shape stays current T09 shape. Durable producer is implemented in T06 candidate patch; consumer integration is still outstanding and owned by T09. No root integration or live Docker proof claimed.
