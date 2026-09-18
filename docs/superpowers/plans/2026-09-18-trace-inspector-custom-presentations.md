# Trace Inspector custom presentations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all eight Trace Inspector request types show useful human content immediately, with focused expandable secondary data and no primary content hidden inside `Technical details`.

**Architecture:** Keep the existing Python-generated HTML and embedded JavaScript renderer in `src/local_ai_hub/dashboard.py`. Strengthen the shared presentation contract so each renderer returns a visible primary section plus explicit secondary `<details>` sections; retain the outer technical disclosure only for universal diagnostics, tabs, events, and raw JSON. Extend the existing Node-backed contract/runtime tests instead of adding a frontend dependency.

**Tech Stack:** Python 3.11+, embedded browser JavaScript, native HTML `<details>`, pytest, Node.js fixture tests.

**Spec:** `docs/superpowers/specs/2026-09-18-trace-inspector-custom-presentations-design.md`

## Global Constraints

- Preserve trace APIs, polling, SQLite persistence, redaction defaults, tab state, and raw trace fallback.
- Use existing sanitization, escaping, truncation, copy, and bounded rendering helpers.
- Keep primary markup free of secrets, headers, tokens, internal-only identifiers, empty values, and duplicate metadata.
- Technical disclosures stay closed by default and retain open state during polling refreshes.
- No new frontend dependency, endpoint, persistence schema, or unrelated dashboard refactor.
- Every renderer must handle missing, empty, malformed, redacted, truncated, live, and failed data states.

---

### Task 1: Establish shared presentation contract and fixture matrix

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py` near existing Trace Inspector fixtures and renderer tests.
- Modify: `src/local_ai_hub/dashboard.py:2073-2459` only after the failing tests exist.

**Interfaces:**
- Existing `tracePresentationKind(model)` remains the dispatcher.
- Existing renderer functions continue returning HTML strings.
- New shared helpers use existing `tracePresentationField`, `traceSummaryCard`, `traceCodeBlock`, `traceList`, `traceFinalizeMarkup`, and `traceReadableMarkup` helpers.

- [ ] **Step 1: Add one fixture for each presentation kind.**

Extend the existing fixture dictionary with representative primary data for `model_chat`, `agent_loop`, `command`, `review`, `repo_intelligence`, `rag_search`, `async_job`, and `request_response`, including one failed and one incomplete case. Keep fixtures bounded and free of real secrets.

- [ ] **Step 2: Add the failing shared contract test.**

Add a Node-backed test that invokes each renderer and asserts its output contains a visible primary marker and at least one type-specific value, while `Technical details` is not required to find that value. Assert that `[object Object]` and raw unsanitized secret markers are absent.

```python
for kind, renderer, markers in renderer_contracts:
    output = rendered[kind]
    assert 'class="trace-primary"' in output
    for marker in markers:
        assert marker in output
    assert '[object Object]' not in output
```

- [ ] **Step 3: Run the focused contract test and confirm RED.**

Run:

```bash
python -m pytest -q tests/test_dashboard_custom_modals.py -k "presentation or renderer" --tb=short
```

Expected: failure for at least one new contract marker before renderer changes.

- [ ] **Step 4: Add shared section helpers with minimal behavior.**

Add helpers beside the existing presentation helpers:

```javascript
function tracePrimarySection(title, subtitle, markup) { /* visible section */ }
function traceSecondaryDetails(title, markup, options = {}) { /* closed details */ }
function traceAttentionSection(items, budget) { /* meaningful warnings/errors */ }
function tracePresentationShell(title, subtitle, primary, secondary, attention = '') { /* shared layout */ }
```

Helpers omit empty markup, use native `<details>`, preserve escaped labels, and pass all values through existing safe helpers.

- [ ] **Step 5: Run the focused contract test and confirm GREEN.**

Run the same command. Expected: shared shell tests pass; type-specific tests may remain RED until their tasks are complete.

### Task 2: Rebuild model chat and agent loop presentations

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` functions `renderModelChatPresentation` and `renderAgentLoopPresentation`.
- Test: `tests/test_dashboard_custom_modals.py` model-chat and agent-loop runtime tests.

**Interfaces:**
- Consume normalized `model.input`, `model.output`, `model.thinking`, `model.toolCalls`, `model.events`, and `model.presentation`.
- Produce visible primary prompt/result cards and closed secondary timeline/context details.

- [ ] **Step 1: Add failing assertions for model chat.**

Assert visible prompt, final response, status/capture state, and tool-call summary. Assert reasoning, model context, and execution timeline use expandable sections.

- [ ] **Step 2: Add failing assertions for agent loop.**

Assert visible objective, lifecycle, final result, failure summary, and ordered tool cards. Assert raw tool payloads and full event metadata are expandable.

- [ ] **Step 3: Run model-chat and agent-loop tests and confirm RED.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k "model_chat or agent_loop" --tb=short`.

- [ ] **Step 4: Implement visible primary sections.**

Keep chronological grouping and tool pairing. Move only secondary timeline, reasoning, model context, and raw payloads into focused closed details. Keep final response complete, bounded, and copyable.

- [ ] **Step 5: Run the same tests and confirm GREEN.**

Expected: model-chat and agent-loop contract/runtime tests pass with no redaction or escaping regressions.

### Task 3: Rebuild command and review presentations

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` functions `renderCommandPresentation` and `renderReviewPresentation`.
- Test: `tests/test_dashboard_custom_modals.py` command/review fixture and runtime tests.

**Interfaces:**
- Consume command fields (`command`, `args`, `stdin`, `stdout`, `stderr`, exit state, retries, duration) and review fields (`request`, `context`, `diff`, `findings`, `recommendation`, status, severity counts).
- Produce semantic cards, not generic JSON dumps.

- [ ] **Step 1: Add failing command assertions.**

Require command line, arguments, exit state, duration, success/failure, and bounded stdout/stderr preview in visible markup; require cwd, paths, retries, criterion, and raw payload in expandable details.

- [ ] **Step 2: Add failing review assertions.**

Require review target, overall status, severity counts, findings, and recommendation in visible markup; require diff/context and full finding metadata in expandable details.

- [ ] **Step 3: Run focused command/review tests and confirm RED.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k "command or review" --tb=short`.

- [ ] **Step 4: Implement the two renderers using shared shell helpers.**

Keep severity chips and stdout/stderr escaping. Add explicit no-output, failed-command, no-findings, and incomplete-review states.

- [ ] **Step 5: Run focused tests and confirm GREEN.**

Expected: semantic command/review tests pass, including structured values and redaction.

### Task 4: Rebuild repository intelligence and RAG presentations

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` functions `renderRepoIntelligencePresentation` and `renderRagSearchPresentation`.
- Test: `tests/test_dashboard_custom_modals.py` repository/RAG fixture and runtime tests.

**Interfaces:**
- Consume repository operation fields, query/context/results, symbols/files, and retrieval query/answer/results/sources/scores.
- Produce visible result-oriented cards with per-item expandable evidence.

- [ ] **Step 1: Add failing repository assertions.**

Require operation, repository/root, query, result summary, files/symbols, and errors first. Require full graph/evidence payloads to be expandable.

- [ ] **Step 2: Add failing RAG assertions.**

Require query, answer, result count, ranked result title/source/snippet, and explicit no-results/truncated states. Require score/provider/path/full payload to expand per result.

- [ ] **Step 3: Run focused repository/RAG tests and confirm RED.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k "repo or rag or search" --tb=short`.

- [ ] **Step 4: Implement result-first layouts.**

Keep ranking and bounded result limits. Never render an object through string coercion; route all structured values through the existing semantic value renderer.

- [ ] **Step 5: Run focused tests and confirm GREEN.**

Expected: repository and RAG renderers expose useful result content without opening technical details.

### Task 5: Rebuild async job, request/response, and generic fallback presentations

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` functions `renderAsyncJobPresentation`, `renderRequestResponsePresentation`, `tracePrimaryFallback`, and outer `renderTraceDetail` assembly.
- Test: `tests/test_dashboard_custom_modals.py` async/request-response/fallback tests.

**Interfaces:**
- Consume lifecycle, timing, correlation, request, response, error, input, output, and capture-state data.
- Produce a visible first answer for generic or malformed traces, even when no specialized fields exist.

- [ ] **Step 1: Add failing async assertions.**

Require job type/status/progress, queue wait, retries, result/error, and explicit live/incomplete state in primary markup; keep IDs, correlations, worker payloads, and event timeline expandable.

- [ ] **Step 2: Add failing request/response assertions.**

Require method/path/action, status, duration, request, response, and error in primary markup; keep headers, actor/tenant, correlations, retained bytes, and raw JSON secondary.

- [ ] **Step 3: Add failing generic fallback assertions.**

Create a malformed/generic model with only captured input/output/error and assert those values appear outside `traceTechnicalDetails`, while empty technical panels do not create blank primary cards.

- [ ] **Step 4: Run focused tests and confirm RED.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py -k "async_job or request_response or fallback or technical_details" --tb=short`.

- [ ] **Step 5: Implement layouts and outer composition.**

Keep `universalSummary`, tabs, event timeline, and raw JSON available. Make primary content independent from the outer technical `<details>` and preserve current open-state restoration during polling.

- [ ] **Step 6: Run focused tests and confirm GREEN.**

Expected: async, request/response, malformed, and outer disclosure tests pass.

### Task 6: Documentation and full verification

**Files:**
- Modify: `docs/DASHBOARD.md` Trace Inspector section.
- Test: `tests/test_dashboard_custom_modals.py` full file plus project validation commands.

- [ ] **Step 1: Update dashboard documentation.**

Document the eight request-specific primary views, visible result-first rule, expandable secondary sections, redaction behavior, and generic fallback behavior. Remove wording that implies all useful content belongs inside one technical disclosure.

- [ ] **Step 2: Run the complete dashboard test file.**

Run `python -m pytest -q tests/test_dashboard_custom_modals.py --tb=short`. Expected: all dashboard tests pass.

- [ ] **Step 3: Run compile and diff checks.**

Run `python -m compileall -q src tests` and `git diff --check`. Expected: exit code 0 for both.

- [ ] **Step 4: Run the full test suite with a bounded timeout.**

Run `python -m pytest -q --tb=short`. Report any timeout separately from test failures; do not claim the full suite passed unless pytest exits 0.

- [ ] **Step 5: Review final diff.**

Confirm only dashboard renderer, dashboard tests, and dashboard documentation changed for this redesign; preserve the earlier fallback fix and unrelated user work.

- [ ] **Step 6: Restart Local AI Hub and verify status.**

Restart the local service after code changes, then verify the Hub reports `success=true`, `version=3.0.0`, and `ollama_online=true`.
