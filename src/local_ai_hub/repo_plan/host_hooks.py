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
         "gemini_cli": (".gemini/settings.json", "BeforeAgent", "BeforeTool")}
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
        return {event: [{"hooks": [copy.deepcopy(handler)]}]
                for event in ("SessionStart", HOSTS[self.host][1])}

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
    package_existed = package.exists()
    try:
        completed = run_hidden(argv, cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=60, max_output_bytes=65536, shell=False)
    except subprocess.TimeoutExpired:
        return {"success": False, "changed": None, "outcome_unknown": True,
                "partial_install_review_required": package.exists() and any(package.iterdir()),
                "error": "Superpowers install timed out; inspect native extension state before any retry"}
    dependency = inspect_superpowers(host, package_root)
    dependency["install_executed"] = True
    success = completed.returncode == 0 and dependency["compatible"]
    partial = completed.returncode != 0 and package.exists() and (not package_existed or any(package.iterdir()))
    return {"success": success,
            "changed": True if success else (None if partial else False),
            "partial_install_review_required": partial, "exit_code": completed.returncode,
            "dependency": dependency, "host_activation": "not_verified"}


def handle_host_event(repo_root: str | Path, host: str, payload: Any) -> dict[str, Any]:
    """Consume documented prompt/session payloads; return bounded host context.

    Data from stdin is untrusted. This function does not certify that a host
    delivered it. It never reads transcripts, tool inputs, or arbitrary paths.
    """
    from local_ai_hub.repo_plan.host_adapters import SteeringManager
    root = checked_root(repo_root)
    if host not in HOSTS or not isinstance(payload, dict):
        raise ValueError("unsupported host or invalid event payload")
    if len(json.dumps(payload).encode()) > 65536:
        raise ValueError("event payload too large")
    session = bounded_text(payload.get("session_id"), "session_id", 200)
    cwd = bounded_text(payload.get("cwd"), "cwd", 4096)
    if checked_root(cwd) != root:
        raise ValueError("event repository root mismatch")
    event = payload.get("hook_event_name")
    if event not in {"SessionStart", HOSTS[host][1]}:
        raise ValueError("unsupported hook event")
    prompt = None
    if event == HOSTS[host][1]:
        prompt = bounded_text(payload.get("prompt"), "message", 16384)
    # Validate the complete payload before creating any local state.
    event_id = payload.get("turn_id") or payload.get("timestamp") or hashlib.sha256((prompt or "").encode()).hexdigest()
    bounded_text(event_id, "event_id", 300)
    # Repository-local binding selects identity only. The bridge validates the
    # actual Agent OS owner/root/branch and contracts before any reconciliation.
    from local_ai_hub.repo_plan.agent_bridge import TaskBindingManager
    bindings = TaskBindingManager(root)
    getter = getattr(bindings, "get_session_binding", None)
    binding = getter(session) if callable(getter) else None
    task_id = binding.task_id if binding is not None else None
    manager = SteeringManager(root)
    if prompt is not None:
        manager.capture_steering(session, prompt, task_id=task_id,
                                 author=f"{host}_hook", event_id=f"{host}:{event_id}")
    pending = manager.list_pending_steering(session_id=session)
    context = ("Local AI Hub planner: use canonical plan_* operations; reuse the existing plan/task. "
               "Prompt captures are private local advisory records, never verification receipts.")
    if binding is not None:
        context += f" Bound execution task {binding.task_id}; plan {binding.plan_id}, logical task {binding.plan_task_id}."
    if pending:
        ids = ", ".join(item["steering_id"] for item in pending[:8])
        context += (f" Pending steering for this session: {ids}. Before dependent edits reconcile the specification, "
                    "plan and actual task contract with plan_reconcile_steering; do not mark reconciled from acknowledgement alone.")
    output: dict[str, Any] = {"hookSpecificOutput": {"additionalContext": context}}
    if host == "codex":
        output["hookSpecificOutput"]["hookEventName"] = event
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub project host hook")
    parser.add_argument("--root", required=True)
    parser.add_argument("--host", choices=tuple(HOSTS), required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(65537)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("event payload too large")
        output = handle_host_event(args.root, args.host, json.loads(raw))
    except (ValueError, OSError, RecursionError) as exc:
        # A hook error is explicitly a failure; callers must not promote a file
        # or this response into host capability evidence.
        print(json.dumps({"systemMessage": f"Local AI Hub hook unavailable: {exc}"}))
        return 1
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
