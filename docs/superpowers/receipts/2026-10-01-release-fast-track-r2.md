# Release fast track r2 — observed evidence, not a release claim

Owner: orchestrátor. Root source integration and serialized validation: T20.
Root: `C:\Users\Adam\.local-ai-hub`; dirty master preserved. No new chats/worktrees.

## Newly accepted root slices

Evidence read directly from T20 command execution outputs, exit 0:

- `python -B -m pytest -q --tb=short tests/test_mutation_replay.py tests/test_t21_journal_observation_uncertainty.py`: **69 passed in 12.43s**. S7 existing-mutation observation uncertainty regression now included. Root HTTP SHA after fix: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`.
- T15 cache-only v2 patch SHA `D26D7F9075EC2E3CE94B23CEC66DAA75FB12AE036B9F51910758DE88DA246501` integrated by T20. `python -B -m pytest -q --tb=short tests/test_project_command_broker.py`: **15 passed in 4.09s**.
- `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py tests/test_project_config_worktrees.py tests/test_project_command_broker.py tests/test_project_config_service_integration.py tests/test_project_path_hints.py tests/test_command_streaming.py tests/test_new_capabilities_and_hardening.py::test_13_mock_recorder_and_replayer tests/test_command_network_safety.py::test_replay_mock_rejects_cassette_path_traversal tests/test_command_network_safety.py::test_replay_mock_rejects_oversized_cassette`: **115 passed in 11.76s**.

These are slice receipts, not full T07/T15 or whole-release acceptance.

Main subsequently took the idle T20 validation slot for one bounded native fallback batch under the human's explicit Hub-ignore instruction. Exact root module imports asserted; main T21 search policy test plus root `tests/test_project_config_service_integration.py` and `tests/test_repo_tools.py`: **22 passed in 7.78s**, exit 0. T10 r3 integrated source hashes match proposed postimages (`repo_tools.py` 8DA38EC…B6DA65, `services.py` A06AE015…4235). Root production not edited by main; slot returned to T20.

Real current-root packaged SDK smoke initially failed on raw Python tuple-vs-JSON-list equality; separate installed fresh-venv diagnostic proved successful JSON serialization. Main corrected only the new test to inspect wire semantics, added metadata-preservation/non-finite/unsupported-object negative controls, and reran the changed test: **2 passed in 13.131s**, exit 0, no skips. Actual root sdist/wheel/fresh-venv installed SDK verified. Receipt `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-vjtt5vpp\receipt.json`, SHA `6E38D874EADF56ED354EAFE182C02A97A28B954A8FE657B6086FAB6F81B4097E`; source snapshot map `42A4319D8CF6625E6B8F264BB494F6F239928D719192D3B1FD47FAF6CD78301C`. Full diagnosis/command/limits in T19 `handoff/T19-packaged-sdk-smoke-20261001-r2-root.md`. This predates remaining source integration, not final release approval.

## CPU slot released

T20 interrupted its own benchmark session 98922 with Ctrl+C. Partial artifacts preserved under `C:\Users\Adam\AppData\Local\Temp\t02-artifact-matrix-d4efa05318c54f1ca241f782c514e830`.
Observed `INCOMPLETE.txt`: INCOMPLETE, contaminated=true; root partial, candidate not started. No accepted timings or claimed speedup.

## Parallel ready queue and holds

- T09 exact five-artifact spec review: Dirac completed NOT SPEC-COMPLIANT; [review receipt](2026-10-01-t09-spec-review-r1.md). T20 briefly applied the old adapter during an in-progress turn, then exact reverse-check/apply removed only its own new hunk, preserving inherited dirty source. Actual root verification_rules SHA restored to `157129234E47605307D208BB586E2D8351E619271E79720BA7D0555569FA61B3`. Old bundle remains HOLD, not accepted. Trusted project/memory binding, every terminal completion path and resolved command proof must be fixed before release.
- T16 core v5 SHA `27242C3C4F9EA7113DC9E84C4179A6E937583175BF4ECEA64D605BC34A940459`, HTTP v3 SHA `954F126E34DC408F2AF8139E54033F88967EDC2DC072E94F627D70360CCC3AFE`: main targeted follow-up closes Bernoulli's legacy writer floor and non-directory-ancestor restore gaps; source guard reviewed and strict root checks pass. Owner genuine RED/GREEN **12 pass/1 Windows privilege skip in 5.09s**, no root tests yet. Narrow integration approved to T20; actual T06 broker namespace forwarding still needs joined root proof.
- T11 exact embedding-space production SHA `5631CC11281F207EB70B244AEF7468EF5867257FE8736E0F1C9FE9623C41B636`, tests SHA `4FBBE2D81DA5CC58C457A050370319747923016342714D5B440F3CE186DEE62E`: independent Hubble review. Candidate 3-test overlay is not root acceptance.
- T10 r2 was held for unsupported `rg --files-from` and missing zero-segment `**`. Revised immutable r3 SHA `2873B765178E686F0AF27F82ADC099A2F98B4C2FC273EC5BABD58928F4BBB842` independently reviewed by main: supported explicit approved-file argv batches (192 files/20k estimated characters), one total timeout, correct relative output resolution and safe glob matcher. Strict root apply-check exit 0. Owner actual overlay **5 passed in 1.41s**, real rg engine/two batches/second-batch hit plus policy negatives. Approved this narrow integration to T20; root acceptance pending. No context/pack route edit or whole-T10/T21 completion claimed.
- T12 r3 remains held for reviewed inventory correctness and prompt trace privacy issues; owner fixes new revision.
- T19 packaged SDK smoke completed: actual candidate sdist/wheel/fresh-venv installed SDK, resource bytes/version/schema, **1 passed in 10.022s**, no skips. Test SHA `FDAED8791E9021C47B9C56F92A11115F7020F03ED833BFE61DBA16CFCA77F58F`; existing `T19_PACKAGE_SOURCE_ROOT` selector can verify final integrated root without duplicate test or Git-HEAD-only export. T20 received exact invocation. Candidate evidence is not final root/release evidence; worker closed after scoped completion.

## Release gates still pending

T20 must validate the final integrated snapshot: full pytest, compileall, selftest, dashboard JavaScript, surface inventory drift/non-writing check, release check and fresh package smoke/hygiene. No version/tag/build/published release is claimed here. No data-integrity or privacy gate waived for speed.
