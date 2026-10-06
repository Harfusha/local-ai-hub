# T09 root-current receipt/retrieval patch

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Patch: `handoff/t09-receipt-e2e-root-current.patch`.
- Patch SHA-256: `9F2DC77227A2A5DBA37A5936CB779B75D8F09CFCD840C26D75164951AF85E5B1`.
- Root preimages:
  - `src/local_ai_hub/agent_verification.py`: `FB477438FF110AB80FE6F2D486FFA5D87AAB1A855735FCD94592F8080EAF0017`.
  - `tests/test_agent_receipt_completion_t09.py`: `A6B7684359D2126F9366EBCE97CA9DDE918AE383F491428947A850C4BB6409D9`.
- Scope: `VerificationStore.completion` evaluates the latest receipt per criterion, then returns/audits only receipts matching task owner. Newer foreign receipt stays unsatisfied; it cannot leak or expose an older owner pass.
- New regressions: foreign tenant receipt is hidden; newer foreign receipt supersedes an older owner pass. Retrieval test also asserts exact task, owner, command ID, evidence ID and revision after verifier restart.
- Red: tenant privacy regression failed before fix because completion returned the `tenant-b` receipt to `tenant-a` task. Green: focused module, 9 passed in 3.48 s.
- Run receipt: `handoff/t09-receipt-e2e-run-20261003-r2.json`; includes exact command, nine selectors, source pins and result.
- `git apply --check --verbose --whitespace=error` against root: PASS. Root untouched. T08 test files untouched. No broad suite.
