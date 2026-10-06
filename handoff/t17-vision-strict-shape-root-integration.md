# T17 vision strict-shape root integration handoff

- Candidate patch SHA-256: `299F438AA20FD2B1599CCFCB3BF30E17A587B8A88DE7AB6F2A3C4DD6223A3ACB`.
- Current-root `git apply --check`: PASS; post-integration `git apply --reverse --check`: PASS.
- Root strict-shape selectors: **6 passed** in 0.80 s. Expanded root acceptance: **174 passed** in 46.64 s.

Exact root selector command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_vision_contracts.py::test_strict_vision_output_rejects_unknown_root_field `
  tests/test_vision_contracts.py::test_dom_facts_must_ground_every_cited_element `
  tests/test_vision_contracts.py::test_dom_fact_must_support_observed_text `
  tests/test_vision_contracts.py::test_vision_result_bounds_bbox_to_image_dimensions `
  tests/test_vision_service.py::test_vision_rejects_dom_observation_fact_that_mismatches_supplied_source `
  tests/test_vision_service.py::test_malformed_vision_output_is_terminal_structured_failure
```
## Follow-up acceptance evidence (2026-10-01)

- Candidate audio/vision command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py tests/test_http_vision_routes.py tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint` — **141 passed** in 16.97 s.
- Candidate browser/runtime/accessibility-review command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_frontend_review.py tests/test_frontend_coder_context.py` — **58 passed** in 12.28 s.
- Root browser selectors previously passed: `tests/test_browser_bridge_runtime.py tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint tests/test_browser_bridge.py::test_extension_treats_malformed_commit_response_as_unknown` — **5 passed**.
- Root strict-shape patch integration verified after integration with `git apply --reverse --check`: **PASS**.
- Root strict-shape/grounding pytest selectors: **6 passed** in 0.80 s. Expanded root acceptance below: **174 passed** in 46.64 s.

Root expanded acceptance command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_browser_bridge_runtime.py tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py tests/test_http_vision_routes.py tests/test_mcp_agent_routing.py::test_local_ai_task_transcribe_forwards_only_explicit_language_hint
```

## Evidence boundary

These are automated candidate and root pytest/Node fixture results plus root patch-presence check. No live browser session, visual capture, real accessibility tree, or live vision/transcription model run was performed. `/api/context/pack` remained outside T17 scope and was not edited.
