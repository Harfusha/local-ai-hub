# T18 errno diagnostic integration reconciliation

Status: integrated in current root by the root owner. Do not apply the earlier test-only patch again.

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `src/local_ai_hub/telemetry.py` SHA-256: `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`.
- Root `tests/test_telemetry_error_errno_diagnostics_t18.py` exists and SHA-256 matches integrated owner receipt: `B6C59287C900E2E4C8B6023DBF6C049720D754CACEE2E3F14F322945D801620F`.
- Test covers base `OSError` with `ENOENT` and `EACCES`, SQLite safe messages, <=96-character bounds, and prompt/source/token/path sentinel exclusion.
- Root owner reports `1 passed in 0.72s` and scoped diff-check clean. T18 independently verified target existence, test hash, current root HEAD and telemetry hash; T18 did not rerun root test or write root.
- Earlier T18 overlay receipt: 11 passed in 6.16s. Candidate status/dashboard/telemetry selector: 65 passed in 22.74s; current-root pinned selector: 11 passed in 15.96s.
- Superseded patch remains at `handoff/T18-root-current-errno-diagnostic-test-only-20261001-v1.patch` with SHA-256 `9F43C740E38AB4D2062FE77432E28645546B2E00CE0DC490343193879ACC5E4F`; target now exists, so patch is stale and must not be applied.
- Full root repository suite not run by T18. T20 remains root release integrator.
