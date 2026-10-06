# T12 VRAM timeout receipt

Scope: `src/local_ai_hub/vram_balancer.py`, `tests/test_vram_balancer.py`, and the T12 patch packet. Other dirty worktree paths were inherited or owned elsewhere and were not changed or attributed here.

## Candidate worktree

- Root: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Source SHA-256 before/after: `1B82D39E51A16F1C2AA1E74E7324E13A56CE30C601788B3DEEBA82C7EBC930B2`
- Test SHA-256 before/after: `202E4C468A14E2A83E90FF4B4ABF587051C1B50249B518F97AD4A5DF05D9C17C`
- Test command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_vram_balancer.py::test_status_wait_timeout_returns_conservative_unavailable_without_second_sampler tests/test_vram_balancer.py::test_status_wait_timeout_returns_conservative_stale_cache
  ```

- Result: exit `0`; `2 passed in 0.22s`; wrapper duration `0.983s`; command broker duration `1.4087s`.
- Execution ID: `fc91601690094fc79d7610cd22704cb4`.

## Root-current integration receipt

- Root: `C:\Users\Adam\.local-ai-hub`
- HEAD before/after: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Source SHA-256 before/after: `1B82D39E51A16F1C2AA1E74E7324E13A56CE30C601788B3DEEBA82C7EBC930B2`
- Test SHA-256 before/after: `202E4C468A14E2A83E90FF4B4ABF587051C1B50249B518F97AD4A5DF05D9C17C`
- Same two-selector command; T20 one-shot GO.
- Result: exit `0`; `2 passed in 0.26s`; wrapper duration `0.796s`; command broker duration `1.248s`.
- Execution ID: `2097f0070ef84fd2890517cf7cd9e142`.
- Orchestration receipt: `git apply --check` and `git diff --check` passed.

Both tests mock `get_gpu_telemetry` and use CPU threads. No physical GPU, Ollama, or network access.

## Packet and remaining acceptance

- Root-current patch: `handoff/T12-root-current-vram-timeout-20261004.patch`
- Patch SHA-256: `893F12C48E950E8396B290AE0B35977F7995A5F57DB7FC7A5B31E93563C3C4BB`
- Last reported live profile: balanced RTX 4060; no other physical hosts available.
- T02 paired baseline artifact absent; no optimization comparison or claim.
- This receipt proves the bounded VRAM sampler timeout regressions only. T12 profile-wide quality, latency, VRAM, scheduler/fairness, batch, overload, cancellation, and fallback acceptance remain incomplete unless separately receipted.
- No further test is authorized by this receipt; wait for a fresh T20 GO.
