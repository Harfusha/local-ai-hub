"""Experimental MXC policy construction; not yet integrated into launcher."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

_EXECUTOR_SHA256 = "090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a"
_NETWORK = {"egress": {"default": "deny"}, "ingress": {"default": "allow", "hostLoopback": "allow"}}


class SandboxError(RuntimeError):
    """Sandbox policy or executor could not be established."""


def _directory(value: Path) -> Path:
    path = Path(value).resolve(strict=True)
    if not path.is_dir() or path == Path(path.anchor):
        raise ValueError("sandbox paths must be existing non-root directories")
    return path


def build_policy(argv: list[str], *, cwd: Path, readwrite: list[Path], readonly: list[Path],
                 environment: dict[str, str], proxy_port: int, timeout_seconds: float) -> dict[str, Any]:
    if type(proxy_port) is not int or not 1 <= proxy_port <= 65535:
        raise ValueError("invalid proxy port")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 43200:
        raise ValueError("invalid sandbox timeout")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv):
        raise ValueError("invalid sandbox command")
    executable = Path(argv[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("sandbox executable must be an existing absolute file")
    if not isinstance(environment, dict) or any(not isinstance(k, str) or not k or "=" in k or "\0" in k or not isinstance(v, str) or "\0" in v for k, v in environment.items()):
        raise ValueError("invalid sandbox environment")
    if not {"SYSTEMROOT", "LOCALAPPDATA"}.issubset({key.upper() for key in environment}):
        raise ValueError("sandbox requires SYSTEMROOT and LOCALAPPDATA")
    working = _directory(cwd)
    rw = [_directory(path) for path in readwrite]
    ro = [_directory(path) for path in readonly]
    if not rw or not any(working.is_relative_to(root) for root in rw):
        raise ValueError("sandbox working directory requires write access")
    resolved_exe = executable.resolve(strict=True)
    if not any(resolved_exe.is_relative_to(root) for root in rw + ro):
        raise ValueError("sandbox executable must be inside an authorized directory")
    return {"version": "1.0.0", "containment": "processcontainer",
            "lifecycle": {"destroyOnExit": True, "preservePolicy": False},
            "process": {"commandLine": subprocess.list2cmdline(argv), "cwd": str(working),
                        "env": [f"{key}={value}" for key, value in sorted(environment.items())],
                        "inheritDefaultEnv": False, "timeout": int(timeout_seconds * 1000)},
            "filesystem": {"readwritePaths": list(map(str, rw)), "readonlyPaths": list(map(str, ro))},
            "network": {"egress": dict(_NETWORK["egress"]), "ingress": dict(_NETWORK["ingress"])},
            "runtimeConfig": {"networkProxy": f"http://127.0.0.1:{proxy_port}"}}


def run_sandbox(executor: Path, policy: dict[str, Any], *, cwd: Path, environment: dict[str, str],
                timeout_seconds: float, run_child: Callable[..., int]) -> int:
    target = Path(executor)
    try:
        if not target.is_absolute() or target.is_symlink() or not target.is_file() or target.stat().st_size > 64 * 1024 * 1024:
            raise SandboxError("cannot verify sandbox executor")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise SandboxError("cannot verify sandbox executor") from exc
    if digest != _EXECUTOR_SHA256:
        raise SandboxError("cannot verify sandbox executor")
    if (not isinstance(policy, dict) or set(policy) != {"version", "containment", "lifecycle", "process", "filesystem", "network", "runtimeConfig"}
            or policy.get("version") != "1.0.0" or policy.get("containment") != "processcontainer"
            or policy.get("lifecycle") != {"destroyOnExit": True, "preservePolicy": False}
            or policy.get("network") != _NETWORK
            or not isinstance(policy.get("runtimeConfig"), dict) or set(policy["runtimeConfig"]) != {"networkProxy"}
            or not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", str(policy["runtimeConfig"]["networkProxy"]))
            or int(policy["runtimeConfig"]["networkProxy"].rsplit(":", 1)[1]) > 65535):
        raise SandboxError("invalid sandbox policy")
    process = policy.get("process")
    if (not isinstance(process, dict) or set(process) != {"commandLine", "cwd", "env", "inheritDefaultEnv", "timeout"}
            or process.get("inheritDefaultEnv") is not False or process.get("cwd") != str(Path(cwd).resolve())
            or not isinstance(process.get("commandLine"), str) or not process["commandLine"] or "\0" in process["commandLine"]
            or not isinstance(process.get("env"), list)
            or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 43200
            or process.get("timeout") != int(timeout_seconds * 1000)):
        raise SandboxError("invalid sandbox process")
    filesystem = policy.get("filesystem")
    try:
        if (not isinstance(filesystem, dict) or set(filesystem) != {"readwritePaths", "readonlyPaths"}
                or not isinstance(filesystem["readwritePaths"], list) or not filesystem["readwritePaths"]
                or not isinstance(filesystem["readonlyPaths"], list)
                or any(not isinstance(path, str) or not path for path in filesystem["readwritePaths"] + filesystem["readonlyPaths"])):
            raise ValueError("invalid filesystem")
        writable = [_directory(Path(path)) for path in filesystem["readwritePaths"]]
        for path in filesystem["readonlyPaths"]:
            _directory(Path(path))
        if not any(Path(process["cwd"]).resolve().is_relative_to(root) for root in writable):
            raise ValueError("working directory is not writable")
        entries = process["env"]
        if any(not isinstance(item, str) or "=" not in item or item.startswith("=") or "\0" in item for item in entries):
            raise ValueError("invalid environment")
        names = [item.split("=", 1)[0].upper() for item in entries]
        if len(names) != len(set(names)) or not {"SYSTEMROOT", "LOCALAPPDATA"}.issubset(names):
            raise ValueError("invalid environment")
    except (OSError, ValueError) as exc:
        raise SandboxError("invalid sandbox policy") from exc
    # On Windows NamedTemporaryFile uses delete-on-close. Keep its handle open
    # while MXC reads it so a terminated launcher does not leave credentials.
    with tempfile.NamedTemporaryFile(prefix="lah-mxc-policy-", suffix=".json", mode="w+", encoding="utf-8", delete=True) as stream:
        json.dump(policy, stream, ensure_ascii=True)
        stream.flush()
        return run_child([str(target), stream.name], cwd=Path(cwd), env=environment, timeout=timeout_seconds)
