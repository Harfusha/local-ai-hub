# Vision Frontend Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent review a screenshot plus prompt, optionally enriched with the current tab's live DOM and runtime evidence, then give a coder agent actionable findings and a verified frontend repair loop.

**Architecture:** Extend the existing `local_ai_task(action="vision")` path and `/api/task/vision` service. Store a versioned frontend evidence bundle in the existing artifact store, run Qwen3-VL:4B as a strict JSON visual critic, resolve repository context through `local_ai_repo`, and expose a current-tab capture bridge as a local-only browser extension. Keep screenshot-only review useful without a repository; enable repair/recheck only when code and browser evidence exist.

**Tech Stack:** Python 3.11+, stdlib dataclasses/json, existing HTTP server and SQLite `ArtifactStore`, Ollama multimodal `/api/generate`, MCP FastMCP, Chrome/Edge Manifest V3 extension, pytest, existing `local_ai_command` validation path.

**Design source:** `docs/superpowers/specs/2026-09-18-vision-frontend-review-design.md`

---

## Task 1: Establish versioned frontend-review contracts

**Files:**
- Create: `src/local_ai_hub/vision_contracts.py`
- Test: `tests/test_vision_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests for `FrontendReviewBundle.from_payload`, `parse_vision_result`, and `build_coder_packet`:

```python
def test_bundle_requires_screenshot_and_preserves_full_dom() -> None:
    bundle = FrontendReviewBundle.from_payload({
        "schema_version": "1",
        "source": "current_tab",
        "prompt": "Why is the CTA hidden?",
        "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
        "dom": {"artifact_id": "art_dom", "redaction": "none"},
    })
    assert bundle.screenshot_artifact_id == "art_img"
    assert bundle.dom_redaction == "none"

def test_vision_result_accepts_findings() -> None:
    result = parse_vision_result('{"summary":"bad CTA","findings":[{"id":"f1",'
        '"severity":"high","category":"layout","problem":"below fold","confidence":0.91}]}')
    assert result.findings[0].finding_id == "f1"

def test_coder_packet_keeps_only_referenced_dom() -> None:
    packet = build_coder_packet(
        prompt="Fix mobile checkout",
        findings=[{"id": "f1", "element_ids": ["el-42"]}],
        dom={"elements": [{"element_id": "el-42"}, {"element_id": "other"}]},
        repo_context={"files": ["src/Checkout.tsx"]},
    )
    assert packet["dom"]["elements"] == [{"element_id": "el-42"}]
```

- [ ] **Step 2: Run the focused tests and confirm failure**

```powershell
python -m pytest -q tests/test_vision_contracts.py
```

Expected: collection failure because `vision_contracts.py` does not exist.

- [ ] **Step 3: Implement the contract module**

Use frozen dataclasses and bounded parsing:

```python
SEVERITIES = {"blocker", "high", "medium", "low", "info"}
CATEGORIES = {"layout", "responsive", "accessibility", "interaction", "visual-regression", "runtime"}

@dataclass(frozen=True)
class VisionFinding:
    finding_id: str
    severity: str
    category: str
    problem: str
    confidence: float
    element_ids: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    evidence: tuple[str, ...] = ()
    likely_cause: str = ""
    fix_hint: str = ""
    needs_runtime_check: bool = True

@dataclass(frozen=True)
class FrontendReviewBundle:
    schema_version: str
    source: str
    prompt: str
    screenshot_artifact_id: str
    screenshot_mime_type: str
    dom_artifact_id: str = ""
    accessibility_artifact_id: str = ""
    computed_styles_artifact_id: str = ""
    runtime_artifact_id: str = ""
    viewport: dict[str, int | float] = field(default_factory=dict)
    page: dict[str, str] = field(default_factory=dict)
    dom_redaction: str = "none"
```

`parse_vision_result` accepts JSON or fenced JSON, validates required fields, clamps confidence to `0.0..1.0`, rejects unknown severity/category values, and returns a terminal structured error for malformed model output. `build_coder_packet` projects only finding-referenced DOM elements plus ancestors and bounded runtime context.

- [ ] **Step 4: Run focused tests**

```powershell
python -m pytest -q tests/test_vision_contracts.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/local_ai_hub/vision_contracts.py tests/test_vision_contracts.py
git commit -m "feat: add frontend vision review contracts"
```

---

## Task 2: Add Qwen3-VL:4B routing and strict vision output

**Files:**
- Modify: `src/local_ai_hub/services.py:vision`
- Modify: `src/local_ai_hub/defaults.toml:[models]`
- Modify: `config.toml.example:[models]`
- Modify: `src/local_ai_hub/features.py`
- Modify: `src/local_ai_hub/model_policy.py`
- Create: `tests/test_vision_service.py`
- Modify: `tests/test_uncovered_domains.py`

- [ ] **Step 1: Write failing routing tests**

Cover default model, JSON format, structured findings, and missing-model failure:

```python
def test_vision_defaults_to_configured_qwen_model(tmp_path, services_factory):
    services, runtime = services_factory(tmp_path, models={"vision": "qwen3-vl:4b"})
    result = services.vision({"image": str(tmp_path / "shot.png"), "prompt": "Review UI"}, "t")
    assert result["model"] == "qwen3-vl:4b"
    assert runtime.request.call_args.args[1]["format"] == "json"

def test_vision_returns_structured_findings(tmp_path, services_factory):
    services, runtime = services_factory(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {"response": '{"summary":"bad CTA","findings":[]}'}
    result = services.vision({"image": str(tmp_path / "shot.png"), "prompt": "Review UI"}, "t")
    assert result["review"]["summary"] == "bad CTA"

def test_vision_missing_model_is_explicitly_unsupported(tmp_path, services_factory):
    services, _ = services_factory(tmp_path, models={"vision": ""})
    result = services.vision({"image": str(tmp_path / "shot.png")}, "t")
    assert result["success"] is False
    assert result["unsupported"] is True
```

- [ ] **Step 2: Run tests and confirm failure**

```powershell
python -m pytest -q tests/test_uncovered_domains.py tests/test_vision_service.py
```

Expected: structured-output assertions fail against the current free-text implementation.

- [ ] **Step 3: Configure the model role**

Add:

```toml
[models]
vision = "qwen3-vl:4b"
```

Add `vision_model` to `FeatureSet`, expose it in capabilities/status, and keep it separate from coder/reasoning roles. Update `ModelExecutionPolicy.tier_for` with a single-slot `vision` tier and conservative image context. Preserve resident-model and VRAM handoff behavior.

- [ ] **Step 4: Upgrade `LocalAIServices.vision`**

Keep `image`, `image_path`, and base64 compatibility. Add `image_artifact_id`, `bundle_artifact_id`, and optional `json_schema`. Send Ollama `images`, prompt, `format: "json"`, and schema instructions. Return parsed `review` plus an artifact reference for raw output. Invalid JSON returns `success=False`, `terminal=True`, `retryable=False`, and the raw-output artifact ID.

- [ ] **Step 5: Verify**

```powershell
python -m pytest -q tests/test_uncovered_domains.py tests/test_vision_service.py tests/test_model_policy.py
```

Expected: PASS; existing legacy response field remains compatible.

- [ ] **Step 6: Commit**

```powershell
git add src/local_ai_hub/services.py src/local_ai_hub/features.py src/local_ai_hub/model_policy.py src/local_ai_hub/defaults.toml config.toml.example tests/test_uncovered_domains.py tests/test_vision_service.py
git commit -m "feat: route frontend vision reviews to qwen3-vl"
```

---

## Task 3: Extend artifact transport for images and review bundles

**Files:**
- Modify: `src/local_ai_hub/artifacts.py`
- Modify: `src/local_ai_hub/http_server.py:/api/artifact/get`
- Modify: `src/local_ai_hub/mcp_server.py:local_ai_artifact`
- Modify: `src/local_ai_hub/services.py`
- Modify: `tests/test_artifacts.py`
- Create: `tests/test_vision_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

```python
def test_binary_image_artifact_round_trips_as_data_url(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(b"\x89PNG\r\n", "tenant", "vision-image", "image/png")
    result = store.get_binary(artifact_id)
    assert result["mime_type"] == "image/png"
    assert result["data_base64"]

def test_review_bundle_artifact_is_addressable(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_json({"schema_version": "1", "dom": {"elements": []}}, "t", "vision-bundle")
    assert store.get(artifact_id, section="json:dom")["success"] is True
```

- [ ] **Step 2: Implement additive binary storage**

Extend the artifact schema with `mime_type`, `encoding`, and `blob` columns while preserving existing text rows. Add:

```python
def put_bytes(self, data: bytes, tenant: str, kind: str, mime_type: str) -> str: ...
def put_json(self, value: dict[str, Any], tenant: str, kind: str) -> str: ...
def get_binary(self, artifact_id: str) -> dict[str, Any]: ...
```

Reject non-image MIME types for vision images, cap bytes using config, and never inline binary contents in MCP responses.

- [ ] **Step 3: Add bounded retrieval**

Keep `local_ai_artifact` retrieval bounded. If a public `put` action would overgrow the schema, keep writes internal to `/api/vision/review` and expose only artifact IDs. Existing `get` and evidence slicing must remain unchanged.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest -q tests/test_artifacts.py tests/test_vision_artifacts.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/local_ai_hub/artifacts.py src/local_ai_hub/http_server.py src/local_ai_hub/mcp_server.py src/local_ai_hub/services.py tests/test_artifacts.py tests/test_vision_artifacts.py
git commit -m "feat: store bounded vision artifacts"
```

---

## Task 4: Implement DOM-aware review packets and coder context

**Files:**
- Create: `src/local_ai_hub/frontend_review.py`
- Modify: `src/local_ai_hub/services.py:vision`
- Modify: `src/local_ai_hub/mcp_server.py:local_ai_task`
- Modify: `src/local_ai_hub/http_server.py:/api/task/vision`
- Modify: `src/local_ai_hub/generator.py`
- Create: `tests/test_frontend_review.py`
- Create: `tests/test_frontend_coder_context.py`
- Modify: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Write failing bundle tests**

```python
def test_build_model_context_includes_screenshot_dom_and_prompt():
    context = build_model_context(
        prompt="Why is the button missing?",
        screenshot_data_url="data:image/png;base64,AA==",
        dom={"elements": [{"element_id": "el-1", "tag": "button"}]},
        accessibility={"role": "button"},
        computed_styles={"el-1": {"display": "none"}},
        viewport={"width": 390, "height": 844},
    )
    assert context.prompt == "Why is the button missing?"
    assert context.dom["elements"][0]["element_id"] == "el-1"

def test_full_dom_is_not_semantically_redacted():
    projected = project_live_dom({"html": "<main>user@example.test</main>"}, max_chars=10_000)
    assert "user@example.test" in projected["html"]

def test_dom_limit_is_explicit():
    projected = project_live_dom({"html": "x" * 20}, max_chars=10)
    assert projected["truncated"] is True
    assert projected["original_chars"] == 20
```

- [ ] **Step 2: Implement focused frontend-review helpers**

Create:

```python
def project_live_dom(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]: ...
def build_model_context(*, prompt: str, screenshot_data_url: str, dom: dict[str, Any], accessibility: dict[str, Any], computed_styles: dict[str, Any], viewport: dict[str, Any], runtime: dict[str, Any] | None = None) -> FrontendModelContext: ...
def build_coder_context(review: dict[str, Any], bundle: dict[str, Any], repo_context: dict[str, Any] | None = None) -> dict[str, Any]: ...
```

Full DOM is not semantically redacted. Only the configured size/context bound applies. Include `truncated`, `original_chars`, and `limit_chars` when bounded. The model prompt requires JSON, stable `element_id`/`bbox` references, observed-vs-hypothesized separation, and explicit uncertainty.

- [ ] **Step 3: Extend the existing vision action**

Preserve `candidate` and `context`. Add optional `bundle_artifact_id`, `image_artifact_id`, `source`, `root`, `cloud_fallback`, and `json_schema` forwarding fields to `local_ai_task(action="vision")`. Do not add a new public MCP tool.

- [ ] **Step 4: Assemble repository context**

When `root` is supplied and the prompt requests a fix, call the existing repository worker with finding IDs, selectors, component hints, and the user prompt. Return relevant files/symbols/tests only; keep detailed evidence artifact-backed.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest -q tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_mcp_agent_routing.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/local_ai_hub/frontend_review.py src/local_ai_hub/services.py src/local_ai_hub/mcp_server.py src/local_ai_hub/http_server.py src/local_ai_hub/generator.py tests/test_frontend_review.py tests/test_frontend_coder_context.py tests/test_mcp_agent_routing.py
git commit -m "feat: add dom-aware frontend review packets"
```

---

## Task 5: Add current-tab browser bridge

**Files:**
- Create: `browser_bridge/manifest.json`
- Create: `browser_bridge/background.js`
- Create: `browser_bridge/capture.js`
- Create: `browser_bridge/README.md`
- Create: `src/local_ai_hub/browser_bridge.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/config.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Create: `tests/test_browser_bridge.py`
- Create: `tests/test_http_vision_routes.py`

- [ ] **Step 1: Write protocol tests**

Test capability issuance/consumption, origin binding, one-use behavior, payload limits, and rejection of cookies/authorization/request bodies:

```python
def test_capture_capability_is_single_use():
    capability = issue_capture_capability(config, origin="http://127.0.0.1:11435")
    assert validate_capture_request(capability, {"origin": config.allowed_origins[0]})["success"]
    assert not validate_capture_request(capability, {"origin": config.allowed_origins[0]})["success"]

def test_capture_rejects_credentials_and_network_bodies():
    result = validate_capture_payload({"cookies": [], "authorization": "x", "request_bodies": [{}]})
    assert result["success"] is False
    assert result["error"] == "credential-bearing capture fields are not allowed"
```

- [ ] **Step 2: Implement local capability protocol**

Use a short-lived, one-use capability bound to authenticated tenant and extension origin. Validate size, MIME type, viewport bounds, and required screenshot. Store screenshot, DOM, accessibility, styles, runtime JSON, and one bundle artifact.

Do not persist cookies, password values, authorization headers, or request bodies. Do not silently capture a background tab.

- [ ] **Step 3: Implement the Manifest V3 extension**

Request minimum permissions for an explicit capture gesture. Collect:

```javascript
{
  screenshot,
  url: location.href,
  title: document.title,
  dom: document.documentElement.outerHTML,
  accessibility: collectAccessibleProjection(),
  computed_styles: collectVisibleComputedStyles(),
  viewport: { width: innerWidth, height: innerHeight, device_scale_factor: devicePixelRatio }
}
```

Send only to the configured loopback Hub endpoint with the one-use capability. Never read cookies or password input values.

- [ ] **Step 4: Add authenticated HTTP routes**

Add:

```text
POST /api/browser/capability
POST /api/browser/capture
POST /api/vision/review
```

`/api/vision/review` accepts an image or `bundle_artifact_id`, and returns review artifact ID, parsed findings, model provenance, and bounded errors.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest -q tests/test_browser_bridge.py tests/test_http_vision_routes.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add browser_bridge src/local_ai_hub/browser_bridge.py src/local_ai_hub/http_server.py src/local_ai_hub/config.py src/local_ai_hub/defaults.toml tests/test_browser_bridge.py tests/test_http_vision_routes.py
git commit -m "feat: capture current browser tab for vision review"
```

---

## Task 6: Connect findings to coder-agent repair loop

**Files:**
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/frontend_review.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/generator.py`
- Create: `tests/test_frontend_coder_context.py`
- Modify: `tests/test_agent_context.py`

- [ ] **Step 1: Write failing handoff tests**

Verify the coder packet includes prompt, findings, referenced DOM, artifact IDs, repository candidates, tests, and uncertainty. Verify unrelated files are absent.

- [ ] **Step 2: Implement handoff shape**

Return:

```json
{
  "prompt": "Fix mobile checkout",
  "findings": [],
  "evidence": {
    "screenshot_artifact_id": "...",
    "dom_artifact_id": "...",
    "report_artifact_id": "..."
  },
  "repo_context": {"files": [], "symbols": [], "tests": []},
  "uncertainty": []
}
```

Update generated agent policy with: collect evidence, run vision critic, obtain indexed repository context, fix only supported findings, run browser/test verification. Local vision remains advisory and cannot claim edits.

- [ ] **Step 3: Add Agent OS checkpoints**

For closed repair requests use checkpoints `capture`, `vision_review`, `coder_context`, `edit`, and `recheck`. Attach a verification receipt only after browser probe and relevant tests pass.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest -q tests/test_frontend_coder_context.py tests/test_agent_context.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/local_ai_hub/services.py src/local_ai_hub/frontend_review.py src/local_ai_hub/mcp_server.py src/local_ai_hub/generator.py tests/test_frontend_coder_context.py tests/test_agent_context.py
git commit -m "feat: hand vision findings to frontend coder agents"
```

---

## Task 7: Add dashboard and trace presentation

**Files:**
- Modify: `src/local_ai_hub/dashboard.py`
- Create: `tests/test_dashboard_vision_review.py`
- Modify: `tests/test_dashboard_custom_modals.py`
- Modify: `docs/DASHBOARD.md`

- [ ] **Step 1: Write failing UI contract tests**

Require screenshot upload, prompt, current-tab capture state, permission error, model provenance, summary-first findings, expandable screenshot/DOM/a11y/raw output, and finding IDs usable by repair.

- [ ] **Step 2: Implement minimal dashboard flow**

Reuse existing modal, safe escaping, bounded HTML, polling, and trace renderers. Initial render contains only compact review projection; technical artifacts load on demand.

- [ ] **Step 3: Run tests**

```powershell
python -m pytest -q tests/test_dashboard_vision_review.py tests/test_dashboard_custom_modals.py
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add src/local_ai_hub/dashboard.py tests/test_dashboard_vision_review.py tests/test_dashboard_custom_modals.py docs/DASHBOARD.md
git commit -m "feat: show frontend vision reviews in dashboard"
```

---

## Task 8: Add explicit cloud fallback

**Files:**
- Modify: `src/local_ai_hub/frontend_review.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/config.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Modify: `config.toml.example`
- Create: `tests/test_vision_cloud_fallback.py`
- Modify: `docs/CONFIGURATION.md`

- [ ] **Step 1: Write failing consent tests**

Cloud fallback fails closed without per-request consent. Successful cloud output carries `provider="cloud"` and `consent=true`. Local mode never calls the cloud client.

- [ ] **Step 2: Implement opt-in fallback**

Add `cloud_fallback=false` by default. Accept `allow_cloud=true` only in the request. Record provider provenance. Never copy cookies, authorization headers, or network bodies into cloud input.

- [ ] **Step 3: Run tests and commit**

```powershell
python -m pytest -q tests/test_vision_cloud_fallback.py
git add src/local_ai_hub/frontend_review.py src/local_ai_hub/services.py src/local_ai_hub/config.py src/local_ai_hub/defaults.toml config.toml.example tests/test_vision_cloud_fallback.py docs/CONFIGURATION.md
git commit -m "feat: add explicit cloud vision fallback"
```

Expected: PASS.

---

## Task 9: End-to-end fixture and release verification

**Files:**
- Create: `tests/fixtures/frontend_review/index.html`
- Create: `tests/fixtures/frontend_review/app.css`
- Create: `tests/test_frontend_review_e2e.py`
- Modify: `docs/TESTING.md`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] **Step 1: Create deterministic broken fixture**

Include mobile CTA below fold, contrast failure, inaccessible icon button, one console error, and a fake authenticated state with no real credentials.

- [ ] **Step 2: Write the end-to-end test**

Start fixture server, submit mocked screenshot/bundle, assert finding-to-DOM mapping, assert coder packet contains only relevant fixture files, apply fixture repair, run browser recheck, and assert finding cleared.

- [ ] **Step 3: Run focused and full gates through `local_ai_command`**

```text
local_ai_command(action="run", cwd="C:\\Users\\Adam\\.local-ai-hub", command="python -m pytest -q tests/test_vision_contracts.py tests/test_vision_service.py tests/test_vision_artifacts.py tests/test_frontend_review.py tests/test_browser_bridge.py tests/test_http_vision_routes.py tests/test_frontend_coder_context.py tests/test_frontend_review_e2e.py")
```

Then run:

```text
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Expected: all pass. If the Hub command broker returns terminal non-retryable failure, run one bounded native fallback and record it.

- [ ] **Step 4: Run indexed review/security checks**

```text
local_ai_repo(action="review_diff", root="C:\\Users\\Adam\\.local-ai-hub")
local_ai_repo(action="security_audit", root="C:\\Users\\Adam\\.local-ai-hub")
```

Review extension permissions, capability tokens, artifact TTLs, image limits, cloud consent, path handling, and credential/network-body capture.

- [ ] **Step 5: Commit fixture and documentation**

```powershell
git add tests/fixtures/frontend_review tests/test_frontend_review_e2e.py docs/TESTING.md docs/TROUBLESHOOTING.md
git commit -m "test: verify end-to-end frontend vision review"
```

---

## Execution order and stop points

1. Tasks 1–2: working screenshot-only local vision review.
2. Tasks 3–4: artifact-backed DOM-aware review and coder context.
3. Task 5: current-tab capture behind login.
4. Tasks 6–7: agent repair loop and dashboard.
5. Task 8: optional cloud policy.
6. Task 9: release gate.

Do not start the extension before manual screenshot review and strict JSON contracts pass. Do not enable cloud fallback by default. Do not claim completion until capture, analysis, coder context, repair, and recheck pass against the fixture.

## Self-review

- Spec coverage: screenshot upload, full live DOM, accessibility, computed styles, Qwen3-VL:4B, current-tab capture, login-preserving flow, coder handoff, repair loop, cloud opt-in, failures, tests, and release gates map to tasks.
- Placeholder scan: no TBD/TODO implementation step; deferred Playwright is explicitly scoped out of first implementation.
- Type consistency: `FrontendReviewBundle`, `VisionFinding`, `parse_vision_result`, `build_coder_packet`, `project_live_dom`, and `build_model_context` are introduced before reuse.


