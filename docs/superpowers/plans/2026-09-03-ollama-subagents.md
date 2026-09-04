# Ollama Advisory Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add named, advisory-only Ollama subagent profiles that use Local AI Hub tooling directly for repository evidence.

**Architecture:** Extend the existing compact `local_ai_task` and `local_ai_repo` MCP tools with an optional profile selector. A small profile catalog resolves role, model, language contract, budgets, and read-only tool allowlists; the existing `ToolAwareLocalAgent`, cache, scheduler, async jobs, evidence, and telemetry remain the execution infrastructure. No profile receives command, write, worktree, or external-provider capabilities.

**Tech Stack:** Python 3.11+, FastMCP, TOML configuration, Ollama `/api/chat`, existing Hub cache/index/RAG/evidence services, pytest.

---

## File map

- Create `src/local_ai_hub/ollama_subagents.py`: immutable profile definitions, aliases, configuration parsing, model selection, language-aware system contract, and read-only tool policy.
- Modify `src/local_ai_hub/tool_agent.py`: consume profile policy, enforce role allowlists, include profile/language/advisory metadata, and keep all tool execution read-only.
- Modify `src/local_ai_hub/services.py`: resolve named profiles for non-repository delegation, route repository profiles into `ToolAwareLocalAgent`, and preserve existing fallback/cache/telemetry behavior.
- Modify `src/local_ai_hub/mcp_server.py`: add optional `profile`, `root`, and `workspace` parameters without adding an MCP tool.
- Modify `src/local_ai_hub/config.py`: validate profile limits and profile names without rejecting extensible user configuration.
- Modify `src/local_ai_hub/defaults.toml`: define three profiles using the installed `qwen2.5-coder:7b` model and conservative limits.
- Modify `skills/local-ai-orchestrator/SKILL.md`: document profile triggers and the mandatory Hub-tooling contract for Ollama subagents.
- Create `tests/test_ollama_subagents.py`: profile, safety, routing, language, fallback, and compatibility tests.
- Modify `tests/test_mcp_agent_routing.py` and `tests/test_pipeline.py`: preserve the existing MCP action surface and pipeline role behavior while covering profile metadata.

### Task 1: Add profile catalog and configuration contract

**Files:**
- Create: `src/local_ai_hub/ollama_subagents.py`
- Modify: `src/local_ai_hub/config.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Test: `tests/test_ollama_subagents.py`

- [ ] **Step 1: Write failing profile tests**

```python
from local_ai_hub.ollama_subagents import OllamaSubagentCatalog


def test_default_profiles_are_advisory_and_use_fast_model():
    catalog = OllamaSubagentCatalog({
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "ollama_subagents": {
            "enabled": True,
            "profiles": {
                "qwen-explorer": {"model": "qwen2.5-coder:7b", "role": "explorer"},
                "qwen-drafter": {"model": "qwen2.5-coder:7b", "role": "drafter"},
                "qwen-critic": {"model": "qwen2.5-coder:7b", "role": "critic"},
            },
        },
    })

    assert catalog.resolve("qwen-explorer").role == "explorer"
    assert catalog.resolve("qwen-drafter").model == "qwen2.5-coder:7b"
    assert catalog.resolve("qwen-critic").advisory_only is True


def test_aliases_and_unknown_profiles_are_deterministic():
    catalog = OllamaSubagentCatalog({"models": {"fast_code": "qwen2.5-coder:7b"}})

    assert catalog.resolve("explorer").name == "qwen-explorer"
    try:
        catalog.resolve("writer")
    except ValueError as exc:
        assert "qwen-explorer" in str(exc)
    else:
        raise AssertionError("unknown profile must fail")


def test_model_resolution_does_not_select_unavailable_model():
    catalog = OllamaSubagentCatalog({
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "ollama_subagents": {"profiles": {"qwen-explorer": {"model": "missing:99b"}}},
    })

    resolved = catalog.resolve("qwen-explorer", available_models={"qwen2.5-coder:7b"})
    assert resolved.model == "qwen2.5-coder:7b"
    assert resolved.model_fallback is True


def test_profile_tool_allowlist_excludes_mutation_and_commands():
    catalog = OllamaSubagentCatalog({"models": {"fast_code": "qwen2.5-coder:7b"}})

    for name in ("qwen-explorer", "qwen-drafter", "qwen-critic"):
        profile = catalog.resolve(name)
        assert "file_slice" in profile.tools
        assert "local_ai_command" not in profile.tools
        assert "write_file" not in profile.tools
        assert profile.advisory_only is True
```

- [ ] **Step 2: Run focused tests and verify they fail for the missing catalog**

Run: `python -m pytest tests/test_ollama_subagents.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'local_ai_hub.ollama_subagents'`.

- [ ] **Step 3: Implement the catalog**

Define:

```python
@dataclass(frozen=True)
class OllamaSubagentProfile:
    name: str
    role: str
    model: str
    tools: tuple[str, ...]
    max_steps: int
    max_tool_calls: int
    max_tokens: int
    temperature: float
    advisory_only: bool = True
    model_fallback: bool = False


class OllamaSubagentCatalog:
    PROFILE_ALIASES = {"explorer": "qwen-explorer", "drafter": "qwen-drafter", "critic": "qwen-critic"}
    READ_ONLY_TOOLS = (
        "preprocessed_context", "deterministic_facts", "code_index", "semantic_symbols",
        "code_graph", "repo_search", "rag_search", "evidence_get", "file_slice",
    )

    def __init__(self, config: dict[str, Any]):
        self.config = config
        section = config.get("ollama_subagents", {})
        self.enabled = bool(section.get("enabled", True))
        self.default_profile = str(section.get("default_profile", "qwen-explorer"))
        self.language = str(section.get("language", "match_input"))
        self.raw_profiles = section.get("profiles", {}) if isinstance(section.get("profiles", {}), dict) else {}

    def resolve(self, name: str, available_models: set[str] | None = None) -> OllamaSubagentProfile:
        canonical = self.PROFILE_ALIASES.get(str(name).strip().lower(), str(name).strip().lower())
        if canonical not in {"qwen-explorer", "qwen-drafter", "qwen-critic"}:
            raise ValueError("unknown Ollama subagent profile; valid profiles: qwen-explorer, qwen-drafter, qwen-critic")
        raw = self.raw_profiles.get(canonical, {})
        if not isinstance(raw, dict):
            raw = {}
        default_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:7b"))
        requested_model = str(raw.get("model", default_model))
        model = requested_model
        model_fallback = False
        if available_models is not None and requested_model not in available_models:
            model = default_model if default_model in available_models else requested_model
            model_fallback = model != requested_model
        role = str(raw.get("role", canonical.removeprefix("qwen-")))
        return OllamaSubagentProfile(
            name=canonical, role=role, model=model, tools=self.READ_ONLY_TOOLS,
            max_steps=max(1, min(int(raw.get("max_steps", 3)), 8)),
            max_tool_calls=max(1, min(int(raw.get("max_tool_calls", 6)), 16)),
            max_tokens=max(64, min(int(raw.get("max_tokens", 800)), 2400)),
            temperature=max(0.0, min(float(raw.get("temperature", 0.05)), 1.0)),
            model_fallback=model_fallback,
        )

    def system_contract(self, profile: OllamaSubagentProfile, task: str) -> str:
        return (
            f"You are {profile.name}, a local Ollama {profile.role} subagent inside Local AI Hub. "
            "ADVISORY_ONLY: never edit files, execute commands, create worktrees, or claim that a proposal was applied. "
            "Use Local AI Hub read-only tooling directly: preprocessed context, deterministic facts, code index, "
            "semantic symbols, code graph, repository search, RAG, evidence IDs, and bounded file slices. "
            "Start with the cheapest evidence path. Respond in the same language as TASK while preserving paths, "
            "identifiers, code, line numbers, errors, numbers, and uncertainty exactly. "
            f"Return compact structured output with profile={profile.name}, advisory_only=true."
        )
```

Add explicit profile defaults to `[ollama_subagents]` and the three nested profile tables in `src/local_ai_hub/defaults.toml`. Extend `validate_config` numeric checks for the profile limits while retaining unknown profile keys as extensible data.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_ollama_subagents.py -q`

Expected: PASS.

### Task 2: Connect profiles to the read-only Hub tool loop

**Files:**
- Modify: `src/local_ai_hub/tool_agent.py`
- Test: `tests/test_ollama_subagents.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tool-loop tests**

```python
def test_profile_tool_loop_uses_only_hub_read_tools(agent_factory):
    agent = agent_factory()
    profile = agent.profile_catalog.resolve("qwen-explorer")

    assert set(agent._tools_for_profile(profile)) <= set(profile.tools)
    assert not {"local_ai_command", "write_file", "delete_file"}.intersection(profile.tools)


def test_profile_result_marks_advisory_only_and_preserves_language(agent_factory):
    result = agent_factory().run_profile("qwen-drafter", "Navrhni opravu chyby", root="C:\\repo")

    assert result["advisory_only"] is True
    assert result["profile"] == "qwen-drafter"
    assert result["language"] == "cs"
```

- [ ] **Step 2: Run focused tests and verify they fail for missing profile integration**

Run: `python -m pytest tests/test_ollama_subagents.py tests/test_pipeline.py -q`

Expected: FAIL because `ToolAwareLocalAgent` has no profile catalog or profile entrypoint.

- [ ] **Step 3: Integrate profile policy into `ToolAwareLocalAgent`**

Instantiate `OllamaSubagentCatalog(config)` once. Add `_tools_for_profile(profile)` that filters the existing `TOOLS` schema by `profile.tools`, never by caller-provided arbitrary names. Add `run_profile(profile_name, task, root, tenant, workspace=None, seed_context="")` that resolves installed models via `self.services.runtime.installed_models()` when available, then calls the existing bounded `run` loop with profile limits and role.

Update `run` to accept an optional resolved profile. When present, use profile-specific `max_steps`, `max_tool_calls`, `temperature`, and system contract. Include `profile`, `language`, `advisory_only`, `model_fallback`, `tools_used`, and existing cache metadata in successful and degraded results. Keep `_execute_tool` limited to current read-only methods; reject any unknown or mutation-like name before dispatch.

Use a small language detector based on Unicode/script and common task markers, with `match_input` as default. For Czech/Slovak/English/German/Polish/Spanish/French, return the detected ISO language; otherwise return `und` and instruct the model to mirror the task.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_ollama_subagents.py tests/test_pipeline.py -q`

Expected: PASS.

### Task 3: Expose named profiles through existing MCP actions

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/services.py`
- Test: `tests/test_ollama_subagents.py`
- Test: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Write failing MCP compatibility tests**

```python
def test_local_ai_task_accepts_named_advisory_profile(monkeypatch):
    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update(payload)
        return {"success": True, "text": "návrh", "profile": payload.get("profile")}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_task(
        action="delegate", profile="qwen-explorer", root="C:\\repo", task="Najdi vstupní body"
    )

    assert result["success"] is True
    assert captured["profile"] == "qwen-explorer"
    assert captured["root"] == "C:\\repo"


def test_invalid_profile_returns_non_retryable_structured_error(monkeypatch):
    result = local_ai_mcp.local_ai_task(action="delegate", profile="writer", task="x")

    assert result["success"] is False
    assert "qwen-explorer" in result["error"]
```

- [ ] **Step 2: Run focused tests and verify they fail for missing MCP fields**

Run: `python -m pytest tests/test_ollama_subagents.py tests/test_mcp_agent_routing.py -q`

Expected: FAIL because `local_ai_task` does not accept `profile` or `root`.

- [ ] **Step 3: Add optional profile routing without changing tool count**

Extend `local_ai_task` signature with `profile: str = ""`, `root: str = ""`, and `workspace: str = ""`. For `profile` requests, call a service method that validates the catalog, chooses the repository-aware tool loop when `root` is present, and otherwise uses existing bounded generation with the profile system contract. Pass `profile` through async job payloads and include it in cache/source identity so profiles cannot share incompatible answers.

Extend `local_ai_repo` delegation with `profile: str = ""`; forward it to `/v1/delegate/repo`. In `LocalAIServices`, add `delegate_profile(args, tenant)` and use it only for validated profiles. Repository profile calls must use `ToolAwareLocalAgent`; non-repository profile calls must use `_generate` with advisory contract and no tool schema. Existing calls without a profile must remain byte-compatible at the field level used by current tests.

Record profile and model metadata through existing telemetry fields or bounded metadata fields. Never record prompt, context, source text, or model output.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_ollama_subagents.py tests/test_mcp_agent_routing.py -q`

Expected: PASS.

### Task 4: Document adoption and protect configuration behavior

**Files:**
- Modify: `skills/local-ai-orchestrator/SKILL.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `README.md`
- Test: `tests/test_ollama_subagents.py`

- [ ] **Step 1: Write failing documentation-contract tests**

```python
def test_profile_docs_describe_hub_tools_and_advisory_boundary():
    text = Path("skills/local-ai-orchestrator/SKILL.md").read_text(encoding="utf-8")
    assert "qwen-explorer" in text
    assert "qwen-drafter" in text
    assert "qwen-critic" in text
    assert "advisory" in text.lower()
    assert "local_ai_repo" in text
    assert "local_ai_artifact" in text
```

- [ ] **Step 2: Run documentation test and verify it fails before docs change**

Run: `python -m pytest tests/test_ollama_subagents.py::test_profile_docs_describe_hub_tools_and_advisory_boundary -q`

Expected: FAIL because the current skill does not name the three profiles.

- [ ] **Step 3: Document exact triggers and examples**

Add a concise profile section to the skill:

```markdown
### Ollama advisory subagents

Use `qwen-explorer` for bounded repository reconnaissance, `qwen-drafter` for a proposed solution, and `qwen-critic` for independent read-only checking. All profiles call Local AI Hub tooling first: preprocessing/deterministic facts, code index, semantic/graph intelligence, search/RAG, evidence IDs, then bounded file slices. They never write files or run commands.

Example:

```text
local_ai_task(action="delegate", profile="qwen-explorer", root="<absolute-root>", task="Find the smallest set of files relevant to ...")
```
```

Update `docs/MCP_AND_AGENTS.md` and `README.md` with the same short contract, model default, output-language behavior, and skip conditions for deterministic answers.

- [ ] **Step 4: Run documentation test and configuration validation**

Run: `python -m pytest tests/test_ollama_subagents.py::test_profile_docs_describe_hub_tools_and_advisory_boundary -q`

Expected: PASS.

### Task 5: Full verification and final review

**Files:**
- Test: all existing tests plus `tests/test_ollama_subagents.py`

- [ ] **Step 1: Route focused validation through the Hub command broker**

Call `local_ai_command(action="run", command="python -m pytest tests/test_ollama_subagents.py tests/test_mcp_agent_routing.py tests/test_pipeline.py -q", cwd=".")`.

Expected: cached or completed PASS with zero failures.

- [ ] **Step 2: Run focused tests natively only if the broker returns a non-retryable failure**

Run: `python -m pytest tests/test_ollama_subagents.py tests/test_mcp_agent_routing.py tests/test_pipeline.py -q`

Expected: PASS with zero failures.

- [ ] **Step 3: Run the full project validation suite**

Run: `python -m compileall -q src mcp tools tests`

Expected: exit code 0 and no output.

Run: `python -m pytest -q`

Expected: all tests pass.

Run: `python tools/selftest.py`

Expected: self-test success.

- [ ] **Step 4: Verify runtime surface and safety invariants**

Run a bounded Python check that imports the MCP server, collects exactly the existing seven tool names, resolves all three profiles, and asserts none of their tool names contains `command`, `write`, `delete`, `worktree`, or `shell`.

Expected: `MCP_SURFACE_OK`, `PROFILES_OK`, `READ_ONLY_OK`.

- [ ] **Step 5: Review diff and report limitations**

Inspect the changed files with `git diff` only if a Git repository becomes available; otherwise review the file list and test output directly. Confirm no runtime state, prompts, source text, or model output was added to tracked documentation or telemetry. Report that local model output remains advisory and that unavailable-model fallback is bounded.

The workspace is not a Git repository, so no commit step is possible.
