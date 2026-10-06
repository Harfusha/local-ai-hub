# T12 T13-to-T11 model-release transition evidence

## Scope and ownership

- Worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`, HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285`.
- Test-only handoff artifact: `handoff/test_t12_model_release_transition.py`.
- Product source loaded from the pinned T12 root-current overlay at `.handoff/T12-root-current-overlay-20261001/src`; no `operational_mode.py`, `model_lifecycle.py`, or other T13/T11 source was copied or edited.
- The test asserts imports resolve to the overlay's real `http_server.py` and `model_lifecycle.py` paths. Runtime, active-work registry, and torch CUDA API are fakes; no Ollama/model/GPU was started.

## Exact test

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -B -m pytest -q -p no:cacheprovider --tb=short handoff/test_t12_model_release_transition.py
```

Result: **3 passed in 0.34s**.

The three cases verify: (1) the real `/api/admin/mode` handler calls the cancellation hook and drains before Ollama unload, releases both tracked CUDA owners, and calls `empty_cache` once after the final owner; (2) an undrained inference skips Ollama and CUDA release and retains the release guard; (3) a concurrent owner lock timeout is reported as failed/unverified, while the other owner may detach but the shared CUDA cache is not emptied while the busy owner remains tracked.

## SHA-256 pins

| File | SHA-256 |
| --- | --- |
| `handoff/test_t12_model_release_transition.py` | `C4F005E141D6091D0067DD3C50648EE07330003079327630432B623CAB40D160` |
| `http_server.py` | `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3` |
| `model_lifecycle.py` | `782337CA8110965CBC213F7425280A5BA403327BDE85F0A8DB89556700B482FD` |
| `operational_mode.py` | `50FA2F56E0B0FDECED08EA1603C78D81DB2E4451BDEFA4E1D6D219D0FD60E8F9` |
| `embeddings.py` | `21A6282871005D1045B2E76A2CC65599DEEDB877477E007C1AA8FB31BFACCD08` |
| `reranker.py` | `12773E04A90DB8F8A367E618D725A3EA995FAF4B624244907B8A13F30CED2EC7` |

## Boundary

This proves the adapter ordering and T11 tracked-owner allocator contract against the dated source overlay with deterministic fakes. It does not prove live CUDA, physical VRAM reclamation, a live Ollama unload, or that the overlay still matches today's T20 root. Broader T12 acceptance stays blocked by missing T02 baseline, integrated/high/max host receipts, and current-source live/profile evidence.
