# Code-index storage and cleanup

The configured `code_index.max_index_bytes` bounds the shared derived SQLite
index. The current default is 536,870,912 bytes (512 MiB). Check the active
configuration before changing it; usage signals and least-recently-used/oldest
file records guide eviction. Parse blobs are shared across roots and are not
deleted by stale-file or orphan-trigram cleanup.

## Inspect and clean derived data

Run cleanup only while the Hub is offline. The command refuses online or
unknown Hub state, requires a readable preprocessing root snapshot, skips
currently running roots and roots with a `.git` marker in their ancestry, and
touches only code-index trigram rows with no matching symbol row. It never
removes project files or worktrees.

```powershell
python tools/cleanup_code_index.py --dry-run
python tools/cleanup_code_index.py --apply --batches 32 --max-rows 100000
python tools/cleanup_code_index.py --apply --batches 32 --max-rows 100000 --compact
```

`--apply` commits at most 100,000 rows per transaction. Runs are repeatable;
`has_more=true` means another bounded run can continue. `--compact` performs a
verified offline SQLite compaction after cleanup. For stale file records, use
`CodeIndex.cleanup_stale_files(dry_run=True)` first; its apply path preserves
active Git roots and shared parse blobs. Inspect both dry-run reports before
mutation.

## Measured installation cleanup

On 2026-11-05, the installed code-index database measured 4,073,857,024 bytes
with 853,422 free pages. The table inventory showed zero `files`, `symbols`,
`refs`, `edges`, and `parse_blobs`, but 2,627,510 `symbol_trigrams`; a read-only
anti-join confirmed all trigram rows lacked an owning symbol. This stale derived
data, not live source content, caused the excess allocation.

After a verified VACUUM, dry-run classified 2,620,606 rows as eligible across
two inactive/non-Git roots and protected 6,904 rows from Git roots. The bounded
cleanup removed exactly those 2,620,606 orphan rows. SQLite integrity check
passed; other row counts were unchanged. Final VACUUM reduced physical size
from 573,362,176 to 1,814,528 bytes and released 571,547,648 bytes. The Hub
subsequently repopulated indexes for current roots; a later observation showed
490,483,712 bytes, below the configured 536,870,912-byte cap. P23's usage data
was not part of the cleanup and remains preserved.
