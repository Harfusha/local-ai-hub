# T12 routing/policy blob receipt — 2026-10-06

## Candidate identity and scope

- Worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- Comparison master: `b947d76fdfb7ed592b72e55587d5c83cfa352c35`
- Repository fingerprint during evidence capture: `5b46e0cc0c080627c934d8ab1990a1dffcf30d42d0e749d099577ebf8061d8de`
- Dirty count: 42 paths. Existing source/config/doc/test changes are inherited or mixed; this receipt is the only file authored in this continuation. No master/root edits.

## Model routing and generated policy files

The bounded candidate diff against `b947d76f` names these modified paths:

- `AGENTS.md`
- `config.toml.example`
- `defaults.toml`
- `docs/INSTALL_PROMPT.md`
- `docs/UPDATE_PROMPT.md`
- `src/local_ai_hub/generator.py`
- `src/local_ai_hub/model_policy.py`
- `tests/test_local_model_availability.py`
- `tests/test_router.py`
- `tests/test_setup.py`

SHA-256 before and after the focused suites matched:

| Path | SHA-256 |
|---|---|
| `AGENTS.md` | `3FD4C90FA3DD10CCA0E4C20423E1B25521C554C32953EEAD628B0CE166D2EA78` |
| `config.toml.example` | `47780F009EB1D0081F90DC8ED5F769CB246DE42AA2E191B947D6EC6B79730E70` |
| `defaults.toml` | `D688F8546F616B872B2111C1F137C06964035E75C6DA8B2A2DD2F420400A039E` |
| `docs/INSTALL_PROMPT.md` | `0B14752FDC0C4118DEA636B23F35005CA1D6F57DBD5950C1C7613353F650A7F9` |
| `docs/UPDATE_PROMPT.md` | `574F8673C18799CBC5566DD22CEC73EC00A66B571052A5DFC4D11B0866FDEE8A` |
| `docs/MODEL_CAPABILITIES.md` | `09FE472497C3F8F5381CCFEFB64B21CA4453C9110F55BB7C22F22BC313487617` |
| `src/local_ai_hub/generator.py` | `5AA14AC1D6FC9462ADA6CC2E495B519E18D1E535E37D2AC3245888376B4747FF` |
| `src/local_ai_hub/model_policy.py` | `07B26603663FBA0BAE195E755B613F6E307CFD206D32748D7F90A9999127F7E7` |

## Exact test receipts

Commands ran through `local_ai_command`; the listed complete test-file hashes matched immediately before and after the suite runs.

1. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_setup.py::test_instruction_policy_blocks_match_generated_policy_sources`
   - Result: **24 passed in 1.73s**, exit 0.
   - Test file SHA-256: `test_model_routing.py` `4681E55CE6B149FB41D54C35C48104D6734769AC068A18B8AD945540EF006AA4`; `test_config_hardware.py` `D63E1F38FDC1F6D68EDB349CC6AE2607E8145A58BEBC9E030D797283682C4975`; `test_prompt_contracts.py` `A62C3FCB2EDCC42D7A4C2687967B8A600FA4C82878DC92003EF1B4D1B20D8D88`; `test_model_policy_sampling_floor.py` `3355B2B3DB8F3EAEA6EDD7B6C217CB24033254CD5886EF01AD693E5477B59D22`; `test_setup.py` `E105735577C744D804570A1E423A02EE9786B643D8DCE090DB24D1A05A13F559`.
2. `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_router.py tests/test_local_model_availability.py tests/test_completion_model_routing.py tests/test_model_quality.py`
   - Result: **56 passed in 0.88s**, exit 0.
   - Test file SHA-256: `test_router.py` `BADE3906817F8EB17DC59350364E2AC4E6F6FA9C1FA53EC1BA87A7D62AD498BD`; `test_local_model_availability.py` `2559A986F98D670A3F4914E4295FD9CEDBD9C64191BE19A35EC19F17DFFF2D50`; `test_completion_model_routing.py` `3C37562CCAF9F54EE5E3F0FD0FF5743F0F45C14AE077013FDC7B9B011FD10FFF`; `test_model_quality.py` `15503D68E4AEB021C5E34A4DC204C9666B7D2C59D57791D0EF19AC52860EB264`.
3. `git diff --check b947d76f -- AGENTS.md config.toml.example defaults.toml docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md src/local_ai_hub/generator.py src/local_ai_hub/model_policy.py tests/test_local_model_availability.py tests/test_router.py tests/test_setup.py`
   - Result: exit 0.

These are candidate contract receipts. They do not prove a particular optional model is installed, live quality, physical VRAM, or multi-profile runtime behavior. No model pull/install or live inference occurred.
