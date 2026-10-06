# T04 SSE and transport parity handoff

Candidate root/worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root files remain untouched.

## SSE defect and fix

Regression: `Handler._stream_agent_events` treated write disconnects and unexpected stream failures as success in its `finally` block. The SSE test's dummy finish hook did not record classification, so this was not detected.

Changed candidate paths:
- `src/local_ai_hub/http_server.py` SHA-256 `20d0e9fe3ea625fc77ae18d12bb98f5fc2e77d88f00f6801b06d4bece43c0932`
- `tests/test_sse_events_stream.py` SHA-256 `bcee7a41e7a561de6e1f4c5f7c663ccfe518cac9616f48064a5cd86cb67eeecc`

Behavior: replay/live/keep-alive/timeout writes that fail now finalize as `(success=False, error="client disconnected")`. Other stream exceptions finalize as `(False, "stream failed")`. Subscription cleanup remains in `finally`.

## Test receipts

RED command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py::test_sse_stream_replays_and_receives_live_events`

Result: **1 failed in 2.21s**, expected before-fix assertion; actual finish was `(True, "")` instead of `(False, "client disconnected")`.

GREEN command: same selector, after fix. Result: **1 passed in 0.35s**.

Additional candidate command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py::test_sse_stream_does_not_lose_event_between_replay_and_subscribe tests/test_sse_events_stream.py::test_sse_stream_timeout_bounds_queue_wait tests/test_sse_events_stream.py::test_client_stream_events_parsing tests/test_client_transport.py::test_stream_events_sends_client_identity_and_caps_timeout tests/test_client_transport.py::test_stream_events_reports_uncertain_partial_disconnect tests/test_client_transport.py::test_stream_events_cancel_event_closes_blocked_response tests/test_client_transport.py::test_stream_events_enforces_deadline_while_response_is_blocked tests/test_client_transport.py::test_post_uses_explicit_request_id_across_safe_retry tests/test_client_transport.py::test_post_rejects_malformed_request_ids_before_network tests/test_client_transport.py::test_transport_connection_refusal_marks_request_not_sent tests/test_client_transport.py::test_transport_other_connect_failure_is_not_classified_as_request_not_sent tests/test_client_transport.py::test_transport_write_failure_marks_outcome_unknown tests/test_client_transport.py::test_post_malformed_response_returns_explicit_unknown_outcome tests/test_t04_malformed_json_contract.py`

Result: **16 passed in 2.93s**, exit 0. Covers stream cancel, partial disconnect classification, stable/rejected request IDs, connect-refused vs uncertain write, and complete malformed JSON envelopes.

AST parse and scoped `git diff --check` passed.

## Root-current patch

Patch: `handoff/t04-sse-disconnect-root-current.patch`
SHA-256: `d17394eb216f92a783555ccf420435231da268a75d1e0dfc0d88a33ed8a32271`
Paths: `src/local_ai_hub/http_server.py`, `tests/test_sse_events_stream.py`
Root preimage SHA-256:
- `src/local_ai_hub/http_server.py`: `c619ae6297f9b99466304722e95455994bffdf88258e32b1487fed247f159e15`
- `tests/test_sse_events_stream.py`: `fd278ef2a1472203b50c99f9d5e2d1af0f87397b6db3a103952d91be5bd88cbd`

`git apply --check --whitespace=error` passed against root current dirty state; root HEAD stayed unchanged. Patch excludes unrelated dirty HTTP routes. T20 owns root integration and root validation.
