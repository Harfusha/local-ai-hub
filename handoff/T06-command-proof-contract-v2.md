# T06 command proof contract v2

Status: v7 producer handoff supersedes v6. T09 owns the typed receipt consumer; T20 owns root integration. No root source or tests were written.

## Project-bound receipts

A configured project command can produce proof only when the resolved alias equals the receipt criterion and its project configuration, configured command, caller arguments, resolved private environment, and actual executed command are bound. `project_execution_binding_sha256` covers those six hashes/identities in canonical sorted JSON. Raw environment values are never stored. This path uses the current T09 typed receipt fields: owner, mutation generation, evidence type, command id, evidence id, and repository revision.

## Generic receipts

Generic executed test/benchmark commands retain the established T09 `work_command_verification` receipt shape when the project has no matching `verification_rules` key for that criterion. These proofs contain the actual command text/hash and execution result, but no project alias or project execution binding. If a rule matches the criterion, generic proof is suppressed; a configured project command must supply the alias-bound proof. Generic source-review receipts remain ineligible.

The producer requires an actual recognized test/benchmark runner. A successful `python -c` that merely prints `pytest` cannot mint evidence. Help/version, collection/list-only, dry-run, shell chaining/redirection, and nonzero or zero-test outcomes do not produce receipts. `-v` is accepted as test verbosity; `-V` remains a version-only rejection.

## Focused producer/consumer evidence

`tests/test_t06_project_validation_receipts.py` uses current root package sources plus v7 in a temporary overlay. It covers configured project pytest and private-environment binding, the T09 completion consumer accepting that receipt, `pytest --help`, verbose pytest `-v`, zero-test unittest discovery (exit 5, no receipt), a generic real pytest receipt without project proof fields, the same consumer completing from the generic test plus configured lint receipts, fake successful `python -c` rejection, `echo lint` rejection, and rejection of generic test evidence when the matching criterion has an alias rule. Both project and generic receipts assert typed owner, mutation generation, evidence type, and revision fields.

The exact v7 patch passed the two integration tests (`2 passed`), `git apply --check`, and `python -m pyflakes` on the patched `commands.py` in the same temporary overlay. Full `pyflakes src` still reports existing issues in other modules (including `mcp_server.py`, `ollama.py`, `pipeline.py`, and `response_protocol.py`); T06 made no broad lint suppressions or unrelated fixes. v6 failed the new generic-receipt assertion and is on hold; it remains unchanged.

## v7 patch identity

- Base root `commands.py`: `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E`
- Patch: `T06-T09-validation-receipts-v7-root-namespace-current.patch`
- Patch SHA-256: `A4F87E3588D40ED7008261D9DEC9D07194B993623D5D069351ACF8F809B23EA5`
- Result `commands.py`: `C16F16D75E147BE61EC0F9F4998A9DFACBDD449A280F81D5580F0D8C7C0E1F7B`

The patch also removes a redundant function-local `import uuid`; the module-level import remains used. No broad lint suppression was added. Hub command routing was unavailable, so the bounded pytest and pyflakes fallback ran only against the temporary overlay.
