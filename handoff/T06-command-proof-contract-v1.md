# T06 command proof contract v1

Scope: T06 receipt producer only. T09 owns the typed receipt consumer/verifier; this handoff does not change T09 code. The selected contract is the current T09 `work_command_verification` proof and receipt shape.

## Producer admission

- Receipts require a successful executed project command with trusted `_ResolvedProjectCommand` context. Generic `CommandBroker.run()` cannot supply project provenance; caller-provided alias/config strings are not accepted.
- `criterion` must equal the resolved project command alias, the project configuration digest must be present, and the criterion's T09 evidence type must match the classifier (`test`, `benchmark`, or `source_review`).
- Test/benchmark commands that only show help/version, collect/list tests, dry-run, or contain shell chaining/redirection do not earn receipts. Source-review receipts additionally require an allowlisted validator executable in the resolved command.
- Exit code must be the integer `0`; unsuccessful executions do not earn receipts. Thus `unittest discover` reporting `Ran 0 tests` (exit 5) is rejected. `pytest --help` returns successfully but is also rejected by its non-executing option.

## Persisted proof fields

The `work_command_verification` artifact binds task, owner, criterion, command id, classification, resolved command text/hash, project alias/config digest, configured command hash, caller-argument hash, and a hash of the resolved private environment. `project_execution_binding_sha256` hashes the canonical JSON object containing alias, config digest, configured-command hash, caller-argument hash, actual-command hash, and private-environment hash. Raw environment values are never persisted.

T09 must independently validate the proof against the configured command, allowed caller arguments, environment binding, task/owner/revision/generation, and its typed receipt contract. Producer presence alone is not verifier acceptance.

## Focused evidence and limits

- `tests/test_t06_project_validation_receipts.py` covers a structured configured pytest success, private environment hashing, caller argument binding, `pytest --help`, generic execution, a zero-test unittest discovery, rejected `echo lint`, and configured pyflakes source review.
- The zero-test case is expected to return `success=False`, exit code 5, include `Ran 0 tests`, and have no verification receipt.
- T09 proof logic from v5 has been composed into `T06-T09-validation-receipts-v6-root-namespace-current.patch`, based on current root namespace-bridge postimage SHA-256 `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E`; patch SHA-256 `2BC2AAED85A83126906D0F347C25BFD059FFF816B413093D09E3242804D22982`; resulting `commands.py` SHA-256 `21E8F325B652ED338F30714EC0DD341B3A898A9D608814A62CAB86915BECC71C`.
- The v6 composed receipt test passed in a temporary copy of current root package sources (`1 passed in 10.18s`); `git apply --check` passed against the recorded base. Receipt consumer acceptance remains T09-owned.
- Root project integration remains T20-owned. All composed validation uses a temporary overlay; no root source or tests are written by T06.
