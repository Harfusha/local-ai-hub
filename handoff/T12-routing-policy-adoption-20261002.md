# T12 routing, prompt policy, and token-economizer handoff — 2026-10-02

## Acceptance

Focused routing/policy/token-economizer selector set passed: **66 passed, 20 subtests passed in 3.92s**.

Command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_agent_policy.py tests/test_token_economy_tools.py tests/test_completion_model_routing.py tests/test_model_policy_sampling_floor.py tests/test_llama_cpp_routing.py
```

Checked policy block identity across `AGENTS.md`, `docs/INSTALL_PROMPT.md`, and `docs/UPDATE_PROMPT.md`. Both `LOCAL AI HUB TOOL POLICY` and `TOKEN ECONOMY POLICY` matched byte-for-byte after marker extraction. Hashes: local tool policy `{policy_hashes['LOCAL AI HUB TOOL POLICY']}`; token economy policy `{policy_hashes['TOKEN ECONOMY POLICY']}`.

## Scope paths and SHA-256

- `AGENTS.md`: `F6A8E38845F4D92F4843D66692ACD7B5AB9700829BB4561784E34AFE75577200`
- `docs/INSTALL_PROMPT.md`: `2F09D9C17F5ABFB9E9C592FFD925C7CC663A601D87FC9DFC7FA3528F6D4F1E18`
- `docs/UPDATE_PROMPT.md`: `F56E684D4DBECF18FB9B8AB4C8F255D561602A751A06C6AD2B8A8E8416691B3E`
- `src/local_ai_hub/router.py`: `AC089C43BD6A3CBEE26F3A742D80C92E7252D5A803491842EA7CB5D9C2E74B49`
- `src/local_ai_hub/model_policy.py`: `8A3111368C0CCCD6616C87B27EAE366359F8D5821D1261E337E5CD9982F19013`
- `tests/test_model_routing.py`: `4681E55CE6B149FB41D54C35C48104D6734769AC068A18B8AD945540EF006AA4`
- `tests/test_agent_policy.py`: `87F6E52F7DBA6BFA6370540AF163CB8C04155E4D63AFA5427CBA1C742434D7BC`
- `tests/test_token_economy_tools.py`: `BBF627D4F17812B61C9B04552A32A8D73FE1B554C85BE40A6B8F0BBA3BF3DF7E`
- `tests/test_completion_model_routing.py`: `3C37562CCAF9F54EE5E3F0FD0FF5743F0F45C14AE077013FDC7B9B011FD10FFF`
- `tests/test_model_policy_sampling_floor.py`: `3355B2B3DB8F3EAEA6EDD7B6C217CB24033254CD5886EF01AD693E5477B59D22`
- `tests/test_llama_cpp_routing.py`: `D67C7F65EAC5940FB682A60AD063DCDFB1D0BB2D13099A5FD7753712407CB6C2`


No source or prompt file was edited in this continuation. Existing dirty T12 changes remain in their worktree. No dependencies installed. No root edits or merge.

## Limits

This proves deterministic routing and prompt/tool-policy contracts only. Live provider behavior, model quality, CUDA/VRAM, and physical profile acceptance remain unverified. T02 baseline artifact absent; skip comparison and make no optimization claim.


## Root-current patch revalidation (2026-10-02)

Against `C:\Users\Adam\.local-ai-hub`, the T12 policy patch was checked read-only. Forward `git apply --check --whitespace=error` failed at `AGENTS.md:52`, `docs/INSTALL_PROMPT.md:168`, and `docs/UPDATE_PROMPT.md:95`; reverse `git apply --reverse --check --whitespace=error` passed. This confirms the patch hunks are already present in the current root. T12 made no root writes. T19 was asked to exclude these already-integrated hunks from its refreshed docs patch.

User-confirmed evidence limits: only the balanced RTX 4060 host is available; integrated/high/max live profile runs are unavailable. No T02 baseline artifact exists, so comparison is skipped and no optimization claim is made.
