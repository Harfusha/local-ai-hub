# Code-index storage audit — 2026-11-06

Read-only measurements from the installed Hub's `state/code-index.sqlite3`. Cleanup ran with `--dry-run`; no index rows or user data were changed.

## Whole database

| Measure | 2026-11-06 | Prior read-only measurement, 2026-11-05 |
| --- | ---: | ---: |
| Physical database + WAL/SHM | 470,814,720 B | 317,145,960 B |
| Allocated SQLite pages | 470,781,952 B | not captured |
| SQLite freelist | 0 B | not captured |
| Difference between measurements | +153,668,760 B (+48.45%) | — |
| Configured maximum | 536,870,912 B (512 MiB default) | same source default |
| Remaining to maximum | 66,056,192 B | — |

The active `config.toml` does not override `code_index.max_index_bytes`; the Hub default is 536,870,912 bytes. Current physical storage is 87.70% of that limit.

## Current derived rows

| Table | Rows | Raw text payload |
| --- | ---: | ---: |
| `symbol_trigrams` | 1,384,070 | 111,034,917 B |
| `parse_blobs` | 733 | 27,403,283 B |
| `edges` | 149,924 | 21,279,092 B |
| `refs` | 141,206 | 11,577,077 B |
| `symbols` | 12,236 | 2,799,510 B |
| `files` | 593 | — |

The 593 indexed files belong to two current roots: 337 in the Hub repository and 256 in the active `shpotify-monitor` worktree. Trigram postings, serialized parse blobs, and graph edges account for 174,093,879 bytes of measured raw text before SQLite row, page, and B-tree index overhead. The SQLite build lacks the `dbstat` virtual table, so exact allocated bytes per table are unavailable.

This explains the current database composition: high-volume trigram postings plus parse and graph data. It does **not** prove which table accounts for the full 153,668,760-byte increase since the prior measurement; no prior per-table snapshot exists.

## Cleanup dry-run

The bounded dry-run scanned all 3 orphan-trigram roots and both stale-file roots in its scope:

- 6,904 orphan trigram rows observed; 0 eligible for removal.
- 0 stale files, 0 stale source bytes, 0 rows pruned.
- 0 reusable SQLite pages before or after cleanup.
- Physical bytes released: 0.
- Active preprocessing/Git roots were skipped and preserved.
- Shared parse blobs were preserved.

No compaction was requested. There was no free-list space for SQLite to return, and the scan found no eligible stale rows. The safe outcome is to keep the index intact and let the configured size budget backpressure further indexing if protected active roots leave insufficient room.

## Follow-up live snapshot — 2026-11-06

A second read-only dry-run measured 515,552,232 B across the main database
(389,242,880 B), WAL (125,326,312 B), and SHM (983,040 B). SQLite reported
95,030 pages of 4,096 B and zero free pages. The default 536,870,912 B cap had
21,318,680 B (about 4.0%) of headroom. This is a later snapshot than the
470,814,720 B total above; the earlier database/WAL/SHM split was not recorded,
so the increase cannot be attributed to a specific file component.

The Python SQLite build still has no `dbstat` virtual table. The installed
`sqlite3_analyzer` measured page shares for tables and their indices: `symbol_trigrams`
56,600 pages (59.6%), `edges` 19,298 (20.3%), `refs` 11,219 (11.8%),
`parse_blobs` 5,411 (5.7%), and `symbols` 2,268 (2.4%). A read-only row count
found 1,346,187 trigram rows, 146,327 edges, 136,454 refs, 603 parse blobs,
11,530 symbols, 602 files, and 845 file-usage rows. This attributes most
allocated database pages to trigram postings and graph relationships; it does
not attribute the WAL's bytes to individual tables.

The matching dry-run found 6,904 orphan-trigram candidates, zero eligible
rows, zero stale files, zero reusable pages, and zero releasable physical
bytes. No cleanup or compaction ran. The database remains under its configured
cap, with little remaining headroom; bounded indexing must continue to defer
or evict only eligible cold records.
