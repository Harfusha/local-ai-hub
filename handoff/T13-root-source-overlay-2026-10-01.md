# T13 root-source overlay receipt — 2026-10-01

## Pin and isolation

- Current root: C:\Users\Adam\.local-ai-hub
- Root HEAD before and after overlay: 98a9a1a7611af574caf20a88620c4aa3eb2e918a
- Current root snapshot: handoff/root-source-current-selectors-20261001/root-pin.json, SHA-256 8b720ef79106b5e839542b78b3fad3b147a5fbef251ba3a7e37753d36959da05.
- Pin covers 142 source/tool/test files. Post-run check found no missing files and no root-file changes since copy.
- Root file pins: operational_mode.py b72023ed7bd029ea747794a02b5c8f6783e6dc592b4bf67542bdee63f5d1f5a1; mcp_server.py 5ff372af25d78edbb09b7f6d3ab6ecf5f8c9c593247f38a7b01c2cff8e7929ce; http_server.py 520a77b5f2b8e0b4c4c9fc68a8b7e7718dd3a170c37e197af1623f4c0853c38d; preprocess.py 86715359388ca1598dde14c01ffcb4a23590263f99e13554d48502b50d4e961f; client.py 5518706e0e81623e3ff0184274bd17f18c9bf7f43d9bc4dd37fd754586b0d056; commands.py a17c02e1a5c4ced5372d75090758a647898bac2723d6ad3df5346344224406e7; tools/hubctl.py d587d80847152aa863a06d2850a60cbc2788409eb13ef94477dce1791b9758f6.
- Candidate test file pins: candidate-selector-pins.json, SHA-256 e44b20736ed9510ce0ff1542f49956ce4b511dcace9b76767e2290235a1ffa78.
- The first root copy caught concurrent dirty-source changes in commands.py and mcp_server.py. It was superseded. Final overlay recopied current root files; all pins matched after tests.

## Exact selector receipt against current root sources

- Command flags: python -B -m pytest -c pytest.ini -q -p no:cacheprovider --tb=short.
- Exact selectors: root-source-current-selectors-20261001/candidate-selectors.txt.
- Result: 38 failed, 10 passed in 8.22s. Full output and failed node IDs: root-source-current-selectors-20261001/current-root-candidate-selectors.log, SHA-256 af6e8151ef02facc2d7a7b265d9427bb4bc9af157cbe633d615fb221c73f0f8d.
- Root-owned mode-status regression selector: tests/test_mcp_task_mode_gate.py::test_maintenance_blocks_agent_action_but_preserves_job_status — 1 passed in 2.73s.
- Persisted pause/resume selector: tests/test_t13_mode_resume_matrix.py::test_persisted_pause_blocks_jobs_and_active_resume_dispatches_again — 1 passed in 0.23s.
- No test ran against the live root. All pytest runs used copied root source in isolated overlays. async_jobs.py was not edited.

## Root-specific findings

- Three candidate helper selectors use stale API assumptions: two expect OperationalModeWriteError, which current root helper does not define; one constructs OperationalModeSnapshot without required updated_at.
- Maintenance policy intentionally diverged: old candidate selectors require safe job status to be blocked. Current root allows safe job actions in maintenance; root-owned status selector above passes.
- Old hubctl selectors expect offline gaming to return success without unload receipts. Current root reports incomplete VRAM unload/accelerator release and exits 1.
- Multiple old route selectors receive HTTP 503 where candidate fixtures expect 200, 403, or 423. See complete list in log. These are root-current contract mismatches; no route patch was made from this receipt.
- Preprocessing pause tests exposed a concrete acceptance gap. Root CPU/GPU loops wait full poll_seconds while restricted; exact test observed 30.0s, expected bounded 0.1s. Root _run_project_step, _yield, _gpu_yield, and status()["paused"] also ignore persisted mode. Cooperative step can continue; dashboard status stays unpaused.

## Root-current preprocessing patch proposal

- Patch: T13-root-current-preprocess-pause-recheck-20261001.patch.
- SHA-256: d5b6823e6dc1f04984a7dab9674ff89eb6c71bfb9c12fa2c87bc4d9a10ce6213.
- Base root preprocess.py SHA-256: 86715359388ca1598dde14c01ffcb4a23590263f99e13554d48502b50d4e961f.
- Patch changes one root-owned file only: gate project-step/cooperative yield on persisted mode, expose mode in pause status/cache, recheck CPU/GPU restricted loops within 0.1s.
- git apply --check against current root passed. Patch was not applied.
- Same root-source overlay with patch: python -B -m pytest -c pytest.ini -q -p no:cacheprovider --tb=short tests/test_preprocess_operational_mode.py::test_mode_pause_blocks_next_preprocessing_step tests/test_preprocess_operational_mode.py::test_restricted_mode_pauses_background_worker_with_bounded_recheck tests/test_preprocess_operational_mode.py::test_cooperative_preprocess_yields_observe_restricted_mode — 7 passed in 2.71s.

Runtime unload remains unverified. These tests use fakes; no live Ollama, CUDA, or measured VRAM release was claimed.

