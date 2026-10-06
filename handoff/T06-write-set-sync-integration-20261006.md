# T06 write-set checkout reconciliation

Original dirty checkpoint: `f8deb793`; original ordinary untracked handoffs
committed at `1145d19d`. Branch: `codex/sync-t06-write-set-resume-20261006`.

The older rollback helper duplicates the current master's stronger helper,
which takes explicit command/attempt keys and rollback paths and reports
uncertain outcome with incident capture. Keep the current interface, private
transaction helpers, provenance, cache bypass, and uncertain-outcome guards.
Daemon admission remains unconditional for disallowed policy commands.
Reviewed source conflicts therefore resolve to the current master behavior;
the resulting production source is identical to the pinned master. Older
source remains recoverable in the original checkpoint, not silently erased.

Retain the original rollback OSError regression as a separate test alongside
master policy tests. No expectations were weakened.

Native check:
`python -B -m pytest -q -p no:cacheprovider tests/test_command_rollback.py
-k test_rollback_restore_oserror_marks_outcome_unknown_and_invalidates_caches
--tb=short`: **2 failed, 77 deselected in 2.60s**. Both cases reach the
`failure_kind` assertion with no such key. Earlier uncertain-outcome assertions
passed, but later cache invalidation assertions were not reached and remain
unverified. Completion requires explicit metadata and cache-safety acceptance;
this preservation merge is not functional completion.

No new product fixes, runtime deletion, stash/drop, or blanket file replacement.
