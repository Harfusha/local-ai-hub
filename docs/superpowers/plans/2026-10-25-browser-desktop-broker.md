# Browser and desktop automation implementation plan

**Goal:** Integrate existing Playwright MCP and Microsoft winapp automation behind the existing Hub MCP tool, with explicit target permissions and owned sessions.
**Architecture:** One installation broker owns bounded, expiring sessions. Each browser session has an owned Playwright MCP process; extension mode exclusively leases the personal profile, isolated mode uses a fresh headless context. Desktop sessions bind one configured executable and window identity. No arbitrary agent JavaScript, CDP, shell, or executable selection.
**Spec:** Approved design in this chat, 2026-10-25. Network egress isolation and VM provisioning are distinct from browser context isolation and are not silently claimed.
**Global constraints:** Python 3.11+; seven public MCP tools; exact origin/optional path rules; default disabled and deny-all; no automatic package/browser downloads; preserve API authorization and repository/task scopes; no tenant identities. Personal-browser connection requires the existing extension's user selection.

- [x] Add failing tests for canonical URL policy, owner/key isolation, capacity, exclusivity, expiry, duplicate requests, timeout fencing and adapter argument construction.
- [x] Implement broker, fixed-operation browser adapter using installed Playwright MCP, and window-bound winapp adapter.
- [x] Connect automation action to MCP/HTTP authorization, task root checks, app shutdown and validated configuration.
- [x] Synchronize operator guide, optional dependency setup and install/update prompts.
- [x] Run targeted regressions and actual isolated Chrome acceptance. Indexed/local advisory review attempted once each but blocked by Hub gaming mode; no mode bypass or retry.

## Validation boundaries

No live personal-profile takeover, Hub restart, deployment or privileged desktop operation. Tests may create temporary fixtures and subprocesses. Fake-adapter tests establish broker behavior, not real UI support. Existing upstream extension/CLI availability must be distinguished from local installation.

## Ledger

- Baseline: clean master 906f1c4d8a99c345e467367b771f2f3b6f4129f6. Agent OS task task_a1eb2e91e92f.
- Ruling: preserve existing browser capture action; add automation action to local_ai_task for owned browser and desktop sessions. This avoids changing the capture contract or adding public tools.
- Ruling: extension mode leases a profile exclusively until its upstream concurrent-connection semantics are proven; isolated sessions remain independently concurrent.
- Preserved concurrent foreign edits: pyproject.toml dev dependencies, tests/test_agent_memory.py, tests/test_client_startup_resilience.py, tests/test_t11_rag_project_policy.py. No reset/stash/clean, commit, deployment or live Hub restart.
- Validation: `python -m pytest -q tests/test_automation_broker.py tests/test_automation_adapters.py tests/test_automation_integration.py tests/test_automation_runtime.py tests/test_browser_bridge.py tests/test_browser_artifact_atomicity.py tests/test_http_vision_routes.py tests/test_mcp_contract_dispatch.py tests/unit/test_mcp_browser_bridge.py tests/test_surface_audit_policy.py tests/test_project_config.py tests/test_surface_and_packaging.py --tb=short`: **290 passed in 52.36s**. Opt-in runtime environment pointed at an isolated temporary installation of @playwright/mcp 0.0.83; no personal-profile attachment.
- Actual Chrome proof includes accessibility snapshot, fill/click, PNG artifact, upload/download, confirm handling, auxiliary tabs, blocked iframe/HTTP redirect outside an allowed path and cancellation/cleanup. Actual HTTP proof includes API token checks, task repository binding, session open/act/close. Fake winapp tests verify host/guest identity and command scoping only.
- Static validation: new modules/tests pyflakes, changed Python modules compileall, node syntax, agent surface audit and git diff --check passed. Updated only the two new reviewed automation surface dispositions.
- Remaining runtime boundaries: personal Chrome extension, native Windows UI and operator-prepared Windows Sandbox were not exercised. Automation defaults remain disabled and deny-all. Windows Sandbox is one shared guest; browser contexts do not establish OS/network isolation.
- Agent OS checkpoint/completion attempted after validation. Hub gaming mode and/or receipt gates remain authoritative; native test stdout is not converted into synthetic broker receipts.

## Main integration follow-up

- Human approved inclusion in the existing integration task `post-gemini-audit-20261025`; broker chat completed and handed over all writes/tests. Its previously blocked lease release was completed after the operator changed to Active revision 9. Primary integrator now owns the root lease.
- Audit reproduced explicit port `0` being accepted as default `80`/`443` and oversized downloads being checked only after completing transfer. Added HTTP/HTTPS rule/candidate regressions and actual Chrome tests for oversized known/unknown-length responses. Initial regressions failed; no assertions, limits or timeouts were relaxed.
- Corrected `_url` to distinguish omitted ports from zero. Added bounded CDP response streaming to the existing fixed browser adapter; no URL replay, agent code, new public tool, implicit backend installation or permission expansion.
- `owned-check-automation-transfer-port-corrected-20261025T151734Z`: **36 passed**, including actual Chrome, producer cancellation before full transfer and no rejected `.bin` residue; source/config stable. Earlier `owned-check-combined-broker-ci-baseline-20261025T144524Z`: 125 passed/1 explicitly opted-out Chrome test, separately verified by `owned-check-combined-broker-real-chrome-20261025T144617Z` (1 passed). These are native evidence records, not broker receipts or release acceptance.
- Required remaining gates: combined review/CI fixes, current full suite and coverage ratchet, package/installed provenance, full runtime/UI acceptance and integration commit. Personal Chrome/Windows/Sandbox remain unverified; source feature stays disabled by default. Local advisory test review `req_19d2720015c6` was malformed/unverified and is not acceptance evidence.
