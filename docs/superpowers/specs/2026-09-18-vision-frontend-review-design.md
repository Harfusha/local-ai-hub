# Vision Frontend Review Design

## Goal

Let a user send a screenshot and a prompt, or explicitly capture the current browser tab, and receive an actionable frontend review. The review combines visual evidence, the live DOM, accessibility state, runtime errors, and repository context. A local vision model performs visual inspection; a coding agent turns the findings into code changes and verification steps.

## Approved scope

The first release has two input paths:

1. Manual screenshot upload with a user prompt.
2. Explicit capture of the current browser tab, including pages behind an existing login or multi-step flow.

The browser capture must never navigate, submit forms, read passwords, or inspect cookies without a separate explicit future capability. A user gesture starts every capture. A controlled Chromium/Playwright runner is deferred to a later phase for reproducible public or test environments.

DOM is not semantically redacted. The system keeps the full live DOM snapshot, subject to bounded payload size, context, and persistence limits. Browser credentials, cookies, authorization headers, and network bodies are separate channels and are not included in the DOM contract.

## Architecture

The feature is an evidence pipeline behind the existing compact MCP surface. It does not add a large collection of public MCP tools.

```text
manual image or current-tab capture
        |
        v
vision evidence bundle
  screenshot + live DOM + a11y + styles + viewport + runtime errors
        |
        +--> local vision analysis: Qwen3-VL:4B
        |
        +--> repository context: local_ai_repo
        |
        v
structured frontend findings
        |
        v
coder context packet for Luna or another coding agent
        |
        v
local_ai_command/browser recheck
```

Existing tools remain the integration points:

- `local_ai_artifact`: image, DOM, accessibility, and report evidence.
- `local_ai_task(action="vision")`: local vision analysis.
- `local_ai_repo`: relevant component/style/test context.
- `local_ai_task(action="reason"|"review")`: combine visual findings with code evidence when needed.
- `local_ai_work`: optional closed end-to-end repair flow.
- `local_ai_command`: browser probe, frontend tests, lint, typecheck, and build.
- `local_ai_coord`: leases, checkpoints, receipts, and reusable findings.

## Evidence contract

Every review receives a versioned `frontend_review_bundle`:

```json
{
  "schema_version": "1",
  "source": "upload|current_tab",
  "prompt": "User question",
  "screenshot": {"artifact_id": "...", "mime_type": "image/png"},
  "dom": {"artifact_id": "...", "format": "live-dom", "redaction": "none"},
  "accessibility": {"artifact_id": "..."},
  "computed_styles": {"artifact_id": "...", "scope": "visible-elements"},
  "viewport": {"width": 390, "height": 844, "device_scale_factor": 1},
  "runtime": {"console_artifact_id": "...", "network_artifact_id": "..."},
  "page": {"url": "...", "title": "..."}
}
```

The browser bridge adds stable `element_id` values to live elements and includes bounding boxes, selectors, tag/role/text, ancestors, visibility, and computed layout properties. The mapping lets the vision model point to an element without guessing a source-file name.

The vision result is strict JSON:

```json
{
  "schema_version": "1",
  "summary": "...",
  "findings": [
    {
      "id": "finding-1",
      "severity": "blocker|high|medium|low|info",
      "category": "layout|responsive|accessibility|interaction|visual-regression|runtime",
      "element_ids": ["el-42"],
      "bbox": [312, 744, 280, 48],
      "problem": "...",
      "evidence": ["artifact:...", "dom:el-42"],
      "likely_cause": "...",
      "fix_hint": "...",
      "confidence": 0.0,
      "needs_runtime_check": true
    }
  ],
  "unknowns": [],
  "recommended_checks": []
}
```

The coder context packet contains the prompt, findings, referenced DOM slices, relevant repository symbols/files, and required checks. It does not ask the coder model to reinterpret the entire screenshot from scratch.

## Manual screenshot flow

The manual path is the guaranteed fallback and first vertical slice.

1. Agent or dashboard accepts one image and a prompt.
2. Hub stores the image as a bounded artifact and creates a review bundle.
3. Qwen3-VL:4B receives the image plus the user question and returns strict findings.
4. Hub resolves referenced selectors/element IDs when DOM is available; for upload-only reviews, findings can remain region-based.
5. `local_ai_repo` finds relevant code only when a repository/workspace is supplied.
6. Agent returns findings, likely files, suggested fixes, and verification commands.

Upload-only review must work even without a repository. It reports visual facts and questions that require DOM or code evidence instead of inventing selectors.

## Current-tab browser bridge

Use a local browser bridge with explicit user activation. The bridge should support Chrome and Edge first and expose one-time, scoped capture capabilities to the Hub.

Capture sequence:

1. User clicks `Capture current tab` in the extension or dashboard.
2. Bridge captures visible screenshot and current URL/title.
3. Bridge collects live DOM, accessibility tree, viewport, visible computed styles, console entries, and performance/network error summaries.
4. Bridge assigns stable element IDs and returns artifact references to the Hub.
5. Hub invokes the local vision review and coder-context pipeline.

The bridge must show the target origin and capture timestamp. It must reject background or unapproved tabs. It must not expose cookies, password fields' values, authorization headers, or request bodies. Login state stays in the browser.

The bridge transport should be local-only, authenticated with a short-lived capability token, bounded by request size/time, and invalidated after one capture. Extension/DevTools implementation is preferred over requiring the user's existing browser to restart with a remote-debugging flag.

## Model routing

Qwen3-VL:4B is the default local visual critic. It is not the coder of record. The Hub must detect vision capability before dispatch and return an actionable unavailable-model error instead of silently sending an image to a text-only model.

Recommended roles:

- `vision`: `qwen3-vl:4b`.
- `frontend_critic`: same vision model with strict review schema.
- `coder`: existing configured cloud/local coding agent.
- `cloud_vision_fallback`: disabled by default; enabled per request.

Only one large model should occupy constrained VRAM at a time. Model switching must use existing Hub-managed runtime routing, not ad-hoc direct model calls. Cloud fallback receives the screenshot only after explicit user consent and is marked in the review provenance.

## Agent experience

The agent should support three commands conceptually:

- `review this screenshot: ...`
- `capture current tab and review: ...`
- `fix finding <id>`

The response has a short human summary first, then findings, affected files, suggested changes, and verification. Raw DOM, trace events, model prompts, and full artifacts remain expandable technical detail, consistent with existing trace presentation patterns.

## Failure handling

- Vision model unavailable: offer DOM/a11y/runtime-only review or cloud opt-in.
- Screenshot present, DOM absent: return region-based findings with lower confidence.
- DOM too large: keep complete artifact, send bounded projected slices to the model, and state the truncation explicitly.
- Current tab capture denied: keep manual upload path available.
- Login or cross-origin restrictions: capture only data permitted by the browser bridge; never bypass them.
- Invalid model JSON: run one bounded repair/finalization pass, then return raw advisory output marked unstructured.
- Coder cannot map finding to code: report unknown and ask for repository/path context; never invent a file.

## Phases

### Phase 1 — Manual screenshot vertical slice

Deliver image artifact input, prompt handling, Qwen3-VL:4B routing, strict findings schema, report rendering, and tests. No browser bridge dependency.

### Phase 2 — DOM-aware review

Add live-DOM bundle ingestion, stable element IDs, accessibility/computed-style payloads, bounded projection, and coder context assembly. Validate screenshot-to-element references with fixtures.

### Phase 3 — Current-tab capture

Build the local extension/bridge, one-time capability tokens, explicit user gesture, capture permissions, and end-to-end current-tab tests against a local fixture page with a simulated login state.

### Phase 4 — Repair loop

Connect findings to `local_ai_repo`, Luna/coder context, affected-test selection, browser recheck, and `fix finding <id>`. Add Agent OS checkpoints and verification receipts.

### Phase 5 — Optional cloud fallback and controlled browser

Add explicit cloud image consent/provenance and later a Playwright-controlled browser mode for public/test pages. Keep both paths independent from current-tab login capture.

## Acceptance criteria

The feature is complete when:

1. A user can submit PNG/JPEG + prompt and receive structured findings.
2. Qwen3-VL:4B is selected when available; text-only fallback never receives an image silently.
3. A current logged-in tab can be captured after one explicit user gesture without re-login.
4. Review includes screenshot, full live DOM artifact, accessibility tree, viewport, and visible computed styles when browser capture is used.
5. Findings reference stable DOM element IDs or image regions, severity, evidence, confidence, and next checks.
6. Coder context includes findings plus relevant repository context, not an unbounded raw repository dump.
7. A finding can be rechecked after a code change.
8. Credentials, cookies, authorization headers, and network bodies never enter the review bundle.
9. Local-only mode works without cloud access.
10. All new paths have unit, contract, integration, and failure-mode tests; existing release checks remain green.

## Out of scope for first implementation

- Automatic login or form submission.
- Full browser control of arbitrary user tabs.
- Pixel-perfect visual diff engine.
- Automatic code edits without coder-agent/user approval.
- Semantic DOM redaction; explicitly excluded by the approved design.
