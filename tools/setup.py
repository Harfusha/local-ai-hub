from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SRC = SOURCE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.config import load_config as load_hub_config  # noqa: E402

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
GLOBAL_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
GLOBAL_POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
GLOBAL_POLICY = """<!-- BEGIN LOCAL AI HUB TOOL POLICY -->
Trigger map:
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`

Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.

Delegation is the default for any task with useful bounded independent work.
- After required indexed evidence, call AGY directly (`mcp__agy__agy` or `mcp__agy__agy_start`) first for research, planning, implementation, review, testing support, or other bounded sidecar work.
- Use `local_ai_task` for bounded local-model work when local inference is the right fit. Do not use the native Codex `multi_agent_v1__spawn_agent` path unless the user explicitly requests a Codex subagent, the task requires a Codex-only capability or native Codex context/tool lifecycle, or one bounded AGY attempt reports AGY unavailable.
- AGY is the mandatory first peer-agent choice for delegatable work; native Codex subagents are exception-only. Never duplicate the same scope across AGY and native Codex agents.
- Codex controls each subagent's scope, `allow_write`, workspace/worktree, timeout, cancellation, and integration.
- AGY is invoked and lifecycle-managed directly by Codex; Local AI Hub does not bootstrap, route, proxy, or own AGY tasks.
- Do not duplicate the same scope across agents. Keep final decisions, edits, and integration in Codex.
- Skip delegation only for trivial tasks, pure evidence lookups, security/privacy constraints, or no useful independent scope.

Routing hierarchy: the main agent is the orchestrator, planner, integrator and final owner. Use Local AI Hub first for its own precise, bounded microtasks: deterministic facts, indexed/search retrieval, preprocess artifacts, targeted impact/review/security checks, safe commands, compression, local-model synthesis and second opinions. After that evidence, delegate every useful independent scope to AGY first. Native `multi_agent_v1__spawn_agent` is exception-only: explicit Codex-subagent request, Codex-only capability/context/lifecycle, or one bounded AGY-unavailable fallback. Neither is routed or managed by Local AI Hub.

READ-ONLY AUDIT CONTRACT:
- Read-only means no Git writes, `git worktree add` or removal, dependency installation, builds/imports, generated artifacts, or other workspace side effects. Never label such work read-only when any of these occur; split validation into a separately owned, explicitly side-effecting task.
- Before native discovery or validation, retain preceding Hub result with action, absolute root, status, cache/in_progress state, and evidence IDs. Native discovery is fallback-only after one bounded terminal Hub failure.
- Native validation fallback is allowed only after `local_ai_command` returns `terminal=true` and `retryable=false`; run one bounded fallback, state side effects/owner, and never repeat identical commands.
- Codex controls subagent permissions per task. Native Codex subagents and AGY may write only when Codex explicitly enables it, and write work stays in the assigned workspace/worktree. Codex remains integrator.
- Do not run parallel duplicate commands or scopes. Tool labels such as `Local ai repo` or `Agy start` are not evidence; preserve exact action, arguments, result, and ownership in the audit record.

For every non-trivial repository task, use Local AI Hub before broad native discovery or repeatable validation. Keep one stable absolute project root. On the first task for that root call `local_ai_repo(action="preprocess", root=ABS_ROOT)` exactly once, then continue immediately; preprocessing is asynchronous, so never poll/wait/force-refresh it.

Adoption gate: `local_ai_command` alone is never sufficient for a repository task. The first useful Hub operation must be `local_ai_repo` (preprocess plus the cheapest applicable deterministic/code-index/search/context action); use the command broker only for commands, after repository evidence exists. For implementation, diagnosis, refactoring or complex review, call `local_ai_repo(action="solve")` after evidence and before native edits. After edits, use the applicable indexed impact/review/security/evidence action before final validation.

Use the cheapest sufficient path: `deterministic` for manifests/config/tests/entrypoints -> `code_index` for symbols/references or `search` for exact text/files -> `semantic`/`graph` only for language/relationship questions -> `context`/`solve` only when compact evidence is insufficient -> RAG/local-model reasoning last. Stop escalating as soon as a cheaper layer provides enough evidence. Do not fan out deterministic/search/context/RAG/model calls in parallel for the same question: the broader layers already compose/reuse the cheaper indexes. Parallelize only independent questions. Before native `find`/`rg`/`grep`/recursive glob/tree or opening more than two files for discovery, use that hub path first. Reuse fresh evidence IDs, artifact slices, memos and cache hits; do not repeat the same hub action with the same root/query while repository state is unchanged.

Treat result state as a protocol: `cache_hit`/`coalesced` means reuse the result; `in_progress=true` means another owner is doing identical work, so never duplicate it; `retryable`/429/503 means back off and do independent work; `degraded`/`stale` means verify only the affected path/slice; a non-retryable failure permits one cheaper/native fallback. Never turn a transient result into larger timeouts, force refreshes, or polling loops.

Route test/lint/typecheck/build/read-only commands through `local_ai_command` before running them natively. If it returns `in_progress=true`, do not launch a duplicate command. Before an expensive `solve`/model call, search coordination memos for reusable findings. For overlapping multi-agent edits use `local_ai_coord` leases and store concise reusable discoveries as memos. After edits, use indexed impact/review plus targeted cached validation; do not rerun broad discovery merely because files changed. `force` and `preprocess_refresh` are recovery/admin controls, never retry buttons. If an optional backend degrades, accept the hub's deterministic/index fallback. If the hub itself is unavailable, make one bounded health/retry attempt, then fall back to native tools. Never loop on health, status, preprocessing, model startup, a failing backend, or an identical command.

Selection guide: `local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`), `local_ai_command` for bounded repeatable commands, `local_ai_task` for small local-model work and second opinions, `local_ai_rag` only after cheaper indexed evidence, `local_ai_artifact` for exact slices, and `local_ai_coord` for leases/memos. AGY is default peer worker for useful delegated scopes, outside Hub orchestration. Native Codex `multi_agent_v1__spawn_agent` is exception-only under the routing rule above.

Codex-owned AGY transport: pass an existing absolute workspace or worktree directory. The bridge uses it as subprocess `cwd` and passes it to AGY with `--add-dir`; never pass a missing path. `WinError 267` means invalid Windows working directory: validate the path before retrying. Codex chooses sandbox and write permissions per task; never use `--dangerously-skip-permissions`, provider API keys, or direct provider REST endpoints.
- Direct AGY MCP calls use `mcp__agy__agy` or `mcp__agy__agy_start`; pass the existing absolute repository directory as `cd`. Detached jobs use bounded `mcp__agy__agy_status`, `mcp__agy__agy_read`, `mcp__agy__agy_result` and `mcp__agy__agy_cancel` operations.
AGY model routing: the caller selects only `effort`; `low`/`medium` use Gemini 3.8 Flash, while `high`/complex or high-risk work uses Claude Sonnet. Claude Opus is never allowed. Do not expose routine provider/model selection or tune generation knobs.
Sonnet quota fallback: on a quota/usage/rate-limit error, retry the same bounded task once on the highest Gemini model reported by the host, targeting `gemini-3.8-flash`. Gemini model usage is shared, so never walk down to weaker models; change only `effort`, report `degraded: Sonnet -> <model>`, and never degrade auth, permission, invalid-request, workspace or transport errors.

Local model default: when generation is needed, use `qwen2.5-coder:7b` for ordinary `local_ai_task` delegate/reason/review/second-opinion/compress work. Escalate to `heavy_code` only for complex or high-risk work; deterministic and indexed Hub actions run first.
<!-- END LOCAL AI HUB TOOL POLICY -->"""


def log(message: str) -> None:
    print(f"[local-ai-hub] {message}")


def run(cmd: list[str], *, check: bool = True, timeout: int | None = 120, capture: bool = False) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(f'\"{x}\"' if " " in str(x) else str(x) for x in cmd))
    return subprocess.run(
        [str(x) for x in cmd], text=True, check=check, timeout=timeout,
        stdout=subprocess.PIPE if capture else sys.stdout,
        stderr=subprocess.PIPE if capture else sys.stderr,
        encoding="utf-8", errors="replace",
    )


def expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_executable(venv: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return venv / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def ensure_venv(venv: Path) -> Path:
    python = venv_python(venv)
    if not python.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    return python


def install_requirements(python: Path, requirement: Path, *, optional: bool = False) -> bool:
    try:
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip", "wheel"], timeout=300)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirement)], timeout=1800)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if optional:
            log(f"WARNING: optional dependency install failed: {requirement.name}")
            return False
        raise


def copy_install_tree(install_dir: Path, config_source: Path) -> None:
    install_dir.mkdir(parents=True, exist_ok=True)
    # Package-native MCP supersedes the legacy source-wrapper directory; remove it on upgrade.
    legacy_mcp = install_dir / "mcp"
    if legacy_mcp.exists() and install_dir.resolve() != SOURCE_ROOT.resolve():
        shutil.rmtree(legacy_mcp)
    for name in ["src", "skills", "tools"]:
        src, dst = SOURCE_ROOT / name, install_dir / name
        if src.resolve() == dst.resolve():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    for name in [
        "requirements-core.txt", "requirements-local-nlp.txt", "defaults.toml", "pyproject.toml",
        "README.md", "FEATURES.md", "AGENTS.md", "LICENSE", "CHANGELOG.md", "THIRD_PARTY.md",
        "RELEASE.json", "CONTRIBUTING.md", "SECURITY.md", "install.ps1", "install.sh",
    ]:
        src, dst = SOURCE_ROOT / name, install_dir / name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
    config_dest = install_dir / "config.toml"
    if config_source.exists() and config_source.resolve() != config_dest.resolve():
        shutil.copy2(config_source, config_dest)


def backup(path: Path, enabled: bool) -> None:
    if not enabled or not path.exists():
        return
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = path.with_name(path.name + f".local-ai-hub-backup-{stamp}")
    shutil.copy2(path, dest)
    log(f"Backup: {dest}")


def install_skill(source_skill: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source_skill, target)
    log(f"Skill installed: {target}")


def json_server_merge(
    path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool, *,
    container_key: str = "mcpServers", require_stdio_type: bool = False,
) -> None:
    """Merge Local AI servers without replacing unrelated client configuration.

    Cursor/Claude/Gemini/Windsurf use ``mcpServers`` while VS Code/Copilot's
    portable MCP format uses ``servers`` and requires an explicit stdio type.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        backup(path, backup_enabled)
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("top-level JSON value must be an object")
            data = parsed
        except Exception as exc:
            raise RuntimeError(f"Cannot parse JSON config {path}: {exc}") from exc
    container = data.setdefault(container_key, {})
    if not isinstance(container, dict):
        raise RuntimeError(f"{container_key} is not an object in {path}")
    for name, raw_entry in servers.items():
        entry = dict(raw_entry)
        if require_stdio_type:
            entry.setdefault("type", "stdio")
        container[name] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"MCP config updated: {path}")


def json_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool) -> None:
    json_server_merge(path, servers, backup_enabled, container_key="mcpServers")


def vscode_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool) -> None:
    json_server_merge(path, servers, backup_enabled, container_key="servers", require_stdio_type=True)

def toml_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def codex_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool, *, startup_timeout: int = 60, tool_timeout: int = 900) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    backup(path, backup_enabled)
    text = re.sub(rf"\n?{re.escape(MARKER_BEGIN)}.*?{re.escape(MARKER_END)}\n?", "\n", text, flags=re.DOTALL).rstrip() + "\n"
    blocks: list[str] = [MARKER_BEGIN]
    for name, entry in servers.items():
        # Never overwrite an explicitly user-managed block.
        if re.search(rf"(?m)^\[mcp_servers\.{re.escape(name)}\]\s*$", text):
            log(f"Codex MCP '{name}' exists outside the managed block; leaving it unchanged")
            continue
        blocks.extend([
            f"[mcp_servers.{name}]", f"command = {toml_quote(entry['command'])}",
            "args = [" + ", ".join(toml_quote(x) for x in entry.get("args", [])) + "]",
            "enabled = true", "required = false", f"startup_timeout_sec = {max(10, int(startup_timeout))}", f"tool_timeout_sec = {max(60, int(tool_timeout))}",
        ])
        if entry.get("cwd"):
            blocks.append(f"cwd = {toml_quote(entry['cwd'])}")
        env = entry.get("env") or {}
        if env:
            blocks.extend(["", f"[mcp_servers.{name}.env]"])
            blocks.extend(f"{key} = {toml_quote(value)}" for key, value in env.items())
        blocks.append("")
    blocks.append(MARKER_END)
    path.write_text(text + "\n".join(blocks) + "\n", encoding="utf-8")
    log(f"Codex MCP config updated: {path}")


def merge_global_policy(path: Path, backup_enabled: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(GLOBAL_POLICY_BEGIN) + r".*?" + re.escape(GLOBAL_POLICY_END), re.DOTALL)
    updated = pattern.sub(GLOBAL_POLICY, text) if pattern.search(text) else (text.rstrip() + "\n\n" + GLOBAL_POLICY + "\n")
    if updated != text:
        backup(path, backup_enabled)
        path.write_text(updated, encoding="utf-8")
        log(f"Tool-first policy installed: {path}")


def install_tool_env(install_dir: Path, name: str, package: str, executables: list[str]) -> Path | None:
    venv = install_dir / "tool-envs" / name
    python = ensure_venv(venv)
    try:
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", package], timeout=1800)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log(f"WARNING: {name} install failed ({type(exc).__name__}); Local AI Hub will continue with built-in code intelligence")
        return None
    for executable in executables:
        candidate = venv_executable(venv, executable)
        if candidate.exists():
            return candidate
    log(f"WARNING: {name} package installed but no supported executable was found")
    return None


def build_mcp_entries(install_dir: Path, hub_python: Path, serena: Path | None, codegraph: Path | None, agent: str, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {
        "local-ai": {
            "command": str(hub_python),
            "args": ["-m", "local_ai_hub.mcp_server"],
            "cwd": str(install_dir),
            "env": {
                "LOCAL_AI_AGENT": agent,
                "LOCAL_AI_AGENT_PROFILE": agent,
                "LOCAL_AI_CONFIG": str(install_dir / "config.toml"),
                "PYTHONPATH": str(install_dir / "src"),
            },
        }
    }
    if not bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        return entries
    # Optional escape hatch. Default installations expose only Local AI Hub to save schemas/tokens.
    if serena is not None and cfg.get("code_intelligence", {}).get("serena_enabled", True):
        context = "codex" if agent == "codex" else "claude-code" if agent == "claude" else "ide-assistant"
        entries["serena"] = {"command": str(serena), "args": ["start-mcp-server", "--context", context, "--project-from-cwd", "--open-web-dashboard", "false"]}
    if codegraph is not None and cfg.get("code_intelligence", {}).get("codegraph_enabled", True):
        entries["codegraph"] = {"command": str(codegraph), "args": ["mcp", "start"]}
    return entries


def find_ollama_executable() -> str | None:
    executable = shutil.which("ollama")
    if executable is None and os.name == "nt":
        candidate = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"))
        if candidate.exists():
            executable = str(candidate)
    return executable


def try_install_ollama() -> str | None:
    existing = find_ollama_executable()
    if existing:
        return existing
    log("Ollama is not installed; attempting a platform package installation...")
    try:
        if os.name == "nt" and shutil.which("winget"):
            run(["winget", "install", "--id", "Ollama.Ollama", "--exact", "--accept-source-agreements", "--accept-package-agreements", "--silent"], check=False, timeout=900)
        elif sys.platform == "darwin" and shutil.which("brew"):
            run(["brew", "install", "ollama"], check=False, timeout=900)
        elif sys.platform.startswith("linux"):
            log("Linux auto-install is disabled: install Ollama from a trusted package source, then rerun setup.")
    except Exception as exc:
        log(f"WARNING: Ollama installation attempt failed: {exc}")
    return find_ollama_executable()


def ensure_ollama_for_setup(cfg: dict[str, Any], install_dir: Path, *, allow_install: bool) -> bool:
    if not cfg.get("server", {}).get("auto_start_ollama", True):
        return True
    executable = find_ollama_executable() or (try_install_ollama() if allow_install else None)
    if not executable:
        log("WARNING: Ollama is unavailable. Install it later or set server.auto_start_ollama=false for deterministic-only use.")
        return False
    src = install_dir / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from local_ai_hub.ollama import OllamaRuntime
        runtime = OllamaRuntime(cfg)
        return runtime.is_online() or runtime.ensure_running()
    except Exception as exc:
        log(f"WARNING: Ollama startup check failed: {exc}")
        return False


def pull_ollama_models(cfg: dict[str, Any]) -> None:
    if not cfg.get("features", {}).get("pull_models_during_setup", True):
        return
    ollama = find_ollama_executable()
    if not ollama:
        return
    models: list[str] = []
    model_cfg = cfg.get("models", {})
    for key in ["background_code", "fast_code", "heavy_code", "reasoning", "general"]:
        model = str(model_cfg.get(key, "") or "")
        if model and model not in models:
            models.append(model)
    if model_cfg.get("embedding_backend") == "ollama":
        model = str(model_cfg.get("embedding", "") or "")
        if model and model not in models:
            models.append(model)
    for model in models:
        try:
            run([ollama, "pull", model], check=False, timeout=1800)
        except Exception:
            log(f"WARNING: model pull did not complete: {model}")


def write_generated_agent_manifests(install_dir: Path, hub_python: Path, serena: Path | None, codegraph: Path | None, cfg: dict[str, Any]) -> None:
    generated_dir = install_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generic = build_mcp_entries(install_dir, hub_python, serena, codegraph, "generic", cfg)
    vscode = build_mcp_entries(install_dir, hub_python, serena, codegraph, "copilot", cfg)
    (generated_dir / "mcp-servers.json").write_text(json.dumps({"mcpServers": generic}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (generated_dir / "vscode-mcp.json").write_text(json.dumps({"servers": {k: {"type": "stdio", **v} for k, v in vscode.items()}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (generated_dir / "agent-policy.md").write_text(GLOBAL_POLICY + "\n", encoding="utf-8")
    log(f"Generic MCP manifests: {generated_dir}")


def configure_agents(install_dir: Path, hub_python: Path, serena: Path | None, codegraph: Path | None, cfg: dict[str, Any]) -> None:
    backup_enabled = bool(cfg.get("setup", {}).get("backup_existing_configs", True))
    agents_cfg = cfg.get("agents", {})
    source_skill = install_dir / "skills" / "local-ai-orchestrator"
    if agents_cfg.get("agent_skills_standard", True):
        install_skill(source_skill, Path.home() / ".agents" / "skills" / "local-ai-orchestrator")
    if agents_cfg.get("codex", True):
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        install_skill(source_skill, codex_home / "skills" / "local-ai-orchestrator")
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            merge_global_policy(codex_home / ("AGENTS.override.md" if (codex_home / "AGENTS.override.md").exists() else "AGENTS.md"), backup_enabled)
            # Keep the legacy Codex instruction file aligned too; otherwise it can
            # shadow the newer routing contract and steer the agent to commands only.
            merge_global_policy(codex_home / "instructions.md", backup_enabled)
        codex_mcp_merge(
            codex_home / "config.toml", build_mcp_entries(install_dir, hub_python, serena, codegraph, "codex", cfg), backup_enabled,
            startup_timeout=int(cfg.get("client", {}).get("startup_wait_seconds", 15)) + 15,
            tool_timeout=int(cfg.get("mcp", {}).get("host_tool_timeout_seconds", 900)),
        )
    if agents_cfg.get("claude", True):
        install_skill(source_skill, Path.home() / ".claude" / "skills" / "local-ai-orchestrator")
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            merge_global_policy(Path.home() / ".claude" / "CLAUDE.md", backup_enabled)
        json_mcp_merge(Path.home() / ".claude.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "claude", cfg), backup_enabled)
    if agents_cfg.get("gemini", True):
        install_skill(source_skill, Path.home() / ".gemini" / "skills" / "local-ai-orchestrator")
        install_skill(source_skill, Path.home() / ".gemini" / "config" / "skills" / "local-ai-orchestrator")
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            merge_global_policy(Path.home() / ".gemini" / "GEMINI.md", backup_enabled)
        json_mcp_merge(Path.home() / ".gemini" / "settings.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "gemini", cfg), backup_enabled)
    # Additional major MCP hosts. Their tool descriptions always carry the same
    # tool-first policy even when the host has no compatible global skill format.
    if agents_cfg.get("cursor", True):
        json_mcp_merge(Path.home() / ".cursor" / "mcp.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "cursor", cfg), backup_enabled)
    if agents_cfg.get("windsurf", True):
        json_mcp_merge(Path.home() / ".codeium" / "windsurf" / "mcp_config.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "windsurf", cfg), backup_enabled)
    if agents_cfg.get("copilot", True):
        vscode_mcp_merge(Path.home() / ".copilot" / "mcp-config.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "copilot", cfg), backup_enabled)

    # Escape hatch for any MCP-compatible host/build whose config path differs from
    # the common defaults above. Users provide explicit paths, so setup never guesses
    # at vendor-specific locations or overwrites unrelated files.
    generic_entries = build_mcp_entries(install_dir, hub_python, serena, codegraph, "generic", cfg)
    for raw in agents_cfg.get("extra_mcp_json_paths", []) or []:
        if str(raw).strip():
            json_mcp_merge(expand(str(raw)), generic_entries, backup_enabled)
    for raw in agents_cfg.get("extra_vscode_mcp_paths", []) or []:
        if str(raw).strip():
            vscode_mcp_merge(expand(str(raw)), generic_entries, backup_enabled)
    write_generated_agent_manifests(install_dir, hub_python, serena, codegraph, cfg)



def select_config_source(explicit: Path | None) -> tuple[Path, dict[str, Any], Path]:
    """Resolve config for idempotent installs.

    A normal rerun preserves the config already living in the install directory.
    Passing --config is explicit replacement/import intent and therefore wins.
    """
    source = (explicit or (SOURCE_ROOT / "config.toml")).expanduser().resolve()
    cfg = load_hub_config(str(source))
    install_dir = expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
    installed = (install_dir / "config.toml").resolve()
    if explicit is None and installed.exists() and installed != source:
        source = installed
        cfg = load_hub_config(str(source))
    return source, cfg, install_dir

def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required. Use install.ps1/install.sh to bootstrap a compatible Python automatically.")
    parser = argparse.ArgumentParser(description="Install Local AI Hub")
    parser.add_argument("--config", type=Path, default=None, help="Import/replace config from this path. Without it, reruns preserve the installed config.")
    parser.add_argument("--profile", choices=["auto", "cpu", "low", "balanced", "high", "max"])
    parser.add_argument("--skip-model-pull", action="store_true")
    parser.add_argument("--skip-local-nlp-preload", action="store_true")
    parser.add_argument("--skip-tools", action="store_true", help="Do not install Serena/CodeGraphContext")
    parser.add_argument("--skip-agent-config", action="store_true")
    parser.add_argument("--skip-service", action="store_true")
    parser.add_argument("--skip-ollama-install", action="store_true")
    args = parser.parse_args()

    config_source, cfg, install_dir = select_config_source(args.config)
    log(f"Installing to {install_dir}")

    # Stop a currently managed instance if this exact install already exists. This is
    # normal idempotent setup behavior for this installation target.
    old_python = venv_python(install_dir / ".venv")
    old_service = install_dir / "tools" / "service.py"
    if old_python.exists() and old_service.exists():
        try:
            run([str(old_python), str(old_service), "stop"], check=False, timeout=20)
        except Exception:
            pass

    copy_install_tree(install_dir, config_source)
    installed_config = install_dir / "config.toml"
    if args.profile:
        text = installed_config.read_text(encoding="utf-8")
        section = re.search(r"(?ms)^\[hardware\]\s*$(.*?)(?=^\[|\Z)", text)
        if section:
            body = section.group(1)
            if re.search(r"(?m)^profile\s*=", body):
                body = re.sub(r'(?m)^profile\s*=.*$', f'profile = "{args.profile}"', body)
            else:
                body = f'\nprofile = "{args.profile}"' + body
            text = text[:section.start(1)] + body + text[section.end(1):]
        else:
            text = text.rstrip() + f'\n\n[hardware]\nprofile = "{args.profile}"\nauto_tune = true\n'
        installed_config.write_text(text, encoding="utf-8")
    cfg = load_hub_config(str(installed_config))
    if args.skip_model_pull:
        cfg.setdefault("features", {})["pull_models_during_setup"] = False
    hub_python = ensure_venv(install_dir / ".venv")
    install_requirements(hub_python, install_dir / "requirements-core.txt")

    serena: Path | None = None
    codegraph: Path | None = None
    setup_cfg = cfg.get("setup", {})
    if not args.skip_tools and bool(setup_cfg.get("install_optional_tools", True)):
        intelligence = cfg.get("code_intelligence", {})
        if intelligence.get("serena_enabled", True):
            serena = install_tool_env(install_dir, "serena", str(cfg.get("tools", {}).get("serena_package", "serena-agent==1.7.0")), ["serena"])
        if intelligence.get("codegraph_enabled", True):
            codegraph = install_tool_env(install_dir, "codegraph", str(cfg.get("tools", {}).get("codegraph_package", "codegraphcontext[gcf]==0.6.8")), ["cgc", "codegraphcontext"])

    features = cfg.get("features", {})
    model_cfg = cfg.get("models", {})
    needs_local_nlp = bool(features.get("reranker", True)) or (bool(features.get("rag", True)) and model_cfg.get("embedding_backend", "sentence-transformers") in {"sentence-transformers", "auto"})
    if needs_local_nlp and features.get("install_local_nlp_dependencies", True):
        local_nlp_ok = install_requirements(hub_python, install_dir / "requirements-local-nlp.txt", optional=True)
        if local_nlp_ok and not args.skip_local_nlp_preload:
            try:
                run([str(hub_python), str(install_dir / "tools" / "prefetch_local_nlp.py")], check=False, timeout=1800)
            except Exception:
                pass

    if not args.skip_agent_config and bool(setup_cfg.get("install_agent_configs", True)):
        configure_agents(install_dir, hub_python, serena, codegraph, cfg)
    else:
        write_generated_agent_manifests(install_dir, hub_python, serena, codegraph, cfg)

    ensure_ollama_for_setup(cfg, install_dir, allow_install=not args.skip_ollama_install)
    pull_ollama_models(cfg)

    if not args.skip_service and bool(setup_cfg.get("install_service", True)) and cfg.get("headless", {}).get("enabled", True):
        try:
            run([str(hub_python), str(install_dir / "tools" / "service.py"), "install"], check=False, timeout=45)
        except Exception as exc:
            log(f"WARNING: service install failed: {exc}")
    else:
        try:
            run([str(hub_python), str(install_dir / "tools" / "hubctl.py"), "restart"], check=False, timeout=30)
        except Exception:
            pass

    try:
        run([str(hub_python), str(install_dir / "tools" / "doctor.py")], check=False, timeout=60)
    except Exception as exc:
        log(f"WARNING: doctor could not complete: {exc}")

    hw = cfg.get("_hardware", {})
    log(f"Setup complete. Detected profile: {hw.get('profile', 'unknown')} ({hw.get('os', '')}/{hw.get('arch', '')}).")
    log("Restart configured agents so they reload the Local AI Hub MCP server and tool-first policy.")
    log("Dashboard: http://127.0.0.1:11435/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
