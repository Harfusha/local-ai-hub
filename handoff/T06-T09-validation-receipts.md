# T06 to T09 validation receipt handoff

Patch: `handoff/T06-T09-validation-receipts.patch`

- Patch SHA-256: `58EC1AE45611BA89DE79D38B95DF37BF7B1A3AF41FD826AE919D551765895F42`
- `src/local_ai_hub/commands.py` preimage SHA-256: `9C6DA1447DBC3EA32CCD85E13D4A52136F07B557A2FCCCCA47A769656BC3C68C`
- Preimage is T06 working-tree source immediately before this receipt-scope edit; `git apply --check` passed against it.
- T06 base commit: `94337de7309b66c63ff427cce8cd3a49e6414d73`

The broker now emits T09 `work_command_verification` proof with actual command, SHA-256, `source_review` classification for configured lint, owner, repository revision, mutation generation, exit status, and result. Receipt construction passes typed T09 fields when available. Test and benchmark command classification remains delegated to T09's classifier.

The integration test configures `python -m pyflakes` as the project lint command, runs it through `CommandBroker`, reads the real persisted proof artifact, and completes task through HTTP. Negative HTTP cases cover substituted command, stale receipt, and wrong owner.

Validation in T06 worktree:

```text
python -m pytest -q --tb=short tests/test_t06_t09_validation_receipts.py tests/test_agent_os_enhancements.py::test_command_broker_auto_registers_verification_receipt
2 passed, 3 skipped
```

The three negative cases skip because T06 worktree still has legacy `VerificationReceipt` without T09 `owner` field. The positive configured-lint, persisted-proof, and HTTP completion case passes. Run negative cases after T09 typed receipt API is integrated. The substituted-command gate must compare proof command/hash with configured lint alias before treating it as lint evidence.

```text
python -m pyflakes tests/test_t06_t09_validation_receipts.py
passed
git diff --check
passed
```
