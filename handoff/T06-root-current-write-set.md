# T06 root-current write-set handoff

Base root HEAD: 98a9a1a7611af574caf20a88620c4aa3eb2e918a.

Patch: handoff/T06-root-current-write-set.patch
SHA-256: E61B8537F53C861E4885EC9DF40E3B631BEBB41C5E372BEE43B820577A75D33A

## Hunks

1. src/local_ai_hub/commands.py, current line 4843. Change declared_paths fallback so an explicitly supplied rollback_paths remains the mutation write set when rollback_on_failure is false. The task-owned worktree check with require_git_identity=true before this hunk and the _environment_overrides guard after it remain unchanged.
2. tests/test_command_rollback.py, after the existing private-transaction write-set test. New case commits its temporary task worktree with _commit_task_worktree and stubs _transaction_docker_ready only. It keeps the real task registration and identity guard active, then confirms _execute is reached for rollback_paths without rollback_on_failure.

The root private transaction already returns its successful result; no return hunk is needed. The separate authoritative attempt-fence seam remains T16-owned and is not included here. Root run/private transaction/recovery still need the confirmed T16 broker fence contract before stale-attempt import/recovery acceptance can be claimed.

## Apply check

Command:
git -C 'C:\Users\Adam\.local-ai-hub' apply --check -- 'C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub\handoff\T06-root-current-write-set.patch'

Result: passed (exit 0) against the root HEAD above. Check made no root edits.

## Test command for a later assigned slot

python -m pytest -q tests/test_command_rollback.py::test_run_uses_rollback_paths_as_write_set_without_rollback

Not run. The test slot remains with T20.
