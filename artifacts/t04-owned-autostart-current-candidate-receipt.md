# T04 owned autostart acceptance handoff

Candidate: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Root: `C:\Users\Adam\.local-ai-hub`
Root HEAD during patch check: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root remains unchanged.

## Candidate evidence

Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_client_startup_resilience.py::test_readiness_timeout_terminates_only_owned_child_and_cleans_lock tests/test_client_startup_resilience.py::test_blocked_operational_modes_never_spawn_for_offline_request tests/test_client_startup_resilience.py::test_autostart_launches_real_hub_child_and_returns_http_search_result`

Result: **4 passed in 11.36s**, exit 0. Includes real child startup and actual HTTP search result, bounded owned-child cleanup, readiness timeout/lock cleanup, and gaming/maintenance no-spawn structured failure assertions. Test module AST parse and scoped diff check passed.

The real-child fixture uses a temporary TOML config, temporary state directory, and an ephemeral loopback port. Config explicitly disables Ollama, smart Ollama, llama.cpp, Serena, and background preprocessing. Existing HubClient autostart and `/api/search` route remain in use. Test cleans only captured detached child handles with `_stop_owned_child`.

Candidate test module SHA-256: `67264628ed9221610c346594b6385851bac7b3d1351b0a138a426b1a03d86d9d`

## Root-current patch

Patch: `handoff/t04-autostart-cold-child-root-current.patch`
SHA-256: `27bc3212b4d914361a45354359a7f3b285d7593f34f35ce41b49d0ca524a7198`
Touched path: `tests/test_t04_real_child_startup_acceptance.py`
Root-current `git apply --check --whitespace=error` passed. Patch adds explicit disabled backend/preprocessing settings and asserts them in the existing real-child HTTP acceptance test. It does not modify production source or service/store construction.

T20 owns root integration and any root selector. No root tests or files changed in this task.
