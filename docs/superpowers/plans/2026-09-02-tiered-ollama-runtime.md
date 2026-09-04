# Tiered Ollama Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route fast/background and smart models to separate Ollama endpoints while serializing GPU residency so `qwen3.5:9b` can keep 32k context without competing with fast models.

**Architecture:** Keep the current user-managed runtime at `127.0.0.1:11434`. Add a Hub-owned smart sidecar at `127.0.0.1:11437` and a `TieredOllamaRuntime` facade with the existing runtime contract. The facade chooses endpoint by `ModelExecutionPolicy.tier_for()`, holds one cross-endpoint residency lock, unloads the peer endpoint, and then delegates to the selected `OllamaRuntime`.

**Tech Stack:** Python 3.11, existing `OllamaRuntime`, `AffinityScheduler`, `ModelExecutionPolicy`, urllib HTTP client, Windows process helpers, pytest.

---

### Task 1: Add disabled-by-default smart-sidecar configuration

**Files:**
- Modify: `defaults.toml`
- Modify: `config.toml`
- Modify: `docs/CONFIGURATION.md`
- Test: `tests/test_config_hardware.py`

- [ ] **Step 1: Write the failing configuration test**

```python
def test_smart_ollama_defaults_are_isolated_and_disabled(tmp_path: Path):
    config = load_config(tmp_path / "missing.toml")
    smart = config["smart_ollama"]
    assert smart["enabled"] is False
    assert smart["url"] == "http://127.0.0.1:11437"
    assert smart["model"] == config["models"]["heavy_code"]
    assert smart["num_parallel"] == 1
    assert smart["context_length"] == 32768
    assert smart["flash_attention"] is True
    assert smart["kv_cache_type"] == "q8_0"
```

- [ ] **Step 2: Run test, verify expected RED**

Run: `python -m pytest tests/test_config_hardware.py::test_smart_ollama_defaults_are_isolated_and_disabled -q`

Expected: `KeyError: 'smart_ollama'`.

- [ ] **Step 3: Add minimal defaults and user override**

Add this complete block to `defaults.toml`:

```toml
[smart_ollama]
enabled = false
url = "http://127.0.0.1:11437"
model = ""
num_parallel = 1
context_length = 32768
flash_attention = true
kv_cache_type = "q8_0"
keep_alive = "10m"
startup_timeout_seconds = 30
handoff_timeout_seconds = 10
retry_cooldown_seconds = 120
```

Add an enabled user override to `config.toml`, setting `model = "qwen3.5:9b"`. Document that port `11435` is Hub HTTP and `11436` is background runtime, so `11437` is the smart endpoint.

- [ ] **Step 4: Run configuration test, verify GREEN**

Run: `python -m pytest tests/test_config_hardware.py::test_smart_ollama_defaults_are_isolated_and_disabled -q`

Expected: `1 passed`.

### Task 2: Create smart-sidecar lifecycle with ownership-safe shutdown

**Files:**
- Create: `src/local_ai_hub/tiered_ollama.py`
- Modify: `src/local_ai_hub/ollama.py`
- Test: `tests/test_tiered_ollama_runtime.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_smart_sidecar_starts_with_isolated_endpoint_and_environment(monkeypatch, tmp_path):
    runtime = SmartOllamaSidecar(config(tmp_path, enabled=True))
    popen = Mock(return_value=FakeProcess(1234))
    monkeypatch.setattr(ollama_module.subprocess, "Popen", popen)
    monkeypatch.setattr(runtime.runtime, "is_online", lambda: True)

    assert runtime.ensure_running() is True
    env = popen.call_args.kwargs["env"]
    assert env["OLLAMA_HOST"] == "127.0.0.1:11437"
    assert env["OLLAMA_NUM_PARALLEL"] == "1"
    assert env["OLLAMA_CONTEXT_LENGTH"] == "32768"
    assert env["OLLAMA_FLASH_ATTENTION"] == "1"
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"


def test_smart_sidecar_shutdown_never_terminates_external_fast_server(monkeypatch, tmp_path):
    sidecar = SmartOllamaSidecar(config(tmp_path, enabled=True))
    sidecar._process = FakeProcess(1234)
    monkeypatch.setattr(tiered_module, "terminate_tree", Mock())

    sidecar.shutdown()

    tiered_module.terminate_tree.assert_called_once_with(1234, timeout=5.0)
```

- [ ] **Step 2: Run tests, verify RED**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py -q`

Expected: import failure for `SmartOllamaSidecar`.

- [ ] **Step 3: Implement isolated managed sidecar**

Implement `SmartOllamaSidecar` around a copied config with `server.ollama_url` set to `smart_ollama.url`. Start `ollama serve` through `hidden_run_kwargs()` with a copied environment containing the five variables asserted above. Persist only sidecar PID/state under `server.state_dir`; call `terminate_tree()` only for that tracked PID. Use one startup deadline and one cooldown timestamp; no retry loop.

- [ ] **Step 4: Run lifecycle tests, verify GREEN**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py -q`

Expected: lifecycle tests pass with no real Ollama process.

### Task 3: Add tier-aware runtime facade and VRAM handoff

**Files:**
- Modify: `src/local_ai_hub/tiered_ollama.py`
- Modify: `src/local_ai_hub/ollama.py`
- Test: `tests/test_tiered_ollama_runtime.py`

- [ ] **Step 1: Write failing routing and handoff tests**

```python
def test_smart_request_unloads_fast_endpoint_before_sidecar_request(tmp_path):
    fast = FakeRuntime(loaded=[{"name": "qwen2.5-coder:7b"}])
    smart = FakeRuntime(loaded=[])
    runtime = TieredOllamaRuntime(config(tmp_path, enabled=True), fast=fast, smart=smart)

    result = runtime.request("/api/generate", {"model": "qwen3.5:9b"})

    assert result["done"] is True
    assert fast.events == [("unload_model", "qwen2.5-coder:7b")]
    assert smart.events == [("ensure_running",), ("request", "/api/generate")]


def test_fast_request_unloads_smart_endpoint_before_fast_request(tmp_path):
    fast = FakeRuntime(loaded=[])
    smart = FakeRuntime(loaded=[{"name": "qwen3.5:9b"}])
    runtime = TieredOllamaRuntime(config(tmp_path, enabled=True), fast=fast, smart=smart)

    runtime.request("/api/generate", {"model": "qwen2.5-coder:7b"})

    assert smart.events == [("unload_model", "qwen3.5:9b")]
    assert fast.events == [("request", "/api/generate")]
```

- [ ] **Step 2: Run routing tests, verify RED**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py -q`

Expected: `TieredOllamaRuntime` missing.

- [ ] **Step 3: Implement facade contract**

Implement `TieredOllamaRuntime` methods currently consumed by `AffinityScheduler`, `IdleGPUWorker`, and status: `request`, `request_interruptible`, `prepare_model`, `unload_model`, `loaded_model_details`, `is_online`, `managed_profile_status`, and `shutdown`.

Route `smart` and `reasoning` models to `SmartOllamaSidecar.runtime`; all other tiers route to the existing runtime. Guard model preparation and requests with one `threading.RLock`. Before dispatch, unload every model reported by peer `loaded_model_details()`, poll peer details until empty with `handoff_timeout_seconds`, then dispatch. On failed unload or deadline, return a structured `error` and do not load the requested peer model.

- [ ] **Step 4: Run routing tests, verify GREEN**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py -q`

Expected: routing, ordering, and peer-empty deadline tests pass.

### Task 4: Wire facade into application and preserve existing scheduler behavior

**Files:**
- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/background_gpu.py`
- Test: `tests/test_v1_5_reliability.py`
- Test: `tests/test_tiered_ollama_runtime.py`

- [ ] **Step 1: Write failing application wiring test**

```python
def test_app_uses_tiered_runtime_only_when_smart_sidecar_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "TieredOllamaRuntime", FakeTieredRuntime)
    app = LocalAIHub(config_with_smart_sidecar(tmp_path, enabled=True))
    assert isinstance(app.runtime, FakeTieredRuntime)

    app = LocalAIHub(config_with_smart_sidecar(tmp_path, enabled=False))
    assert isinstance(app.runtime, OllamaRuntime)
```

- [ ] **Step 2: Run wiring test, verify RED**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py::test_app_uses_tiered_runtime_only_when_smart_sidecar_enabled -q`

Expected: the app always constructs `OllamaRuntime`.

- [ ] **Step 3: Implement opt-in application wiring**

In `LocalAIHub.__init__`, construct the existing `OllamaRuntime` as fast runtime. When `smart_ollama.enabled` is true, wrap it in `TieredOllamaRuntime`; otherwise keep the existing runtime object. Pass the selected runtime to `AffinityScheduler`. Keep `IdleGPUWorker` bound to its managed background runtime and make foreground preemption call the facade unload path before it grants GPU work.

- [ ] **Step 4: Run focused regression tests, verify GREEN**

Run: `python -m pytest tests/test_v1_5_reliability.py tests/test_runtime_hardening.py tests/test_tiered_ollama_runtime.py -q`

Expected: all pass.

### Task 5: Expose endpoint, handoff, failure, and ownership status

**Files:**
- Modify: `src/local_ai_hub/tiered_ollama.py`
- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/dashboard.py`
- Modify: `docs/DASHBOARD.md`
- Test: `tests/test_tiered_ollama_runtime.py`

- [ ] **Step 1: Write failing status test**

```python
def test_tiered_runtime_status_reports_endpoints_and_handoff_failure(tmp_path):
    runtime = TieredOllamaRuntime(config(tmp_path, enabled=True), fast=FakeRuntime(), smart=FakeRuntime())
    runtime._last_handoff_error = "peer still loaded"

    status = runtime.managed_profile_status()

    assert status["fast"]["url"] == "http://127.0.0.1:11434"
    assert status["smart"]["url"] == "http://127.0.0.1:11437"
    assert status["smart"]["managed"] is True
    assert status["handoff"]["last_error"] == "peer still loaded"
```

- [ ] **Step 2: Run status test, verify RED**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py::test_tiered_runtime_status_reports_endpoints_and_handoff_failure -q`

Expected: missing tiered status projection.

- [ ] **Step 3: Implement metadata-only status and dashboard projection**

Return fast/smart URLs, managed ownership, process readiness, active model, lock holder, handoff count, unload/start failures, cooldown remaining, and last error. Add the fields to `/v1/status` and dashboard runtime view. Do not include prompts, completions, source text, or environment values.

- [ ] **Step 4: Run status test, verify GREEN**

Run: `python -m pytest tests/test_tiered_ollama_runtime.py -q`

Expected: all new runtime tests pass.

### Task 6: Verify full integration and documentation

**Files:**
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/DASHBOARD.md`
- Test: `tests/test_surface_and_packaging.py`

- [ ] **Step 1: Write failing documentation/surface test**

```python
def test_default_config_and_docs_describe_opt_in_smart_sidecar():
    defaults = (ROOT / "defaults.toml").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    assert "[smart_ollama]" in defaults
    assert "127.0.0.1:11437" in docs
    assert "user-managed" in docs
```

- [ ] **Step 2: Run test, verify RED**

Run: `python -m pytest tests/test_surface_and_packaging.py::test_default_config_and_docs_describe_opt_in_smart_sidecar -q`

Expected: missing configuration and documentation content.

- [ ] **Step 3: Document activation and limits**

Document sidecar enablement, port roles (`11434` fast, `11435` Hub API, `11436` background, `11437` smart), single-GPU residency handoff, managed ownership, shutdown behavior, and how to inspect status. State that Hub never changes global Ollama variables or terminates the user-managed fast server.

- [ ] **Step 4: Run full verification through Local AI Hub command cache**

Run: `python -m compileall -q src mcp tools tests`

Expected: exit code `0`.

Run: `python -m pytest -q`

Expected: all tests pass.

Run: `python tools/selftest.py`

Expected: exit code `0`.

## Plan self-review

- Spec coverage: configuration, endpoint ownership, routing, handoff, bounded failure behavior, status, telemetry-safe projection, documentation, and regression coverage each map to a task.
- Placeholders: none.
- Type consistency: `SmartOllamaSidecar`, `TieredOllamaRuntime`, `managed_profile_status`, and `handoff_timeout_seconds` use one spelling throughout.
