# T12 owner packet index — 2026-10-05

Candidate identity: registered attached Git worktree `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`; attach confirmed operation `f7d62b6f-3ca2-4435-8172-1ed4c18fdd2b`; HEAD `933c0129079fcc0c894a71fe842cbbb5e6ad7285` (detached).

Latest bounded candidate state before this index: 42 changed paths, fingerprint `065e0ef6953b220617755d8de88f1ba328a422801cd93eed70be7a91a6958f1d`. Paths are mixed T12 and inherited/other-owner work; preserve them. Shared root remains paused under T20's disputed 379-vs-452 inventory. No root was read or changed for this index.

## Existing candidate packets

These packet files were SHA-256 checked in the assigned candidate on 2026-10-05. Their dates and root preimages predate today's unresolved root inventory; they are not fresh root applicability receipts.

| Packet | SHA-256 | Owned path(s) | Recorded root preimage | Current candidate file SHA-256 |
|---|---|---|---|---|
| `handoff/T12-tiered-wrapper-root-current-20261002.patch` | `ABD0E8A67DE3B38AB71E275AAABFFB9132CD2EC82DCE608B31BCEDBBDB3EC6DD` | `src/local_ai_hub/tiered_ollama.py` | `981E339CA6FB054ACAD5E5AFF4FAD24A303E67DB56A8235D2D161D6927C5A394` (2026-10-02) | `C21644B24CB996FD682A1D7EEE11C5B3FD2763597891AFA0F427D3208E04F5FB` |
| `handoff/T12-tiered-wrapper-tests-root-current-20261002.patch` | `7A2CC279B828D6146B571F3F9BF2E0F490ACB240C7B131FAC58B66FB99A85207` | `tests/test_tiered_ollama_runtime.py` | `99F2F732C0055D8E041434F766BD72BCBAB6AA85430652E6EE167ED5C5BA0DA7` (2026-10-02) | `E50E87D7F3268D7AC01AD9C8F7A9A4E9F1142115F130A786EB6FDC1298854686` |
| `handoff/T12-tiered-wrapper-tests-20261002.patch` | `EA7625A99B10DCE81DD36EDA3AC209B6395521EE74709E9B7D3B1870B19E18EA` | `tests/test_tiered_ollama_runtime.py` | Older candidate-specific test preimage; do not apply to root | `E50E87D7F3268D7AC01AD9C8F7A9A4E9F1142115F130A786EB6FDC1298854686` |
| `handoff/T12-generated-policy-sync-20261004.patch` | `5F2E0207E8332F1C2976E7872E1FBDB53A6F52AA1F5A244474998B14B8CC5BBF` | `src/local_ai_hub/generator.py`, `AGENTS.md`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md` | Candidate patch; root preimages are not a current integration contract | Candidate postimages: generator `5AA14AC1D6FC9462ADA6CC2E495B519E18D1E535E37D2AC3245888376B4747FF`; AGENTS `3FD4C90FA3DD10CCA0E4C20423E1B25521C554C32953EEAD628B0CE166D2EA78`; INSTALL `0B14752FDC0C4118DEA636B23F35005CA1D6F57DBD5950C1C7613353F650A7F9`; UPDATE `574F8673C18799CBC5566DD22CEC73EC00A66B571052A5DFC4D11B0866FDEE8A` |
| `handoff/T12-root-current-generator-policy-20261004.patch` | `22CEAC047EBC3957949E7822CEB3F46A9DACBECD8BAFD819B474A127D159A74C` | `src/local_ai_hub/generator.py` | `2147622D0713579F7BE9EEE9890C646D50F932F26687D26BB951A51E560CDFCB` (dated) | `5AA14AC1D6FC9462ADA6CC2E495B519E18D1E535E37D2AC3245888376B4747FF` |
| `handoff/T12-root-current-vram-timeout-20261003.patch` | `254200B68677DB9ED44166720A335338BC8DF80A691D8B47740AB02643587542` | `src/local_ai_hub/vram_balancer.py`, `tests/test_vram_balancer.py` | `vram_balancer.py` `F5A5A7E0F5129F4144B875B4FD54D7C9E92685A7B66E94E54DAF5FA337D5E00A`; test `3C14CA43DA632903E85A394967A79145542C27B4AB53A43CFC7DC3A00CA5DB05` (dated) | Candidate source `1B82D39E51A16F1C2AA1E74E7324E13A56CE30C601788B3DEEBA82C7EBC930B2`; test `202E4C468A14E2A83E90FF4B4ABF587051C1B50249B518F97AD4A5DF05D9C17C` |

## Exact candidate receipts

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_tiered_ollama_runtime.py::test_post_unload_admission_capability_delegates_to_selected_runtime` — **1 passed**, pytest `0.10 s`, exit 0; `git diff --check` exit 0. The candidate's existing effective capability delegate was tested; no lasting source/test change from that run.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_router.py tests/test_local_model_availability.py tests/test_completion_model_routing.py tests/test_model_quality.py` — **56 passed**, pytest `0.82 s`, wrapper `1.273 s`, exit 0; synthetic/mock only.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_setup.py::test_instruction_policy_blocks_match_generated_policy_sources` — **24 passed**, pytest `1.94 s`, wrapper `2.536 s`, exit 0; `git diff --check` passed.
- Historical VRAM timeout/cache regression: **2 passed** with CPU mocks. Historical broad matrix: 303 passed, 5 skipped, 7 failed, 1 teardown error; full failure details were not reproduced here and no broad run was repeated.

## Integration boundary

These dated packets are immutable handoffs, not authorization to apply. T20 must first reconcile root identity/dirty ownership, then refresh each required root preimage and simulate integration. No current root postimage hash is claimed. No packet is safe to apply solely from this index. T14 `/api/context/pack`, shared `services.py` ownership, and all unrelated dirty paths stay excluded.
