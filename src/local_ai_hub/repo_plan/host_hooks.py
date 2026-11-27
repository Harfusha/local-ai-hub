"""Documented, project-local host hooks. Configuration is never enforcement proof.

Codex: https://learn.chatgpt.com/docs/hooks
Gemini CLI: https://geminicli.com/docs/hooks/reference/
Dependency: https://github.com/obra/superpowers/tree/v7.0.1

The host owns trust review and plugin installation. This module neither changes
host trust/permissions nor treats a manually supplied event as authentic proof.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# The installed registration invokes this shipped file with an explicit Python,
# so it also works before an editable install and outside the Hub's cwd.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HOSTS = {"codex": (".codex/hooks.json", "UserPromptSubmit", "PreToolUse"),
         "gemini_cli": (".gemini/settings.json", "BeforeAgent", "BeforeTool"),
         "claude": (".claude/settings.json", "UserPromptSubmit", "PreToolUse"),
         "cursor": (".cursor/hooks.json", "beforeSubmitPrompt", "beforeShellExecution"),
         "devin": (".config/devin/config.json", "UserPromptSubmit", "PreToolUse"),
         "copilot": (".copilot/hooks/local-ai-hub.json", "sessionStart", "preToolUse")}
HOOK_ONLY_HOSTS = {"opencode"}
SUPERPOWERS_VERSION = "7.0.1"
MAX_JSON_BYTES = 131072


def bounded_text(value: Any, name: str, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value.encode("utf-8")) > limit:
        raise ValueError(f"invalid or oversized {name}")
    return value


def checked_root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("explicit absolute repository root required")
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("repository root contains a link")
    if not path.is_dir():
        raise ValueError("repository root must exist")
    return path.resolve(strict=True)


def confined_path(root: Path, path: Path) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path outside repository root") from exc
    if ".." in relative.parts:
        raise ValueError("path outside repository root")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("path contains a link")
    if not path.resolve().is_relative_to(root):
        raise ValueError("path outside repository root")
    return path


def read_bytes(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> bytes:
    with path.open("rb") as source:
        value = source.read(max_bytes + 1)
    if len(value) > max_bytes:
        raise ValueError("file too large")
    return value


def read_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    value = json.loads(read_bytes(path, max_bytes=max_bytes).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def atomic_json(root: Path, path: Path, value: dict[str, Any]) -> None:
    confined_path(root, path)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("file too large")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = confined_path(root, path.with_name(f".tmp_{uuid.uuid4().hex}"))
    try:
        with temporary.open("xb") as target:
            os.chmod(temporary, 0o600)
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        confined_path(root, path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _command(arguments: list[str], *, windows: bool = False) -> str:
    if windows:
        # Host executes through its shell. Refuse cmd expansion/metacharacters;
        # quoting argv alone does not neutralize percent/bang expansion.
        if any(any(char in item for char in '\r\n"%!?^&|<>`$') for item in arguments):
            raise ValueError("unsupported shell characters in hook command paths")
        return " ".join('"' + item + '"' for item in arguments)
    return shlex.join(arguments)


class ManagedHostInstallation:
    """Preview/apply/rollback only owned project-local registration groups.

    Callers must authorize writes to the explicit root. Apply requires a fresh
    preview revision; rollback refuses edited owned groups and preserves custom
    groups/settings. No user/global config or trust file is modified.
    """

    def __init__(self, repo_root: str | Path, host: str, *, python: str | Path | None = None):
        if host not in HOSTS:
            raise ValueError("unsupported host; supported: codex, gemini_cli")
        self.root = checked_root(repo_root)
        self.host = host
        self.config_path = confined_path(self.root, self.root / HOSTS[host][0])
        self.manifest = confined_path(self.root, self.root / ".local-ai-hub/local/host-adapters" / f"{host}.json")
        self.python = Path(python or sys.executable)
        if not self.python.is_absolute() or not self.python.is_file():
            raise ValueError("existing absolute Python executable required")

    def _registrations(self) -> dict[str, list[dict[str, Any]]]:
        argv = [str(self.python), str(Path(__file__).resolve()), "--root", str(self.root), "--host", self.host]
        command = _command(argv, windows=os.name == "nt")
        handler: dict[str, Any] = {"type": "command", "command": command,
                                   "timeout": 5 if self.host == "codex" else 5000}
        if self.host == "codex":
            handler["commandWindows"] = _command(argv, windows=True)
        else:
            handler["name"] = "local-ai-hub-planner"
        events = ["SessionStart", HOSTS[self.host][1]]
        if self.host == "codex":
            events.extend(("SubagentStart", "PreToolUse", "PermissionRequest", "PostToolUse"))
        registrations: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            group: dict[str, Any] = {"hooks": [copy.deepcopy(handler)]}
            if event == "PermissionRequest":
                group["matcher"] = "Bash|apply_patch"
            registrations[event] = [group]
        return registrations

    def _state(self) -> tuple[dict, bytes, dict | None]:
        confined_path(self.root, self.config_path)
        confined_path(self.root, self.manifest)
        raw = read_bytes(self.config_path) if self.config_path.exists() else b""
        config = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
            raise ValueError("invalid host configuration")
        for groups in config.get("hooks", {}).values():
            if not isinstance(groups, list) or not all(isinstance(group, dict) for group in groups):
                raise ValueError("invalid host hook groups")
        manifest = read_json(self.manifest) if self.manifest.exists() else None
        if manifest is not None:
            expected_groups = self._registrations()
            if (set(manifest) != {"schema", "root", "host", "groups", "created_config", "created_hooks"}
                    or manifest.get("schema") != 1 or manifest.get("root") != str(self.root)
                    or manifest.get("host") != self.host or manifest.get("groups") != expected_groups
                    or type(manifest.get("created_config")) is not bool
                    or type(manifest.get("created_hooks")) is not bool):
                raise ValueError("invalid host registration ownership")
        return config, raw, manifest

    def preview(self) -> dict[str, Any]:
        config, raw, manifest = self._state()
        groups = self._registrations()
        revision = hashlib.sha256(raw + json.dumps([groups, manifest], sort_keys=True).encode()).hexdigest()
        installed = bool(manifest) and all(config.get("hooks", {}).get(event, []).count(group) == 1
                for event, entries in manifest["groups"].items() for group in entries)
        return {"success": True, "host": self.host, "repo_root": str(self.root),
                "config_path": str(self.config_path), "revision": revision,
                "installed": installed, "registrations": groups, "support_level": "advisory",
                "changes": [] if installed else [str(self.config_path), str(self.manifest)],
                "limitations": ["Host trust review and supported host version required; trust is never modified.",
                                "Configured hooks are advisory; authenticated host event coverage not verified.",
                                "Cloud orchestration and Antigravity are not supported by this adapter.",
                                "Superpowers installation/enablement must be checked separately."]}

    @contextmanager
    def _locked(self):
        lock = confined_path(self.root, self.manifest.with_suffix(".lock"))
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ValueError("host registration busy; do not retry an uncertain apply") from exc
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def apply(self, *, expected_revision: str) -> dict[str, Any]:
        with self._locked():
            preview = self.preview()
            if not isinstance(expected_revision, str) or expected_revision != preview["revision"]:
                raise ValueError("host configuration changed since preview")
            config, _raw, manifest = self._state()
            groups = preview["registrations"]
            if manifest:
                if not preview["installed"] or manifest["groups"] != groups:
                    raise ValueError("owned host hook modified; explicit rollback/review required")
                return {"success": True, "changed": False, "support_level": "advisory"}
            if any(group in config.get("hooks", {}).get(event, []) for event, entries in groups.items() for group in entries):
                raise ValueError("identical unowned registration exists; refuse adoption")
            manifest = {"schema": 1, "root": str(self.root), "host": self.host, "groups": groups,
                        "created_config": not self.config_path.exists(), "created_hooks": "hooks" not in config}
            for event, entries in groups.items():
                config.setdefault("hooks", {}).setdefault(event, []).extend(entries)
            # Persist ownership first. A failed config write leaves recoverable
            # ownership metadata, never an installed-but-unowned hook.
            atomic_json(self.root, self.manifest, manifest)
            try:
                atomic_json(self.root, self.config_path, config)
            except BaseException:
                self.manifest.unlink(missing_ok=True)
                raise
            return {"success": True, "changed": True, "support_level": "advisory",
                    "requires_host_trust_review": True, "config_path": str(self.config_path)}

    def rollback(self) -> dict[str, Any]:
        if not self.manifest.exists():
            return {"success": True, "changed": False}
        with self._locked():
            config, _raw, manifest = self._state()
            if manifest is None:
                return {"success": True, "changed": False}
            for event, entries in manifest["groups"].items():
                for group in entries:
                    if config.get("hooks", {}).get(event, []).count(group) != 1:
                        raise ValueError("owned host hook modified; rollback refused")
            for event, entries in manifest["groups"].items():
                for group in entries:
                    config["hooks"][event].remove(group)
                if not config["hooks"][event]:
                    del config["hooks"][event]
            if not config["hooks"] and manifest["created_hooks"]:
                del config["hooks"]
            if not config and manifest["created_config"]:
                self.config_path.unlink()
            else:
                atomic_json(self.root, self.config_path, config)
            self.manifest.unlink()
            return {"success": True, "changed": True}


def inspect_superpowers(host: str, source_root: str | Path | None = None) -> dict[str, Any]:
    """Check explicit installed package bytes; presence never proves host enablement."""
    if host not in HOSTS:
        return {"status": "unsupported", "compatible": False}
    result: dict[str, Any] = {"status": "not_checked", "compatible": False, "version_required": SUPERPOWERS_VERSION,
                              "host_enablement": "not_verified", "install_executed": False}
    if host == "gemini_cli":
        result["install_argv"] = ["gemini", "extensions", "install", "https://github.com/obra/superpowers", "--ref", "v7.0.1"]
        result["installation"] = "Use native Gemini extension manager; preserve consent and restart/review extension status."
    else:
        result["installation"] = "Install Superpowers through Codex Plugins UI or a supported Codex plugin CLI. Hub does not automate Codex installation; verify exact 7.0.1 and host enablement."
    if source_root is None:
        return result
    if not Path(source_root).exists():
        candidate = Path(source_root)
        if not candidate.is_absolute():
            raise ValueError("explicit absolute Superpowers package root required")
        for part in (candidate, *candidate.parents):
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise ValueError("Superpowers package root contains a link")
        result["status"] = "missing"
        return result
    root = checked_root(source_root)
    manifest = confined_path(root, root / (".codex-plugin/plugin.json" if host == "codex" else "gemini-extension.json"))
    if not manifest.exists():
        result["status"] = "missing"
        return result
    data = read_json(manifest, max_bytes=16384)
    result["version_found"] = data.get("version")
    if data.get("name") != "superpowers" or data.get("version") != SUPERPOWERS_VERSION:
        result["status"] = "incompatible"
        return result
    required = ["skills/using-superpowers/SKILL.md"] + (["GEMINI.md"] if host == "gemini_cli" else [])
    for relative in required:
        path = confined_path(root, root / relative)
        if not path.is_file() or not read_bytes(path, max_bytes=65536).strip():
            result["status"] = "incomplete"
            return result
    result.update(status="compatible_on_disk", compatible=True,
                  manifest_sha256=hashlib.sha256(read_bytes(manifest)).hexdigest(), source_root=str(root))
    return result


def ensure_codex_superpowers(executable: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    """Ensure the supported Codex plugin is present without replacing existing plugins.

    The CLI has no version pin. Check the marketplace before installation and
    independently verify the installed version, bytes and enablement afterwards.
    An indeterminate or incompatible result is left for operator inspection.
    """
    import subprocess
    from local_ai_hub.process_utils import run_hidden

    root = checked_root(repo_root)
    binary = Path(executable)
    if not binary.is_absolute() or not binary.is_file() or binary.suffix.lower() in {".cmd", ".bat"}:
        raise ValueError("absolute native Codex executable required")
    plugin_id = "superpowers@openai-curated-remote"

    def command(*args: str) -> dict[str, Any]:
        result = run_hidden([str(binary), "plugin", *args], cwd=str(root), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60, max_output_bytes=8 * 1024 * 1024,
                            shell=False)
        if result.returncode != 0:
            raise ValueError(f"Codex plugin command failed with exit code {result.returncode}")
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("invalid Codex plugin response")
        return data

    def installed_status(data: dict[str, Any]) -> tuple[bool, bool]:
        entries = data.get("installed")
        if not isinstance(entries, list) or any(not isinstance(x, dict) for x in entries):
            raise ValueError("invalid Codex installed plugin inventory")
        found = [x for x in entries if x.get("name") == "superpowers" and x.get("installed") is True]
        for item in found:
            source = item.get("source")
            if item.get("version") == SUPERPOWERS_VERSION and item.get("enabled") is True and isinstance(source, dict):
                package_path = source.get("path") if source.get("source") == "local" else None
                if source.get("source") == "remote" and item.get("pluginId") == plugin_id:
                    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
                    package_path = codex_home / "plugins/cache/openai-curated-remote/superpowers" / SUPERPOWERS_VERSION
                try:
                    if package_path and inspect_superpowers("codex", package_path)["compatible"]:
                        return True, True
                except (OSError, ValueError):
                    pass
        return bool(found), False

    try:
        exists, compatible = installed_status(command("list", "--json"))
        if compatible:
            return {"success": True, "changed": False, "host_enablement": "enabled"}
        if exists:
            return {"success": False, "changed": False, "error": "existing Superpowers plugin requires review"}
        inventory = command("list", "--available", "--json")
        exists, compatible = installed_status(inventory)
        if compatible:
            return {"success": True, "changed": False, "host_enablement": "enabled"}
        if exists:
            return {"success": False, "changed": False, "error": "existing Superpowers plugin requires review"}
        available = inventory.get("available")
        if not isinstance(available, list) or any(not isinstance(x, dict) for x in available):
            raise ValueError("invalid Codex marketplace inventory")
        candidates = [x for x in available if x.get("pluginId") == plugin_id]
        if len(candidates) != 1 or candidates[0].get("version") != SUPERPOWERS_VERSION:
            return {"success": False, "changed": False, "error": "supported Superpowers version unavailable"}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"success": False, "changed": False, "error": f"Codex plugin inspection failed: {exc}"}

    try:
        command("add", plugin_id, "--json")
        _, compatible = installed_status(command("list", "--json"))
        if compatible:
            return {"success": True, "changed": True, "host_enablement": "enabled"}
        error = "installed Superpowers version, bytes or enablement did not match"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        error = f"Codex plugin installation or verification failed: {exc}"
    return {"success": False, "changed": None, "outcome_unknown": True,
            "partial_install_review_required": True, "error": error}


def ensure_gemini_superpowers(executable: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    """Run the pinned extension installer through the detected native Gemini CLI."""
    import shutil

    binary = Path(executable)
    if not binary.is_absolute() or not binary.is_file():
        raise ValueError("absolute Gemini executable required")
    entrypoint = None
    if binary.suffix.lower() in {".cmd", ".bat"}:
        package = binary.parent / "node_modules" / "@google" / "gemini-cli"
        manifest = read_json(package / "package.json", max_bytes=65536)
        if manifest.get("name") != "@google/gemini-cli":
            raise ValueError("unrecognized Gemini npm package")
        entry = manifest.get("bin")
        if isinstance(entry, dict):
            entry = entry.get("gemini")
        if not isinstance(entry, str) or not entry:
            raise ValueError("missing Gemini npm entrypoint")
        entrypoint = (package / entry).resolve()
        if not entrypoint.is_relative_to(package.resolve()) or entrypoint.suffix not in {".js", ".mjs", ".cjs"}:
            raise ValueError("Gemini npm entrypoint escapes its package")
        node = shutil.which("node")
        if not node:
            raise ValueError("native Node executable required for Gemini npm installation")
        binary = Path(node).absolute().resolve()
    else:
        binary = binary.resolve()
    gemini_home = Path(os.environ.get("GEMINI_CLI_HOME", str(Path.home())))
    if not gemini_home.is_absolute():
        raise ValueError("GEMINI_CLI_HOME must be absolute")
    return install_superpowers("gemini_cli", repo_root=repo_root,
                               package_root=gemini_home / ".gemini" / "extensions" / "superpowers",
                               executable=binary, entrypoint=entrypoint,
                               operator_authorized=True, consent=True)


def install_superpowers(
    host: str, *, repo_root: str | Path, package_root: str | Path,
    executable: str | Path, entrypoint: str | Path | None = None,
    operator_authorized: bool = False, consent: bool = False,
) -> dict[str, Any]:
    """Explicit opt-in to native Gemini extension installation, never model pulls.

    Codex uses its official plugin UI. Gemini npm Windows wrappers may be .cmd;
    callers must supply node.exe plus the actual CLI JS entrypoint instead.
    Existing incompatible or customized packages are never overwritten.
    """
    import subprocess
    from local_ai_hub.process_utils import run_hidden
    if operator_authorized is not True:
        raise ValueError("explicit operator authorization required")
    if host == "codex":
        raise ValueError("Hub does not support automatic Codex Superpowers installation; use the Codex plugin manager")
    if host != "gemini_cli":
        raise ValueError("unsupported host")
    root = checked_root(repo_root)
    dependency = inspect_superpowers(host, package_root)
    if dependency["compatible"]:
        return {"success": True, "changed": False, "dependency": dependency}
    if dependency["status"] != "missing":
        raise ValueError("existing Superpowers package requires operator review; no overwrite")
    package = Path(package_root)
    if package.exists() and any(package.iterdir()):
        raise ValueError("existing package directory requires operator review; no overwrite")
    binary = Path(executable)
    if not binary.is_absolute() or not binary.is_file() or binary.is_symlink() or binary.suffix.lower() in {".cmd", ".bat"}:
        raise ValueError("absolute native host executable required; .cmd/.bat wrappers unsupported")
    argv = [str(binary)]
    if entrypoint is not None:
        script = Path(entrypoint)
        if not script.is_absolute() or not script.is_file() or script.is_symlink() or script.suffix not in {".js", ".mjs", ".cjs"}:
            raise ValueError("absolute native host JavaScript entrypoint required")
        argv.append(str(script))
    argv.extend(dependency["install_argv"][1:])
    if consent is not True:
        return {"success": False, "changed": False, "requires_consent": True,
                "install_argv": argv, "dependency": dependency}
    argv.append("--consent")
    try:
        completed = run_hidden(argv, cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=60, max_output_bytes=65536, shell=False)
    except subprocess.TimeoutExpired:
        return {"success": False, "changed": None, "outcome_unknown": True,
                "partial_install_review_required": True,
                "error": "Superpowers install timed out; inspect native extension state before any retry"}
    try:
        dependency = inspect_superpowers(host, package_root)
    except (OSError, ValueError) as exc:
        return {"success": False, "changed": None, "outcome_unknown": True,
                "partial_install_review_required": True, "exit_code": completed.returncode,
                "error": f"Superpowers installation could not be inspected: {exc}"}
    dependency["install_executed"] = True
    success = completed.returncode == 0 and dependency["compatible"]
    return {"success": success,
            "changed": True if success else None, "outcome_unknown": not success,
            "partial_install_review_required": not success, "exit_code": completed.returncode,
            "dependency": dependency, "host_activation": "not_verified"}


def _trigger_repo_warmup(root: Path) -> None:
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:11435/api/repo/preprocess",
            data=json.dumps({"root": str(root)}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "HostHook"},
        )
        urllib.request.urlopen(req, timeout=0.5)
    except Exception:
        pass


def _active_plan_summary(root: Path) -> str:
    plans_dir = root / ".local-ai-hub" / "plans"
    if not plans_dir.is_dir():
        return ""
    try:
        active_plans: list[dict[str, Any]] = []
        for plan_file in sorted(plans_dir.glob("*.plan.json")):
            if plan_file.is_symlink() or getattr(plan_file, "is_junction", lambda: False)():
                continue
            if plan_file.stat().st_size > MAX_JSON_BYTES:
                continue
            try:
                data = json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("lifecycle") == "active":
                plan_id = str(data.get("id") or plan_file.stem)
                desc = str(data.get("description") or "").strip()
                tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
                active_tasks: list[str] = []
                for tid, tinfo in tasks.items():
                    if isinstance(tinfo, dict) and tinfo.get("work_status") in ("in_progress", "active"):
                        t_desc = str(tinfo.get("description") or tid).strip()[:80]
                        active_tasks.append(f"{tid} ({t_desc})")
                active_plans.append({
                    "id": plan_id,
                    "desc": desc[:150],
                    "active_tasks": active_tasks[:3],
                })
        if not active_plans:
            return ""
        lines: list[str] = []
        for p in active_plans[:2]:
            lines.append(f"- Plan '{p['id']}': {p['desc']}")
            if p["active_tasks"]:
                lines.append(f"  Active tasks: {', '.join(p['active_tasks'])}")
        return "\n".join(lines)
    except Exception:
        return ""


def _check_codex_tool_use(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    name = (tool_name or "").lower().strip()
    cmd = str(args.get("command") or args.get("CommandLine") or "").strip()

    # 1. Bare pytest check across 17,500+ tests
    if cmd and re.search(r"\b(?:python\s+(?:-m\s+)?pytest|pytest)\b", cmd, re.IGNORECASE):
        parts = cmd.split()
        try:
            pt_idx = next(i for i, part in enumerate(parts) if "pytest" in part.lower())
            subargs = parts[pt_idx + 1:]
            has_selector = any(not a.startswith("-") or a in ("-m", "-k", "--run-all") for a in subargs)
            if not has_selector and subargs in ([], ["-q"], ["-v"], ["-s"]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"Unconstrained bare pytest '{cmd}' across 17,500+ tests is blocked to prevent freezing. "
                        f"Use targeted selectors (e.g. pytest -m 'fast' or a specific test file path)."
                    ),
                }
        except Exception:
            pass

    # 2. Unconstrained grep/find/search check
    if cmd:
        unconstrained = [
            re.compile(r"\bdir\s+.*(?:\/s|\/S)", re.IGNORECASE),
            re.compile(r"\bfindstr\s+.*(?:\/s|\/S)", re.IGNORECASE),
            re.compile(r"\bfind\s+(?:\.|\/|[a-zA-Z]:)[^\n|;]*\s+-name\b", re.IGNORECASE),
            re.compile(r"\bgrep\s+-[a-zA-Z]*[rR]\b"),
        ]
        for p in unconstrained:
            if p.search(cmd):
                return {
                    "decision": "deny",
                    "reason": (
                        f"Unconstrained repository search '{cmd}' is blocked by Token Economy. "
                        f"Use local_ai_repo(action='search'|'code_index') instead."
                    ),
                }

    # 3. Direct full-file read check (> 80 lines)
    path_str = str(args.get("path") or args.get("file_path") or args.get("Path") or "")
    if name in ("view_file", "read_file", "read") and path_str:
        p = Path(path_str)
        if p.is_file() and p.name.lower() not in {"agents.md", "pyproject.toml", ".gitignore"}:
            start = args.get("start_line") or args.get("line_start")
            end = args.get("end_line") or args.get("line_end")
            if start is None and end is None:
                try:
                    with p.open("r", encoding="utf-8", errors="ignore") as f:
                        lines = sum(1 for _ in zip(f, range(81)))
                        if lines > 80:
                            return {
                                "decision": "deny",
                                "reason": (
                                    f"Direct full read of '{p.name}' (> 80 lines) is blocked by Token Economy. "
                                    f"Specify a targeted slice or use local_ai_repo(action='context')."
                                ),
                            }
                except Exception:
                    pass

    # Empty output leaves the host's own approval and permission flow intact.
    return {}


def _normalize_cursor_event(payload: Any) -> Any:
    """Keep only Cursor's workspace/session or bounded shell-hook fields."""
    if not isinstance(payload, dict):
        return payload
    event = payload.get("hook_event_name")
    if event == "afterFileEdit":
        file_path = payload.get("file_path")
        if (
            not isinstance(file_path, str)
            or len(file_path.encode("utf-8")) > 4096
            or not Path(file_path).is_absolute()
        ):
            raise ValueError("invalid Cursor afterFileEdit path")
        path = Path(file_path)
        return {
            "hook_event_name": "PostToolUse",
            "session_id": "",
            "cwd": str(path.parent),
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path)},
        }
    if (
        event == "PostToolUse"
        and payload.get("tool_name") == "Edit"
        and isinstance(payload.get("tool_input"), dict)
        and isinstance(payload.get("cwd"), str)
    ):
        return payload
    if event == "beforeShellExecution":
        normalized_args = payload.get("tool_args")
        normalized_command = normalized_args.get("command") if isinstance(normalized_args, dict) else None
        if (
            payload.get("tool_name") == "Bash"
            and isinstance(normalized_command, str)
            and len(normalized_command.encode("utf-8")) <= 16000
        ):
            return payload
        command = payload.get("command")
        if not isinstance(command, str) or len(command.encode("utf-8")) > 16000:
            raise ValueError("invalid Cursor shell command")
        return {
            "hook_event_name": event,
            "session_id": None,
            "cwd": payload.get("cwd"),
            "tool_name": "Bash",
            "tool_args": {"command": command},
        }
    if payload.get("hook_event_name") == "SessionStart" and "cwd" in payload and "session_id" in payload:
        return payload
    if payload.get("hook_event_name") != "sessionStart":
        raise ValueError("unsupported Cursor hook event")
    roots = payload.get("workspace_roots")
    session_id = payload.get("conversation_id")
    if not isinstance(roots, list) or len(roots) != 1:
        raise ValueError("Cursor hook requires exactly one workspace root")
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "cwd": roots[0],
    }


def _normalize_gemini_cli_event(payload: Any) -> Any:
    """Retain only Gemini CLI's bounded lifecycle and tool-hook fields."""
    if not isinstance(payload, dict):
        raise ValueError("invalid Gemini CLI hook event")
    event = payload.get("hook_event_name")
    if event == "AfterTool":
        event = "PostToolUse"
    if event not in {"SessionStart", "BeforeAgent", "BeforeTool", "PostToolUse"}:
        raise ValueError("unsupported Gemini CLI hook event")
    normalized = {
        "hook_event_name": event,
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
    }
    if event in {"BeforeTool", "PostToolUse"}:
        normalized["tool_name"] = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = payload.get("tool_args")
        normalized["tool_args"] = tool_input if isinstance(tool_input, dict) else {}
    return normalized


def _normalize_copilot_event(payload: Any) -> Any:
    """Keep only Copilot's local hook identity and tool fields; never persist prompts."""
    if not isinstance(payload, dict):
        raise ValueError("invalid Copilot hook event")
    event = payload.get("hook_event_name") or payload.get("hookEventName")
    if event == "preToolUse":
        event = "PreToolUse"
    elif event == "postToolUse":
        event = "PostToolUse"
    elif event == "sessionStart":
        event = "SessionStart"
    elif event is None and ("toolName" in payload or "tool_name" in payload):
        event = "PreToolUse"
    elif event is None and ("sessionId" in payload or "session_id" in payload):
        event = "SessionStart"
    if event not in {"SessionStart", "PreToolUse", "PostToolUse"}:
        raise ValueError("unsupported Copilot hook event")
    normalized = {
        "hook_event_name": event,
        "session_id": payload.get("session_id", payload.get("sessionId")),
        "cwd": payload.get("cwd"),
    }
    if event in {"PreToolUse", "PostToolUse"}:
        normalized["tool_name"] = payload.get("tool_name", payload.get("toolName"))
        tool_input = payload.get("tool_input", payload.get("toolArgs"))
        if not isinstance(tool_input, dict):
            tool_input = payload.get("tool_args")
        normalized["tool_args"] = tool_input if isinstance(tool_input, dict) else {}
    return normalized


def _normalize_opencode_event(payload: Any) -> Any:
    """Accept bounded permission, pre-tool, post-edit, session start and user prompt submit fields forwarded by OpenCode."""
    if not isinstance(payload, dict) or payload.get("hook_event_name") not in (
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest"
    ):
        raise ValueError("unsupported OpenCode hook event")
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd")
    if event == "SessionStart":
        return {"hook_event_name": "SessionStart", "session_id": session_id, "cwd": cwd}
    if event == "UserPromptSubmit":
        prompt_val = payload.get("prompt") or payload.get("text") or ""
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "cwd": cwd,
            "prompt": str(prompt_val)[:4096],
        }
    if event == "PermissionRequest":
        if payload.get("tool_name") != "Bash":
            raise ValueError("unsupported OpenCode permission action")
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str) or not command.strip() or len(command.encode("utf-8")) > 4096:
            raise ValueError("invalid OpenCode shell permission command")
        return {
            "hook_event_name": "PermissionRequest",
            "session_id": session_id,
            "cwd": cwd,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    if event == "PreToolUse":
        tool_name = str(payload.get("tool_name") or "").strip()
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session_id,
            "cwd": cwd,
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        raise ValueError("invalid OpenCode tool event")
    path_value = next((tool_input[key] for key in ("file_path", "filePath", "path", "target")
                       if isinstance(tool_input.get(key), str)), None)
    if not isinstance(path_value, str) or len(path_value.encode("utf-8")) > 4096 or not Path(path_value).is_absolute():
        raise ValueError("invalid OpenCode edited file path")
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "cwd": cwd,
        "tool_name": tool_name,
        "tool_input": {"file_path": path_value},
    }


def _format_host_tool_decision(host: str, decision: dict[str, Any]) -> dict[str, Any]:
    """Translate internal policy results without emitting implicit host approvals."""
    if host == "cursor":
        if decision.get("decision") == "deny":
            reason = str(decision.get("reason") or "Blocked by Local AI Hub policy.")
            return {"permission": "deny", "user_message": reason, "agent_message": reason}
        return {
            "permission": "ask",
            "user_message": "Local AI Hub policy passed; confirm shell execution in Cursor.",
            "agent_message": "The Hub found no bounded-policy violation; host approval is still required.",
        }
    if decision.get("decision") != "deny":
        return {}
    reason = str(decision.get("reason") or "Blocked by Local AI Hub policy.")
    if host in {"codex", "claude"}:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}
    if host == "copilot":
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    if host == "devin":
        return {"decision": "block", "reason": reason}
    return decision


def handle_host_event(repo_root: str | Path, host: str, payload: Any) -> dict[str, Any]:
    """Validate hook envelope and enforce project and token-economy safety policies."""
    if host == "cursor":
        payload = _normalize_cursor_event(payload)
    elif host == "gemini_cli":
        payload = _normalize_gemini_cli_event(payload)
    elif host == "copilot":
        payload = _normalize_copilot_event(payload)
    elif host == "devin":
        if not isinstance(payload, dict):
            raise ValueError("invalid Devin hook event")
        payload = dict(payload)
        payload.setdefault("cwd", os.environ.get("DEVIN_PROJECT_DIR"))
    elif host == "opencode":
        payload = _normalize_opencode_event(payload)
    root = checked_root(repo_root)
    if host not in HOSTS and host not in HOOK_ONLY_HOSTS or not isinstance(payload, dict):
        raise ValueError("unsupported host or invalid event payload")
    if len(payload) > 64:
        raise ValueError("event payload has too many fields")
    event = payload.get("hook_event_name")
    bounded_text(
        payload.get("session_id") if payload.get("session_id") is not None else "",
        "session_id", 200,
        allow_empty=(host == "cursor" and event in {"beforeShellExecution", "PostToolUse"})
        or host == "opencode",
    )
    cwd = bounded_text(payload.get("cwd"), "cwd", 4096)
    if checked_root(cwd) != root:
        raise ValueError("event repository root mismatch")
    valid_events = ({"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest"} if host == "opencode" else
                    {"PostToolUse"} if host in HOOK_ONLY_HOSTS else
                    {"SessionStart", HOSTS[host][1], HOSTS[host][2], "PreToolUse", "PostToolUse"})
    if host in {"codex", "claude"}:
        valid_events.add("SubagentStart")
        valid_events.add("PermissionRequest")
    if event not in valid_events:
        raise ValueError("unsupported hook event")

    if host in {"codex", "claude"} and event == "UserPromptSubmit":
        return {"hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": (
                "When Local AI Hub MCP is available, use it for indexed repository evidence and typed Laya advice "
                "on bounded routing, context, or retrieval decisions. Treat Laya output as advisory; host "
                "permissions and deterministic validation remain authoritative."
            ),
        }}

    if host in {"codex", "claude"} and event == "SubagentStart":
        return {"hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": (
                "When Local AI Hub MCP is available, use indexed repository evidence and typed Laya advice "
                "for bounded routing, context, and retrieval decisions. Treat Laya output as advisory; "
                "host permissions and deterministic validation remain authoritative."
            ),
        }}

    if host in {"codex", "claude"} and event == "PermissionRequest":
        tool_args = payload.get("tool_input")
        if not isinstance(tool_args, dict):
            tool_args = {}
        decision = _check_codex_tool_use(str(payload.get("tool_name") or ""), tool_args)
        if decision.get("decision") == "deny":
            return {"hookSpecificOutput": {
                "hookEventName": event,
                "decision": {
                    "behavior": "deny",
                    "message": str(decision.get("reason") or "Blocked by Local AI Hub policy."),
                },
            }}
        # Never approve here: Codex's own approval flow remains authoritative.
        return {}

    if host == "opencode" and event == "PermissionRequest":
        tool_args = payload["tool_input"]
        decision = _check_codex_tool_use("Bash", tool_args)
        if decision.get("decision") == "deny":
            return {"decision": "deny", "reason": str(decision.get("reason") or "Blocked by Local AI Hub policy.")}
        # OpenCode retains its configured allow/ask flow for all other commands.
        return {}

    if host == "opencode" and event in ("SessionStart", "UserPromptSubmit"):
        _trigger_repo_warmup(root)
        plan_summary = _active_plan_summary(root)
        parts = [
            "Local AI Hub Proactive Context: Local AI Hub is active and monitoring repository integrity.",
        ]
        if plan_summary:
            parts.append(f"Active project plan:\n{plan_summary}")
        parts.append(
            "Guidance: Prioritize Local AI Hub MCP tools (local_ai_repo, local_ai_artifact, local_ai_coord) "
            "over broad unconstrained directory searches. Mint authentic receipts via "
            "local_ai_coord(action='verify_completion') before completing goals."
        )
        return {"additionalContext": "\n\n".join(parts)}

    if host == "opencode" and event == "PreToolUse":
        tool_name = str(payload.get("tool_name") or "")
        tool_args = payload.get("tool_input") or {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        decision = _check_codex_tool_use(tool_name, tool_args)
        if decision.get("decision") == "deny":
            return {"decision": "deny", "reason": str(decision.get("reason") or "Blocked by Local AI Hub policy.")}
        name_l = tool_name.lower().strip()
        if name_l in ("edit", "write", "apply_patch", "edit_file", "write_file", "replace"):
            path_val = next((tool_args[k] for k in ("file_path", "filePath", "path", "target")
                             if isinstance(tool_args.get(k), str)), None)
            if path_val:
                try:
                    confined_path(root, Path(path_val))
                except ValueError as exc:
                    return {"decision": "deny", "reason": f"Target edit path outside repository root: {exc}"}
        return {}

    if host == "gemini_cli" and event == "BeforeAgent":
        return {"hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": (
                "When Local AI Hub MCP is available, use indexed repository evidence and typed Laya advice "
                "for bounded routing, context, and retrieval decisions. Laya is advisory; deterministic "
                "validation and host permissions remain authoritative."
            ),
        }}

    if event == "SessionStart":
        _trigger_repo_warmup(root)
        if host in {"gemini_cli", "claude"}:
            return {"hookSpecificOutput": {
                "additionalContext": (
                    "When Local AI Hub MCP is available, use indexed repository evidence and typed Laya advice "
                    "for bounded routing, context, and retrieval decisions. Laya is advisory; deterministic "
                    "validation and host permissions remain authoritative."
                ),
            }}
        return {}

    if host not in HOOK_ONLY_HOSTS and event in (HOSTS[host][2], "PreToolUse", "BeforeTool"):
        tool_call = payload.get("tool_call") or payload.get("toolCall") or payload.get("tool") or {}
        tool_name = str(tool_call.get("name") or payload.get("tool_name") or "")
        tool_args = tool_call.get("args") or payload.get("tool_args") or payload.get("tool_input") or {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        return _format_host_tool_decision(host, _check_codex_tool_use(tool_name, tool_args))

    if event == "PostToolUse":
        tool_call = payload.get("tool_call") or payload.get("toolCall") or payload.get("tool") or {}
        tool_name = str(tool_call.get("name") or payload.get("tool_name") or "").lower()
        tool_args = tool_call.get("args") or payload.get("tool_args") or payload.get("tool_input") or {}
        path_str = (
            tool_args.get("path") or tool_args.get("Path") or tool_args.get("file_path")
            or tool_args.get("filePath")
        )
        if path_str and tool_name in ("create", "edit", "write", "patch", "apply_patch", "edit_file", "write_file", "replace"):
            try:
                if host == "opencode":
                    path_str = str(confined_path(root, Path(path_str)))
                from local_ai_hub.shadow_compiler import shadow_check
                receipt = shadow_check(path_str, root=root)
                if host in {"claude", "devin", "copilot", "opencode"} and isinstance(receipt, dict):
                    findings: list[str] = []
                    if receipt.get("syntax_ok") is False:
                        findings.append(f"Static check found a syntax error in {Path(path_str).name}.")
                    violations = receipt.get("violations")
                    if isinstance(violations, list):
                        for violation in violations:
                            if isinstance(violation, dict) and violation.get("severity") == "high":
                                message = str(violation.get("message") or "high-severity invariant failed")[:300]
                                findings.append(f"Static check: {message}")
                                if len(findings) >= 3:
                                    break
                    if findings:
                        context = "\n".join(findings)
                        if host == "copilot":
                            return {"additionalContext": context}
                        if host == "opencode":
                            return {"additionalContext": context}
                        return {"hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": context,
                        }}
            except Exception:
                pass
        return {}

    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub project host hook")
    parser.add_argument("--root", help="explicit repository root; otherwise use the hook event cwd")
    parser.add_argument("--host", choices=(*HOSTS, *HOOK_ONLY_HOSTS), required=True)
    parser.add_argument(
        "--event", choices=("afterFileEdit", "beforeShellExecution", "preToolUse", "postToolUse", "PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "UserPromptSubmit"),
    )
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(65537)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("event payload too large")
        payload = json.loads(raw)
        if args.event is not None and isinstance(payload, dict):
            payload["hook_event_name"] = args.event
        if args.host == "cursor":
            payload = _normalize_cursor_event(payload)
        root = args.root or (payload.get("cwd") if isinstance(payload, dict) else None)
        if not root and args.host == "devin":
            root = os.environ.get("DEVIN_PROJECT_DIR")
        if not isinstance(root, str) or not root:
            raise ValueError("hook event must supply cwd when --root is omitted")
        output = handle_host_event(root, args.host, payload)
    except (ValueError, OSError, RecursionError) as exc:
        # Hook infrastructure errors emit no decision; the host keeps its own permission flow.
        if args.host == "devin":
            print(json.dumps({
                "decision": "block",
                "reason": f"Local AI Hub could not evaluate the Devin hook event: {exc}",
            }))
        else:
            print("{}")
        return 0
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
