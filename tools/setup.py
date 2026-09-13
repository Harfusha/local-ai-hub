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
from local_ai_hub.features import FeatureSet  # noqa: E402
from local_ai_hub.generator import generate_global_policy, generate_token_economy_policy, write_all_generated  # noqa: E402

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
GLOBAL_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
GLOBAL_POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
TOKEN_ECONOMY_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMY POLICY -->"
TOKEN_ECONOMY_POLICY_END = "<!-- END TOKEN ECONOMY POLICY -->"


def build_global_policy(cfg: dict[str, Any]) -> str:
    """Build a config-aware LOCAL AI HUB TOOL POLICY block.

    Only mentions tools, backends and model names that are actually enabled in
    the given merged config.  The returned string includes the BEGIN/END markers
    so callers can embed it verbatim into AGENTS.md / CLAUDE.md / GEMINI.md.
    """
    return generate_global_policy(cfg)


# Keep a module-level default for callers that do not have a config available
# (e.g. tests or tools that import setup.py directly).  The real policy is
# always built via build_global_policy(cfg) at setup time.
_DEFAULT_POLICY_CFG: dict[str, Any] = {}
GLOBAL_POLICY = build_global_policy(_DEFAULT_POLICY_CFG)



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
    for name in ["src", "skills", "tools"]:
        src, dst = SOURCE_ROOT / name, install_dir / name
        if src.resolve() == dst.resolve():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    for name in [
        "requirements-core.txt", "requirements-token-economy.txt", "requirements-local-nlp.txt", "requirements-openvino.txt", "defaults.toml", "config.toml.example", "pyproject.toml",
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


COMPANION_SKILLS: list[str] = [
    "token-economizer",
    "caveman",
    "tool-orchestration",
    "ollama-quality-routing",
]


def install_agent_skills(install_dir: Path, target_skills_dir: Path, *, include_companion: bool = True) -> None:
    source_skill = install_dir / "skills" / "local-ai-orchestrator"
    install_skill(source_skill, target_skills_dir / "local-ai-orchestrator")
    if include_companion:
        for skill_name in COMPANION_SKILLS:
            source = install_dir / "skills" / skill_name
            if source.exists():
                install_skill(source, target_skills_dir / skill_name)


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


def merge_global_policy(path: Path, backup_enabled: bool, cfg: dict[str, Any] | None = None) -> None:
    policy = build_global_policy(cfg or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(GLOBAL_POLICY_BEGIN) + r".*?" + re.escape(GLOBAL_POLICY_END), re.DOTALL)
    updated = pattern.sub(policy, text) if pattern.search(text) else (text.rstrip() + "\n\n" + policy + "\n")
    if updated != text:
        backup(path, backup_enabled)
        path.write_text(updated, encoding="utf-8")
        log(f"Tool-first policy installed: {path}")


def merge_token_economy_policy(path: Path, backup_enabled: bool, cfg: dict[str, Any] | None = None) -> None:
    policy = generate_token_economy_policy(cfg or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(TOKEN_ECONOMY_POLICY_BEGIN) + r".*?" + re.escape(TOKEN_ECONOMY_POLICY_END), re.DOTALL)
    updated = pattern.sub(policy, text) if pattern.search(text) else (text.rstrip() + "\n\n" + policy + "\n")
    if updated != text:
        backup(path, backup_enabled)
        path.write_text(updated, encoding="utf-8")
        log(f"Token economy policy installed: {path}")


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


def install_token_economy_suite(install_dir: Path, hub_python: Path, *, allow_external_tools: bool = True) -> None:
    """Install token-economy python dependencies, CLI wrapper scripts, and probe external CLI tools."""
    req_file = install_dir / "requirements-token-economy.txt"
    if req_file.is_file():
        install_requirements(hub_python, req_file, optional=True)

    scripts_dir = install_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    if scripts_dir.is_dir():
        py_exe = str(hub_python)
        if os.name == "nt":
            (scripts_dir / "tokcount.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy tokcount %*\n', encoding="utf-8")
            (scripts_dir / "trim-run.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy trim_run %*\n', encoding="utf-8")
            (scripts_dir / "repo-map.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy repo_map %*\n', encoding="utf-8")
        else:
            for tool_name in ["tokcount", "trim-run", "repo-map"]:
                sh_file = scripts_dir / tool_name
                subcmd = tool_name.replace("-", "_")
                sh_file.write_text(f'#!/bin/sh\nexec "{py_exe}" -m local_ai_hub.token_economy {subcmd} "$@"\n', encoding="utf-8")
                try:
                    sh_file.chmod(0o755)
                except Exception:
                    pass

    if not allow_external_tools:
        return

    # Probe and attempt install for external CLI tools
    if not shutil.which("rg"):
        log("ripgrep (rg) not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "BurntSushi.ripgrep.MSVC", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "ripgrep"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "ripgrep"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional ripgrep install skipped: {exc}")

    if not shutil.which("fd") and not shutil.which("fdfind"):
        log("fd not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "sharkdp.fd", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "fd"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "fd-find"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional fd install skipped: {exc}")

    if not shutil.which("ast-grep") and not shutil.which("sg"):
        if shutil.which("npm"):
            log("ast-grep not found in PATH; installing via npm...")
            try:
                run(["npm", "install", "-g", "@ast-grep/cli"], check=False, timeout=300)
            except Exception as exc:
                log(f"Optional ast-grep install skipped: {exc}")

    if not shutil.which("repomix"):
        if shutil.which("npm"):
            log("repomix not found in PATH; installing via npm...")
            try:
                run(["npm", "install", "-g", "repomix"], check=False, timeout=300)
            except Exception as exc:
                log(f"Optional repomix install skipped: {exc}")

    if not shutil.which("jq"):
        log("jq not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "jqlang.jq", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "jq"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "jq"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional jq install skipped: {exc}")


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
    if bool(cfg.get("ollama_subagents", {}).get("enabled", True)):
        profiles = cfg.get("ollama_subagents", {}).get("profiles", {})
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if not isinstance(profile, dict):
                    continue
                model = str(profile.get("model", "") or "")
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
    write_all_generated(cfg, install_dir, hub_python, serena, codegraph)
    log(f"Dynamic skill, manifests, and schemas generated: {install_dir / 'generated'}")


def configure_agents(
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    codegraph: Path | None,
    cfg: dict[str, Any],
    *,
    include_companion: bool = True,
) -> None:
    backup_enabled = bool(cfg.get("setup", {}).get("backup_existing_configs", True))
    agents_cfg = cfg.get("agents", {})
    write_all_generated(cfg, install_dir, hub_python, serena, codegraph)
    if agents_cfg.get("agent_skills_standard", True):
        install_agent_skills(install_dir, Path.home() / ".agents" / "skills", include_companion=include_companion)
    if agents_cfg.get("codex", True):
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        install_agent_skills(install_dir, codex_home / "skills", include_companion=include_companion)
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            doc = codex_home / ("AGENTS.override.md" if (codex_home / "AGENTS.override.md").exists() else "AGENTS.md")
            merge_global_policy(doc, backup_enabled, cfg=cfg)
            merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        codex_mcp_merge(
            codex_home / "config.toml", build_mcp_entries(install_dir, hub_python, serena, codegraph, "codex", cfg), backup_enabled,
            startup_timeout=int(cfg.get("client", {}).get("startup_wait_seconds", 15)) + 15,
            tool_timeout=int(cfg.get("mcp", {}).get("host_tool_timeout_seconds", 900)),
        )
    if agents_cfg.get("claude", True):
        install_agent_skills(install_dir, Path.home() / ".claude" / "skills", include_companion=include_companion)
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            doc = Path.home() / ".claude" / "CLAUDE.md"
            merge_global_policy(doc, backup_enabled, cfg=cfg)
            merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        json_mcp_merge(Path.home() / ".claude.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "claude", cfg), backup_enabled)
    if agents_cfg.get("gemini", True):
        install_agent_skills(install_dir, Path.home() / ".gemini" / "skills", include_companion=include_companion)
        install_agent_skills(install_dir, Path.home() / ".gemini" / "config" / "skills", include_companion=include_companion)
        if cfg.get("tool_policy", {}).get("install_global_instructions", True):
            doc = Path.home() / ".gemini" / "GEMINI.md"
            merge_global_policy(doc, backup_enabled, cfg=cfg)
            merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        json_mcp_merge(Path.home() / ".gemini" / "settings.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "gemini", cfg), backup_enabled)
        antigravity_mcp = Path.home() / ".gemini" / "antigravity" / "mcp" / "local-ai"
        if antigravity_mcp.exists():
            schemas_dir = install_dir / "generated" / "schemas"
            if schemas_dir.exists():
                for sfile in schemas_dir.glob("*.json"):
                    shutil.copy2(sfile, antigravity_mcp / sfile.name)
    # Additional major MCP hosts. Their tool descriptions always carry the same
    # tool-first policy even when the host has no global skill format.
    if agents_cfg.get("cursor", True):
        json_mcp_merge(Path.home() / ".cursor" / "mcp.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "cursor", cfg), backup_enabled)
    if agents_cfg.get("windsurf", True):
        json_mcp_merge(Path.home() / ".codeium" / "windsurf" / "mcp_config.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "windsurf", cfg), backup_enabled)
    if agents_cfg.get("copilot", True):
        vscode_mcp_merge(Path.home() / ".copilot" / "mcp-config.json", build_mcp_entries(install_dir, hub_python, serena, codegraph, "copilot", cfg), backup_enabled)

    # Escape hatch for any MCP host/build whose config path differs from
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
    if explicit is not None:
        source = explicit.expanduser().resolve()
    else:
        local_config = SOURCE_ROOT / "config.toml"
        example_config = SOURCE_ROOT / "config.toml.example"
        source = (local_config if local_config.is_file() else example_config).expanduser().resolve()
    cfg = load_hub_config(str(source))
    install_dir = expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
    installed = (install_dir / "config.toml").resolve()
    if explicit is None and installed.exists() and installed != source:
        source = installed
        cfg = load_hub_config(str(source))
    return source, cfg, install_dir

def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required. Use install.ps1/install.sh to bootstrap a supported Python automatically.")
    parser = argparse.ArgumentParser(description="Install Local AI Hub")
    parser.add_argument("--config", type=Path, default=None, help="Import/replace config from this path. Without it, reruns preserve the installed config.")
    parser.add_argument("--profile", choices=["auto", "cpu", "integrated", "low", "balanced", "high", "max"])
    parser.add_argument("--skip-model-pull", action="store_true")
    parser.add_argument("--skip-local-nlp-preload", action="store_true")
    parser.add_argument("--skip-tools", action="store_true", help="Do not install Serena/CodeGraphContext")
    parser.add_argument("--skip-agent-config", action="store_true")
    parser.add_argument("--skip-service", action="store_true")
    parser.add_argument("--skip-ollama-install", action="store_true")
    parser.add_argument("--skip-token-economy", action="store_true", help="Do not install token economy packages or probe external CLI tools")
    parser.add_argument("--skip-companion-skills", action="store_true", help="Do not install companion skills (token-economizer, caveman, tool-orchestration, ollama-quality-routing)")
    parser.add_argument("--generate-only", action="store_true", help="Generate dynamic skill, instructions, MCP manifests, and schemas without re-installing dependencies or service.")
    args = parser.parse_args()

    config_source, cfg, install_dir = select_config_source(args.config)
    include_companion = not args.skip_companion_skills and bool(cfg.get("setup", {}).get("install_companion_skills", True))
    if args.generate_only:
        hub_python = venv_python(install_dir / ".venv")
        if not hub_python.exists():
            hub_python = Path(sys.executable)
        write_all_generated(cfg, SOURCE_ROOT, hub_python)
        if install_dir.resolve() != SOURCE_ROOT.resolve():
            write_all_generated(cfg, install_dir, hub_python)
        if not args.skip_agent_config and bool(cfg.get("setup", {}).get("install_agent_configs", True)):
            configure_agents(install_dir, hub_python, None, None, cfg, include_companion=include_companion)
        log("Skill, agent instructions, and MCP artifacts successfully generated.")
        return 0

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
    if not args.skip_token_economy:
        install_token_economy_suite(install_dir, hub_python, allow_external_tools=True)

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
    embedding_backend = str(model_cfg.get("embedding_backend", "sentence-transformers")).lower()
    reranker_backend = str(model_cfg.get("reranker_backend", "torch")).lower()
    needs_local_nlp = (
        (bool(features.get("reranker", True)) and reranker_backend != "openvino")
        or (bool(features.get("rag", True)) and embedding_backend in {"sentence-transformers", "auto"})
    )
    if needs_local_nlp and features.get("install_local_nlp_dependencies", True):
        local_nlp_ok = install_requirements(hub_python, install_dir / "requirements-local-nlp.txt", optional=True)
        if local_nlp_ok and not args.skip_local_nlp_preload:
            try:
                run([str(hub_python), str(install_dir / "tools" / "prefetch_local_nlp.py")], check=False, timeout=1800)
            except Exception:
                pass

    hw_detected = cfg.get("_hardware", {})
    detected_gpus = hw_detected.get("gpus", []) if isinstance(hw_detected, dict) else []
    detected_npus = hw_detected.get("npus", []) if isinstance(hw_detected, dict) else []
    has_intel_gpu = any(str(g.get("vendor", "")).lower() == "intel" for g in detected_gpus if isinstance(g, dict))
    has_npu_hw = bool(detected_npus)

    needs_openvino = (
        embedding_backend == "openvino"
        or reranker_backend == "openvino"
        or has_npu_hw
        or (has_intel_gpu and cfg.get("_hardware", {}).get("profile") == "integrated")
    )
    ov_cfg = cfg.get("openvino", {})
    install_openvino = (
        needs_openvino
        and features.get("install_openvino_dependencies", True)
        and bool(ov_cfg.get("enabled", True))
        and bool(ov_cfg.get("auto_install", True))
    )
    openvino_ok = False
    if install_openvino:
        openvino_ok = install_requirements(hub_python, install_dir / "requirements-openvino.txt", optional=True)
        if openvino_ok and not args.skip_local_nlp_preload:
            try:
                run([str(hub_python), str(install_dir / "tools" / "prefetch_openvino.py")], check=False, timeout=1800)
            except Exception:
                pass

    if needs_openvino and not openvino_ok and features.get("install_local_nlp_dependencies", True):
        # CPU fallback is part of the OpenVINO reliability contract. Install its
        # lightweight SentenceTransformers dependency even when Intel acceleration
        # was explicitly disabled, auto-install was disabled, or the optional
        # OpenVINO install failed. Users can still disable both dependency installers.
        install_requirements(hub_python, install_dir / "requirements-local-nlp.txt", optional=True)

    if not args.skip_agent_config and bool(setup_cfg.get("install_agent_configs", True)):
        configure_agents(install_dir, hub_python, serena, codegraph, cfg, include_companion=include_companion)
    else:
        write_generated_agent_manifests(install_dir, hub_python, serena, codegraph, cfg)

    if os.name == "nt":
        has_nvidia = any(str(g.get("vendor", "")).lower() == "nvidia" for g in detected_gpus if isinstance(g, dict))
        has_igpu = any(bool(g.get("integrated")) or "intel" in str(g.get("name", "")).lower() or "radeon" in str(g.get("name", "")).lower() for g in detected_gpus if isinstance(g, dict))
        is_integrated_profile = cfg.get("_hardware", {}).get("profile") == "integrated" or cfg.get("hardware", {}).get("profile") == "integrated"
        if (has_igpu or is_integrated_profile) and not has_nvidia:
            if not os.environ.get("OLLAMA_VULKAN"):
                try:
                    ps_cmd = "[System.Environment]::SetEnvironmentVariable('OLLAMA_VULKAN', '1', 'User')"
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, timeout=10)
                    os.environ["OLLAMA_VULKAN"] = "1"
                    log("Configured OLLAMA_VULKAN=1 in Windows user environment for iGPU acceleration.")
                except Exception as exc:
                    log(f"Notice: Could not set OLLAMA_VULKAN environment variable: {exc}")

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
