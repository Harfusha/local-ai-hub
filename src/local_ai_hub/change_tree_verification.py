"""Local, explicitly configured checks on independently materialized Git trees.

An exact tree receipt is not an Agent OS task-completion receipt. Commands run
as the invoking user; the temporary checkout is not an OS security sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

from .change_commit_sequence import _entries, parent_raw_to_index
from .change_index_tree import index_tree_oid
from .change_semantics import _blob_matches
from .process_utils import clean_git_env, run_hidden

_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_FILE = 8 * 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_MAX_ENTRIES = 10000
_TTL = 3600


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def commit_policy(root: str, manifest: Any = None, *, require_manifest: bool = False) -> dict[str, Any]:
    """Resolve shared project verification rules without executing project commands."""
    from .project_config import CommandDefinition, resolve_project_config

    resolution = resolve_project_config(root)
    if resolution.error_codes:
        raise ValueError("Invalid project configuration; cannot resolve Git commit policy")
    settings = resolution.settings
    rule = settings.verification_rules.get("git_commit")
    policy = {"required": rule is not None, "config_digest": resolution.config_digest,
              "command_aliases": list(rule) if isinstance(rule, tuple) else []}
    if rule is None:
        return policy
    if not isinstance(rule, tuple) or not 1 <= len(rule) <= 4:
        raise ValueError("git_commit policy requires 1–4 structured command aliases")
    expected = []
    for alias in rule:
        command = settings.commands.get(alias)
        if not isinstance(command, CommandDefinition) or command.env_references or not command.argv:
            raise ValueError("Git commit policy requires structured argv without injected environment")
        argv = list(command.argv)
        if not all(argv) or not argv[0]:
            raise ValueError("Invalid Git commit policy argv")
        if not Path(argv[0]).is_absolute():
            if Path(argv[0]).name != argv[0] or "/" in argv[0] or "\\" in argv[0]:
                raise ValueError("Git commit policy executable must be a name or absolute path")
            search = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                                     if Path(p).is_absolute())
            executable = shutil.which(argv[0], path=search)
            if not executable or not Path(executable).is_absolute():
                raise ValueError("Git commit policy executable unavailable")
            argv[0] = executable
        expected.append(argv)
    if require_manifest and (not isinstance(manifest, dict) or manifest.get("commands") != expected):
        raise ValueError("Verification manifest must exactly match the git_commit project policy")
    return policy


def verification_identity(manifest: Any) -> tuple[str, str, list[list[str]], dict[str, str]]:
    if not isinstance(manifest, dict) or set(manifest) != {"environment_id", "commands"}:
        raise ValueError("Verification manifest requires environment_id and commands")
    external_id, commands = manifest["environment_id"], manifest["commands"]
    if not isinstance(external_id, str) or not _HEX.fullmatch(external_id):
        raise ValueError("Supply an explicit environment capsule SHA-256")
    if not isinstance(commands, list) or not 1 <= len(commands) <= 4:
        raise ValueError("Supply 1–4 explicit verification argv arrays")
    executable_digests = []
    canonical = []
    for argv in commands:
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 32
                or any(not isinstance(a, str) or not a or len(a) > 4096 or "\0" in a for a in argv)
                or not Path(argv[0]).is_absolute()):
            raise ValueError("Verification commands require absolute executable paths and bounded argv")
        exe = Path(argv[0]).resolve(strict=True)
        if not exe.is_file() or exe.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("Unsupported verification executable")
        if os.name == "nt" and exe.suffix.lower() not in {".exe", ".com"}:
            raise ValueError("Windows verification executable must be native, not a shell script")
        h = hashlib.sha256()
        with exe.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        executable_digests.append(h.hexdigest())
        # Preserve invocation through a virtual environment or symlink; the
        # executable identity hashes the resolved target separately.
        canonical.append([argv[0], *argv[1:]])
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}}
    if "PATH" in env:
        env["PATH"] = os.pathsep.join(p for p in env["PATH"].split(os.pathsep) if Path(p).is_absolute())
    commands_id = _digest(canonical)
    environment_id = _digest({"operator_capsule": external_id, "executables": executable_digests,
                              "environment": env, "platform": platform.platform(), "machine": platform.machine()})
    return commands_id, environment_id, canonical, env


def _git(root: str, *args: str, maximum: int = 4 * 1024 * 1024) -> bytes:
    cp = run_hidden(["git", "--no-pager", *args], cwd=root, capture_output=True, check=False,
                    stdin=subprocess.DEVNULL, timeout=20, max_output_bytes=maximum,
                    env=clean_git_env(extra_env={"GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                                                 "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}))
    if cp.returncode or getattr(cp, "stdout_truncated", False) or getattr(cp, "stderr_truncated", False):
        raise ValueError("Git tree materialization failed")
    return cp.stdout


def _materialize(root: str, entries: dict[bytes, tuple[bytes, bytes]], directory: Path, deadline: float) -> None:
    if len(entries) > _MAX_ENTRIES:
        raise ValueError("Tree exceeds verification entry budget")
    total = 0
    normalized: dict[str, str] = {}
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    for raw_path, (mode, raw_oid) in sorted(entries.items()):
        if time.monotonic() >= deadline:
            raise ValueError("Verification time budget exceeded")
        if mode not in {b"100644", b"100755"}:
            raise ValueError("Symlinks and submodules require a dedicated external verification environment")
        path = os.fsdecode(raw_path)
        parts = path.split("/")
        if any(not p or p in {".", ".."} or p.casefold() == ".git" or "\\" in p or ":" in p
               or p.endswith((" ", ".")) or p.split(".", 1)[0].casefold() in reserved
               or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or c in '<>|?*"' for c in p) for p in parts):
            raise ValueError("Unsupported materialization path")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            key = unicodedata.normalize("NFC", prefix).casefold()
            if key in normalized and normalized[key] != prefix:
                raise ValueError("Case or Unicode-colliding paths require external verification")
            normalized[key] = prefix
        target = directory.joinpath(*parts)
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Materialization path escaped")
        oid = raw_oid.decode("ascii")
        size = int(_git(root, "cat-file", "-s", oid, maximum=4096).strip())
        if not 0 <= size <= _MAX_FILE or total + size > _MAX_TOTAL:
            raise ValueError("Tree exceeds verification byte budget")
        content = _git(root, "cat-file", "blob", oid, maximum=max(1024, size + 1))
        if len(content) != size or not _blob_matches(content, oid):
            raise ValueError("Materialized blob identity mismatch")
        total += size
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
        if mode == b"100755":
            target.chmod(0o755)


def verify_sequence(root: str, preview: dict[str, Any], manifest: Any, journal: Any, *, rerun: bool = False) -> dict[str, Any]:
    if preview.get("success") is not True:
        return preview
    try:
        policy = commit_policy(root, manifest, require_manifest=True)
        if preview.get("project_commit_policy", policy) != policy:
            raise ValueError("Project commit policy changed after preview")
        command_id, environment_id, commands, base_env = verification_identity(manifest)
        parent = preview["parent_oid"]
        entries = _entries(_git(root, "ls-tree", "-r", "-z", parent), staged=False)
        target = _entries(_git(root, "ls-files", "--stage", "-z"), staged=True)
        if index_tree_oid(parent_raw_to_index(target), parent) != preview["tree_oid"]:
            raise ValueError("Index changed after sequence preview")
        deadline = time.monotonic() + 600
        results = []
        for step in preview["steps"]:
            for path in step["paths"]:
                raw = os.fsencode(path)
                if raw in target:
                    entries[raw] = target[raw]
                else:
                    entries.pop(raw, None)
            tree = index_tree_oid(parent_raw_to_index(entries), parent)
            if tree != step["tree_oid"]:
                raise ValueError("Intermediate tree changed after preview")
            existing = None if rerun else journal.current_tree_checks(
                root=root, tree=tree, command_id=command_id, environment_id=environment_id,
            )
            if existing:
                results.append({"tree_oid": tree, "receipt_id": existing, "reused": True})
                continue
            attempt = journal.begin_tree_checks(root=root, tree=tree, command_id=command_id,
                                                environment_id=environment_id)
            checks = []
            for argv in commands:
                # Start each command from a fresh tree; one check cannot modify
                # the input of a later check. Materialization is bounded.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Verification time budget exceeded")
                with tempfile.TemporaryDirectory(prefix="hub-tree-verify-") as temp:
                    base = Path(temp)
                    work = base / "tree"
                    home = base / "home"
                    scratch = base / "tmp"
                    for directory in (work, home, scratch):
                        directory.mkdir()
                    _materialize(root, entries, work, deadline)
                    env = {**base_env, "HOME": str(home), "USERPROFILE": str(home),
                           "TMP": str(scratch), "TEMP": str(scratch), "TMPDIR": str(scratch),
                           "GIT_CEILING_DIRECTORIES": str(base)}
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("Verification time budget exceeded")
                    cp = run_hidden(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, check=False, timeout=min(120.0, remaining),
                                    max_output_bytes=256 * 1024)
                    complete = not any(getattr(cp, flag, False) for flag in (
                        "stdout_truncated", "stderr_truncated", "cleanup_unconfirmed", "output_capture_unconfirmed",
                    ))
                    checks.append({"exit_code": cp.returncode, "output_complete": complete,
                                   "stdout_sha256": hashlib.sha256(cp.stdout or b"").hexdigest(),
                                   "stderr_sha256": hashlib.sha256(cp.stderr or b"").hexdigest()})
                    if cp.returncode or not complete:
                        return {"success": False, "error": "Verification command failed or output was incomplete",
                                "tree_oid": tree, "checks": checks, "verified_steps": results}
            if commit_policy(root, manifest, require_manifest=True) != policy:
                raise ValueError("Project commit policy changed during verification")
            if verification_identity(manifest)[:2] != (command_id, environment_id):
                raise ValueError("Observed verification environment changed")
            receipt = journal.record_tree_checks(root=root, tree=tree, command_id=command_id,
                                                 environment_id=environment_id, checks=checks, ttl=_TTL, attempt=attempt)
            results.append({"tree_oid": tree, "receipt_id": receipt, "checks": checks, "reused": False})
        current = require_sequence_receipts(root, preview, manifest, journal)
        if current != [step["receipt_id"] for step in results]:
            raise ValueError("Verification receipts changed during the sequence; refresh verification")
        return {"success": True, "verified_steps": results, "preview_digest": preview["preview_digest"],
                "commands_digest": command_id, "observed_environment_digest": environment_id,
                "reused_step_count": sum(step["reused"] for step in results),
                "executed_step_count": sum(not step["reused"] for step in results),
                "verification_status": "configured_commands_passed", "commit_ready": False,
                "limitations": "Not a sandbox, not proof of complete test coverage or external dependency immutability."}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": str(exc), "commit_ready": False}


def require_sequence_receipts(root: str, preview: dict[str, Any], manifest: Any, journal: Any) -> list[str]:
    policy = commit_policy(root, manifest, require_manifest=True)
    if preview.get("project_commit_policy", policy) != policy:
        raise ValueError("Project commit policy changed after preview")
    command_id, environment_id, _, _ = verification_identity(manifest)
    receipts = []
    for step in preview["steps"]:
        receipt = journal.current_tree_checks(root=root, tree=step["tree_oid"], command_id=command_id,
                                             environment_id=environment_id)
        if not receipt:
            raise ValueError("Missing or expired exact-tree verification; run sequence-verify")
        receipts.append(receipt)
    return receipts


def sequence_receipt_status(root: str, preview: dict[str, Any], manifest: Any, journal: Any) -> dict[str, Any]:
    """Inspect exact-tree receipts without running commands or authorizing publication."""
    if preview.get("success") is not True or preview.get("cleanup_unconfirmed"):
        return preview
    try:
        policy = commit_policy(root, manifest, require_manifest=True)
        if preview.get("project_commit_policy", policy) != policy:
            raise ValueError("Project commit policy changed after preview")
        command_id, environment_id, _, _ = verification_identity(manifest)
        statuses = []
        for step in preview["steps"]:
            receipt = journal.current_tree_checks(root=root, tree=step["tree_oid"],
                                                  command_id=command_id, environment_id=environment_id)
            statuses.append({"tree_oid": step["tree_oid"], "status": "current" if receipt else "missing_or_expired",
                             "receipt_id": receipt})
        if commit_policy(root, manifest, require_manifest=True) != policy or verification_identity(manifest)[:2] != (command_id, environment_id):
            raise ValueError("Policy or environment changed during inspection")
        missing = sum(step["status"] != "current" for step in statuses)
        return {"success": True, "preview_digest": preview["preview_digest"], "steps": statuses,
                "current_step_count": len(statuses) - missing, "missing_or_expired_step_count": missing,
                "all_receipts_current": missing == 0, "commands_digest": command_id,
                "observed_environment_digest": environment_id, "project_commit_policy": policy,
                "commit_ready": False, "commands_executed": False,
                "publication_rechecks_receipts": True}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": str(exc), "commit_ready": False, "commands_executed": False}
