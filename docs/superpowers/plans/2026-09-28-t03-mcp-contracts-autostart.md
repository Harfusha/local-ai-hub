# T03 MCP Contracts and Auto-start Implementation Plan

> Historical note: The command-tool instructions in this plan are obsolete. Use the current MCP schema and the host-native command tool for bounded validation. Historical steps and results below are retained as evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the eight existing MCP tools expose and enforce action-specific input/output contracts, fix the T03 RecoveryJournal call compatibility, and prove MCP uses the existing bounded Hub auto-start path without leaving child processes behind.

**Architecture:** Keep HTTP as the only MCP-to-Hub transport and reuse `HubClient(auto_start=True)`, its readiness deadline, and its start lock. Keep action contracts in `operation_contracts.py`, validate before transport in `mcp_server.py`, and add only the missing identity/fingerprint support to T03's `RecoveryJournal`. Do not change `client.py`; if timeout cleanup is needed, stop at the T04 ownership boundary and record that acceptance gap.

**Tech Stack:** Python 3.11+, JSON Schema dictionaries, pytest, existing HubClient and RecoveryJournal.

---

## File map

- Modify `src/local_ai_hub/operation_contracts.py` for action-specific arguments, result shapes, and generated schema metadata.
- Modify only the T03-owned schema/dispatch hunks in `src/local_ai_hub/mcp_server.py` for action selector types, pre-dispatch validation, and compacted result validation.
- Modify `src/local_ai_hub/resilience.py` for the `RecoveryJournal.begin`/`wait_for` arguments already used by the HTTP registration route.
- Extend the T03-owned `tests/test_operation_contracts.py` and add `tests/test_recovery_journal_contract.py` and `tests/test_mcp_autostart_contract.py`.
- Modify `src/local_ai_hub/client.py` and `tests/test_client_transport.py` only for the user-approved startup timeout cleanup of the child created by the current `ensure_server` attempt. Do not modify `src/local_ai_hub/http_server.py`, `/api/context/pack`, or unrelated inherited dirty paths.

## Task 1: Lock action-specific contract behavior with tests

**Files:** `tests/test_operation_contracts.py`

- [ ] Add a parametrized test covering generated action enums for all eight public tools against `operation_actions(tool, enabled_features)`.
- [ ] Add focused schema validation cases for `local_ai_status.action`, `local_ai_repo.action`, `verify_receipt.receipt`, missing required fields, extra arguments, and invalid scalar types.
- [ ] Assert invalid calls are rejected before the MCP HTTP client receives a request; use a request spy and assert its call count remains zero.
- [ ] Assert each action's result contract is present in metadata and that response compaction preserves the fields declared by that contract.
- [ ] Run `python -m pytest tests/test_operation_contracts.py -q` through `local_ai_command`; expected initial result is failure only in the newly added cases.

## Task 2: Implement contract generation and dispatch validation

**Files:** `src/local_ai_hub/operation_contracts.py`, `src/local_ai_hub/mcp_server.py`, `tests/test_operation_contracts.py`

- [ ] Add explicit per-action input and output JSON Schema objects to `OPERATION_CONTRACTS`; keep action order and existing feature gates as the source for published enums.
- [ ] Derive MCP selector types from the same feature-aware action list so `local_ai_status` and the other seven tools cannot drift from published schemas.
- [ ] In MCP dispatch, call `validate_operation_call` and `validate_operation_arguments` before issuing HTTP requests; translate validation failures to the existing invalid-argument MCP response shape.
- [ ] Validate/project successful operation results with the authored output contract before token compaction; leave error/uncertainty metadata intact.
- [ ] Run `python -m pytest tests/test_operation_contracts.py -q` through `local_ai_command`; expected result is PASS for the focused contract suite.

## Task 3: Match RecoveryJournal to the registration route

**Files:** `tests/test_recovery_journal_contract.py`, `src/local_ai_hub/resilience.py`

- [ ] Add tests that call `begin` and `wait_for` with tenant, identity, operation, request ID, and fingerprint data matching the current HTTP route call shape.
- [ ] Assert an identical retry returns the recorded/running result without claiming a second execution, while a changed identity or fingerprint returns conflict and does not run the operation.
- [ ] Run `python -m pytest tests/test_recovery_journal_contract.py -q` through `local_ai_command`; expected initial result is failure with the current signature mismatch.
- [ ] Add only the missing keyword parameters and persistence/comparison behavior to `RecoveryJournal`; preserve existing response bounds, conflict semantics, and bounded wait behavior.
- [ ] Run the new RecoveryJournal tests plus the existing `tests/test_mutation_replay.py` focused replay cases through `local_ai_command`; expected result is PASS.

## Task 4: Prove MCP uses existing Hub-owned auto-start

**Files:** `tests/test_mcp_autostart_contract.py`, T03-owned `src/local_ai_hub/mcp_server.py` wiring only if a test shows it disables auto-start.

- [ ] Add a test that constructs the MCP client with the default Hub configuration and asserts its HubClient has `auto_start=True`.
- [ ] Add a daemon-off transport test using a temporary Hub config and controlled `Popen`/readiness fakes: the first connection fails, one bounded startup is attempted, concurrent requests share the start lock, and the request deadline caps startup wait.
- [ ] Ensure every fake child is explicitly waited or terminated in `finally`; assert timeout leaves no live child and that a pre-existing managed service is never terminated.
- [ ] Run `python -m pytest tests/test_mcp_autostart_contract.py -q` through `local_ai_command`; expected initial result documents whether current `ensure_server` already satisfies timeout cleanup.
- [ ] If the no-live-child assertion fails in existing `HubClient.ensure_server`, add the narrow approved cleanup: terminate the owned process tree and wait/reap the child, while preserving successful startup and existing/managed services.
- [ ] If tests confirm existing behavior, make no startup implementation change; cite the test receipt as proof that MCP reuses Hub-owned startup.

## Task 5: Focused integration and diff review

**Files:** only the files listed above.

- [ ] Run the focused command `python -m pytest tests/test_operation_contracts.py tests/test_recovery_journal_contract.py tests/test_mcp_autostart_contract.py -q` through `local_ai_command` after all edits.
- [ ] Run indexed impact/review on the changed T03 files and inspect the narrow diff; confirm no `/api/context/pack`, T04, T07, or unrelated inherited hunk changed.
- [ ] Record exact command receipts and hashes. Do not mark complete if the timeout cleanup acceptance still requires a T04-owned edit or runtime proof not covered by the tests.

## Self-review

- Every spec decision maps to a task: eight-tool parity/input/output contracts (Tasks 1-2), RecoveryJournal compatibility (Task 3), bounded HTTP auto-start and cleanup proof (Task 4), and focused acceptance/review (Task 5).
- The T04 file release is limited to timeout cleanup; request dispatch, pooling, retries, and the existing server ownership checks stay untouched.
- The last focused native fallback passed 39 tests after the Hub was unavailable. A later single Hub command attempt and indexed review both returned `outcome_unknown`; neither was retried. No real daemon launch was used as runtime proof.

## Evidence record

Assigned checkout: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`  
HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`

- Native focused fallback: `python -m pytest -q --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_recovery_journal_contract.py tests/test_client_transport.py::test_auto_start_timeout_terminates_and_reaps_only_its_child tests/test_client_transport.py::test_concurrent_auto_start_callers_share_one_child tests/test_client_transport.py::test_auto_start_leaves_preexisting_server_alone tests/test_client_transport.py::test_auto_start_timeout_keeps_child_that_already_owns_listener` — **39 passed in 4.17s**.
- After that run, added `test_status_output_contracts_match_brief_and_cache_projections` and `test_status_telemetry_contract_types_every_projected_summary_metric` in `tests/test_operation_contracts.py`; the authorized bounded native fallback passed both.
- Native focused client file: `python -m pytest -q --tb=short tests/test_client_transport.py` — **22 passed, 1 failed** at `test_coord_pubsub_poll_uses_after_seq_in_json_body`.
- The failing pubsub test creates `_client()` with `auto_start=False` and replaces `_pooled_open`; its path is not marked replay-safe, so this case does not enter `ensure_server`. The failure is recorded without attributing it to the startup cleanup change; it remains unresolved.
- Native compile: `python -m compileall -q src/local_ai_hub/client.py src/local_ai_hub/mcp_server.py src/local_ai_hub/operation_contracts.py src/local_ai_hub/resilience.py tests/test_client_transport.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py tests/test_operation_contracts.py tests/test_recovery_journal_contract.py` — exit 0.
- Native whitespace check: `git diff --check` — exit 0; Git reported existing LF-to-CRLF warnings for `mcp_server.py` and `resilience.py`.
- Hub adaptive context: request `req_c495b9ddde4d`, `outcome_unknown`.
- Hub focused test command: request `req_8888a0267e0c`, `outcome_unknown`.
- Hub status-output regression command (`tests/test_operation_contracts.py::test_status_output_contracts_match_brief_and_cache_projections`): request `req_38901f68572e`, `outcome_unknown`.
- Hub telemetry-output regression command (`tests/test_operation_contracts.py::test_status_telemetry_contract_types_every_projected_summary_metric`): request `req_e6ac6519e7c4`, `outcome_unknown`.
- Authorized native fallback for the two status-output regressions: `python -m pytest -q --tb=short tests/test_operation_contracts.py::test_status_output_contracts_match_brief_and_cache_projections tests/test_operation_contracts.py::test_status_telemetry_contract_types_every_projected_summary_metric` — **2 passed in 2.50s**. This ran once after explicit fallback authorization; the Hub request was not repeated.
- Scoped native fallback after the integration request: `python -m pytest -q --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py` — **34 passed in 3.83s**.
- Scoped candidate commit: `89f30ec89a877599b0432314bbdfff621a6f463f`, parent `2b33602adef0d030fea66cdcc04ca742c60b2e32`; contains only `src/local_ai_hub/operation_contracts.py`, `tests/test_operation_contracts.py`, `tests/test_mcp_contract_dispatch.py`, and `tests/test_mcp_autostart_contract.py`.
- MCP zero-context isolation initially shifted hunks and was fully unstaged. Interactive hunk selection then committed only T03 operation-contract wiring in `mcp_server.py`: commit `a07c41fba00e35d13a8e9d8de26720b4b6f0b45b`, parent `89f30ec89a877599b0432314bbdfff621a6f463f`, changed path `src/local_ai_hub/mcp_server.py`.
- Post-wiring native fallback: `python -m pytest -q --tb=short tests/test_operation_contracts.py tests/test_mcp_contract_dispatch.py tests/test_mcp_autostart_contract.py` — **34 passed in 5.28s**.
- Remaining `mcp_server.py` working-tree hunk starts are `+424, +433, +447, +449, +495, +642, +1066, +1121, +1787`; these were left uncommitted as inherited/unowned changes.
- Hub indexed diff review: request `req_df29307ea521`, `outcome_unknown`.

SHA-256:

| Path | SHA-256 |
| --- | --- |
| `src/local_ai_hub/client.py` | `E43BA99F5846C4A6EE9A4B92BE15666D38F20AB12D0489B22208CB6792A19962` |
| `src/local_ai_hub/mcp_server.py` | `AC7CCA9DFFF469E30D8D1EE9ECD050D40074C319151C327AB73CF0DC05C8111F` |
| `src/local_ai_hub/operation_contracts.py` | `D2120B614852DE7AB7006F65B8AE30D5B6EEE474EBCAD69CB2605D37EC119329` |
| `src/local_ai_hub/resilience.py` | `03EEF6A19E4C2868CDA077C5B5790C424D0DF95BAD460263EBCCBD0131DBD603` |
| `tests/test_client_transport.py` | `B998CA131CF279DAF195411BAD6E3B7174EC117901473A375B33BFE966D45C89` |
| `tests/test_operation_contracts.py` | `6C388CED440D8EDA35DEE2C39762A1289412892C447EBF91BA08D3C0E8BC2BF5` |
| `tests/test_mcp_contract_dispatch.py` | `1BBA650F154E835F961A7FA72494C0DB3C6A806D72F7DD8465F3E86D41606B81` |
| `tests/test_mcp_autostart_contract.py` | `F42DD25E4D2F4EC0E035E4B262F4220C915D794BE5195C2109889F6AB57E96DD` |
| `tests/test_recovery_journal_contract.py` | `9D3AC2CF8701A4E2BBE9F854D69EDFADDDEE31F57E252AB9C82202BD35D6CD44` |

Acceptance remains open pending a Hub-backed receipt/review and runtime evidence for real daemon startup; route-owned and unrelated inherited changes remain outside this T03 validation record.
