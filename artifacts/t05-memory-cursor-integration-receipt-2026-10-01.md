# T05 memory cursor integration receipt — 2026-10-01

Owner: T05. Workspace: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`.

## Candidate change

`agent_memory.py` now uses `_memory_event_stream_id(scope, scope_id, key)` for both `record()` and `mark_stale_for_revision()`. Both event kinds therefore share scope-aware stream sequence and cursor. The record transaction calls T08 `ordered_event_publication()` before `BEGIN`, appends with `append_in_transaction()`, and publishes after commit. Append failure remains within caller transaction rollback.

Candidate source SHA-256 after whitespace-only review fix: `B8494452E5BE1C3D6AD2BCB7BC2E6F0DFC06A9EC707130676AF881E6A7AE9AA2`.
Candidate test SHA-256: `67A76CCD8700182C8169A6C317FC5BE44701A0A933CF17DB0A4B30EF34DFCEC5`.
T08 `agent_events.py` overlay SHA-256: `E79AEB66A1078B0FAFC6CA3319FA0FF58E389D2A78EE066F7651097DE78EF417`.

## Focused validation

Command: `python -m pytest -c <overlay>/pytest.ini -q --tb=short -p no:cacheprovider <test-file>::<selector>...`, `PYTHONPATH=<overlay>/src`. Overlay copied T05 candidate source/test and replaced `agent_events.py` plus `sqlite_support.py` with T08 candidate files. Temporary overlay: `$($overlay.FullName)`.

Temporary overlay: `C:\Users\Adam\AppData\Local\Temp\t05-t08-event-overlay-01b82f93f5f14fe5831e5261dbabe266`.

Selectors: `test_memory_record_updates_event_cursor_and_replay_keeps_sequence`, `test_memory_record_append_failure_rolls_back_record_event_and_cursor`, `test_mark_stale_appends_memory_event_and_advances_cursor`, `test_mark_stale_for_revision_preserves_metadata_and_emits_event`.
Result: **4 passed in 0.45s**. Candidate overlay only. The fourth selector was a related existing regression check. No root test was run and no root file changed.

## Acceptance boundary

T08 public event API/schema must reach root before cursor selectors can run there. This receipt does not prove root integration. T05 corrupt-row/redaction selectors and T08 create/resume memory-adoption selectors still lack fresh root receipts.

## Focused T05 store policy validation

Same candidate overlay, same current source/test hashes, T08 event API plus SQLite support overlay. Selectors: `test_find_skips_corrupt_rows_without_aborting_scoped_read`, `test_memory_write_redacts_private_fields_and_blocks_sensitive_records`, `test_memory_correction_lineage_and_delete_survive_reopen`.

Result: **3 passed in 0.56s**. Candidate overlay only; root unchanged. Overlay `sqlite_support.py` SHA-256: `7AC3F35553D57DF84E1C5A82AC2AE35095C8D07BD8EADA94B52F905B7449CA4B`.
