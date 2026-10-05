# T03 root MCP routing test isolation packet — 2026-10-05

- Root: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Changed path: `tests/test_mcp_agent_routing.py` only
- Production files unchanged. Existing dirty hunks in this test file preserved; owner patch changes only the autouse fixture.
- Isolation: monkeypatch `_ACCOUNTING_REPORTER.record` before test calls, so async telemetry worker cannot post through the route spy's shared `CLIENT.post`; endpoint and payload assertions remain intact.

| Hash scope | SHA-256 |
|---|---|
| HEAD file base | `78e7ec5c590e003cfca6febe71d21cf49e58b4119395cd350014e763fa578412` |
| Pre-owner dirty worktree file | `d3e0ab9139872a722ec24a8b7c6d7d8571262d5c676e800047cdf1a135a8af96` |
| Post-owner worktree file | `c7407de2e99ccbb3a35b28ae161d247d6764274ea874dd7d7c979df7586523da` |

Patch: `handoff/T03-root-mcp-agent-routing-isolation-20261005.patch`  
Patch SHA-256: `bf832af1ec9b7fca01c995ec517807c5c581f45106cfc81bb05bf43646079da3`

## Verification

Red evidence from root owner report: isolated `test_local_ai_repo_enriches_search_when_source_requested` failed because telemetry POST overwrote captured endpoint; full file had 4 failures and 1 teardown error.

`PYTHONPATH=src; PYTHONDONTWRITEBYTECODE=1; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_agent_routing.py::test_local_ai_repo_enriches_search_when_source_requested`

Result: `1 passed in 3.14s`.

`PYTHONPATH=src; PYTHONDONTWRITEBYTECODE=1; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_agent_routing.py`

Result: `49 passed in 2.76s`.

Root file hash above includes pre-existing dirty tests plus this fixture fix. No root production changes.
