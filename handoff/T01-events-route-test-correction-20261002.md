# T01 events route test correction — 2026-10-02

## Test-only change

- Updated only `tests/test_http_route_operation_acceptance.py` in T01 to spy on `app.agent_state.event_page`; kept the existing `calls == [("stream-31", 4, 9)]` and response assertions unchanged.
- T01 test preimage SHA256: `330C91CDA532142C74C47E93CDAC624E5F2B0858F831586CE0509CF114973EC5`.
- T01 updated test SHA256: `00286DF5140B8858C409410D5B4527E236D170B11DB7494743CB4F46031C5296`.
- T01 source `src/local_ai_hub/http_server.py` SHA256: `B5F0A63A0E8F68CE71B81C6B2EC49DE3F9FF8E30AAC90D244298AD790857A35D`.

## Root-current patch prepared, not applied

- Patch: `handoff/T01-root-events-event-page-spy.patch`
- Exact root test preimage SHA256: `AC699F603271308B22C1E6CF2C4B0096A2371F276690B39CE3F6253BB32BB832`.
- Patch SHA256: `F6D03A0BBA888ACD10CC34133C914DEE3B5CA81C2915C9E0EDC82ED9F200F45D`.
- Scratch `git apply --check --whitespace=error`: exit 0, no output.
- Predicted patched root test SHA256: `BD01B4DBE8A0DBA1AF8B1171ED5F15B9ED1888A06AF05A7C7BC9A9CC84DCF679`.
- Root was not edited. Post-run root test SHA remained the preimage; root HEAD remained `01df56605ccf484ebfe2808ac60d696c4e81dffc`.

## Candidate selector result

Preflight: T01 HEAD `689165fbe18101feacf5f489847a4890fc27ed1f`; active pytest process count 0; test and source hashes matched the pins above.

Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_route_operation_acceptance.py::test_http_get_agent_state_events_forwards_stream_cursor_and_limit
```

Result: **1 failed in 4.21s**. `monkeypatch.setattr(app.agent_state, "event_page", event_page)` raised `AttributeError`: T01's `AgentStateStore` has no `event_page`. T01 HTTP route still calls `APP.agent_state.events` (`src/local_ai_hub/http_server.py:1622`); root-current route calls `agent_state.event_page` (`src/local_ai_hub/http_server.py:2275`). Do not replace the selector or weaken assertions. This is a source-revision mismatch; T08 is the recommended owner for the agent-state event API, T20 for integration.

Postflight: pytest process count 0; T01 source and test hashes remained unchanged during the run. Root-current test/source were not edited or rerun.
