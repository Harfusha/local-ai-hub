# T12 routing, prompt, and TOML receipt

## Scope and baseline

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub`
- Candidate HEAD: `933c0129079fcc0c894a71fe842cbbb5e6ad7285`
- The worktree has many inherited or other-owner dirty paths. This receipt does not attribute them to T12. No root files, source, tests, or prompt files were changed while preparing this receipt.

## Contract observations

- `defaults.toml` and `src/local_ai_hub/defaults.toml` parse successfully. Their `hardware.profile` and `[models]` mappings compare equal. Their complete file SHA-256 values differ, so only those fields are confirmed synchronized.
- Confirmed model mapping: `background_code=qwen2.5-coder:0.5b`, `fast_code=qwen2.5-coder:1.5b`, `heavy_code=qwen2.5-coder:3b`, `reasoning=qwen2.5-coder:7b`, `general=qwen2.5-coder:3b`, `vision=qwen3-vl:4b`.
- `docs/MODEL_CAPABILITIES.md` contains the integrated/balanced/high/max role matrix. Candidate `hardware.py` and routing tests are unchanged during this receipt.
- Candidate `AGENTS.md` SHA-256: `F448F39E32AD7933F29E24D686148FEE60D084C559938D4D4FAA4AD97099E9A5`; T21's scoped paragraph and `git diff --check -- AGENTS.md` exit 0 were independently verified.

## Candidate test receipt

Command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_model_routing.py tests/test_config_hardware.py tests/test_prompt_contracts.py tests/test_model_policy_sampling_floor.py tests/test_setup.py::test_instruction_policy_blocks_match_generated_policy_sources
```

Result: `1 failed, 23 passed in 1.68s`; exit 1; broker duration 2.1784s. Sole failure: `test_instruction_policy_blocks_match_generated_policy_sources[AGENTS.md]`.

Root cause: the test compares the complete generated policy block against `generate_global_policy({})`. Candidate AGENTS has T21's new tier paragraph; `src/local_ai_hub/generator.py` and candidate INSTALL/UPDATE generated blocks still use the previous config-derived policy. The output and source agree for INSTALL/UPDATE, not AGENTS. Fix requires source-generator and all generated policy blocks to be reconciled together. No retry performed.

Pre/post test, source, TOML, prompt, and candidate HEAD hashes were unchanged by the command. The command ran in the candidate worktree only; no live inference, model pull, or root test.

## Prompt ownership and packets

- INSTALL/UPDATE prompt sections remain T19-owned. T19 reports its assigned worktree unavailable; T12 did not edit those files.
- Root-current preimages observed read-only: `AGENTS.md` `FE64D54D0B96ED80FE89AD33458B7216BFC771D723B4A026D190C20614DCCC1D`; INSTALL `55037EA931333336908A40BEFACA633D141E55FF90BEB2F909FA4013827A5CE2`; UPDATE `A54522C8AD0BC04749192E89D6A63FCAB4660A958AD6C46E99FB73CCD1E62163`.
- `T12-root-current-agents-policy-20261004.patch` SHA-256: `33E7BB3FDA22B05A04CEF949BFBBDEC4FFF1A4CA0D8BD714DBDDF3BCF3FB51A1`.
- `T12-prompt-tier-policy-root-patch-20261004.patch` SHA-256: `3AEAD3F57D69835EE397EB8B428FDDA8C9A43A4E9E6D20EFA2B1D0B289AECC5B`.
- Both are handoff drafts only. Do not apply either alone: generated policy source and all owned generated blocks need one coordinated update first. Root remains untouched.

## Remaining acceptance

- Generated policy synchronization fails for AGENTS in the candidate suite.
- Profile-wide live quality, latency, and VRAM receipts remain unavailable beyond the balanced RTX 4060 host.
- T02 paired baseline remains absent; no optimization claim.
- Root merge and model downloads remain unperformed.
