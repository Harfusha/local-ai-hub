# T06 command proof contract v3

Status: v8 supersedes v7 for review; v6 and v7 remain unchanged and held. T09 owns the typed receipt consumer; T20 owns root integration. No root files were modified or tested directly.

## Command admission corrections

- Preserve raw argv tokens for case-sensitive option checks. `pytest -V` is version-only and must not mint a receipt; lowercase `pytest -v` remains valid verbose execution.
- Expand pytest `addopts` values passed through `-o` or `--override-ini` before checking for help/version, collection/list-only, or dry-run flags. `pytest -o addopts=--collect-only ...` executes collection successfully but is not a test run and must not mint a receipt.
- Project-bound versus generic receipt rules from v2 remain: generic actual test/benchmark receipts are allowed when no matching project verification rule requires the configured alias; matching rules suppress generic evidence. Project command proof retains alias/configuration/argv/environment binding. T09 still independently validates typed receipts and durable evidence.

## v8 identity and evidence

- Base root `commands.py` SHA-256: `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E`
- Patch: `T06-T09-validation-receipts-v8-root-namespace-current.patch`
- Patch SHA-256: `B8925B9A3542164AA4FCF29B073DD35048E86E39BDD49E561812367C37191F60`
- Result `commands.py` SHA-256: `4814FA5E1868D58961C674533D0F7A0021389A84487F206CC926CA2B1C21CF69`

The v8 builder applied v7 to a temporary copy of current root package sources, applied only the raw-token and pytest `addopts` guards, then ran `tests/test_t06_project_validation_receipts.py`: `2 passed`. `pyflakes` on the produced `commands.py` passed, as did `git apply --check` against the recorded base. The regressions each failed against v7: `pytest -V` minted a receipt, and `-o addopts=--collect-only` minted a receipt. Root integration remains T20-owned.
