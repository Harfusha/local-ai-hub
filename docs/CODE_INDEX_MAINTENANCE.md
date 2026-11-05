# Code-index storage and compaction

`code_index.max_index_bytes` sets the SQLite code-index budget (default: 512 MiB). The Hub records usage and recency per indexed file, prunes cold file-derived rows when over budget, and removes parse-cache entries only when no indexed file references their exact content hash, analyzer version, and language. Source files and worktrees remain untouched. Partial coverage is reported and missing code can be indexed again when used.

Idle maintenance performs bounded cache pruning and incremental vacuum work. Incremental vacuum only truncates pages SQLite can currently move to the end of the file; it does not repack a heavily fragmented legacy database. For an oversized legacy index, use the offline compactor after stopping the Hub.

```powershell
python tools/compact_code_index.py --dry-run
python tools/hubctl.py stop
python tools/compact_code_index.py --apply --timeout-seconds 300
python tools/hubctl.py start
python tools/hubctl.py status
```

Dry-run is the default. It reports current SQLite pages, estimated reclaimable freelist bytes, the compacted-size estimate, and free disk space without writing to the database. Apply refuses while the configured Hub port is reachable or its state is unknown. If TCP times out on Windows, it checks the listener table and managed Hub/supervisor PIDs; other ambiguous probes remain unknown. Apply also requires adequate free space, runs SQLite `VACUUM` under a time limit, checkpoints the WAL, and verifies `integrity_check` plus every table's row count. SQLite interruption leaves its original database transaction recoverable; failed verification is reported as failure.

The compactor changes only the derived code-index database. Its use does not prove the configured logical size budget is met: inspect `within_budget` from the code-index size-maintenance result separately. Never delete the SQLite file, its WAL, source files, worktrees, or user data by hand.
