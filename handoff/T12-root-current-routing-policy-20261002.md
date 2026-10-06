# T12 root-current routing/policy handoff — 2026-10-02

Candidate: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub` at `933c0129079fcc0c894a71fe842cbbb5e6ad7285`. Current root: `C:\Users\Adam\.local-ai-hub` at `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

## Comparison

- `model_policy.py`, `router.py`, and `hardware.py` are byte-identical in candidate and root.
- Candidate `services.py` differs broadly from root due concurrent integration work; only `apply_project_settings` call ASTs were compared, and they match. No services patch generated.
- Root has real `src/local_ai_hub/project_config.py` (SHA-256 `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713`); candidate lacks it. File excluded from patch as another owner's source.
- Seven previously non-green consumer cases now pass using candidate package plus current root module, read-only: **7 passed in 1.91s**. No root tests or files changed.

## Root-current patch

[Patch](T12-root-current-routing-policy-20261002.patch), SHA-256 `38BC78E9315668ED0D6D36001AFF3722E7448187957EB4F20DCF87C9347174D3`. It updates only stale model-role and token-economizer policy lines in root `AGENTS.md` and `docs/INSTALL_PROMPT.md`, then adds two refresh requirements to root `docs/UPDATE_PROMPT.md`. Other root policy content stays intact.

`git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error -- handoff/T12-root-current-routing-policy-20261002.patch` — **PASS**. Patch was not applied. Root policy files were already dirty before this check; those changes remain untouched.

Machine-readable hashes and selector detail: [manifest](T12-root-current-routing-policy-20261002.manifest.json).

## Remaining limits

No live CUDA/VRAM or quality evidence. Only balanced RTX 4060 host exists. T02 baseline artifact absent; skip comparison and make no optimization claim. Full T12 remains open.
