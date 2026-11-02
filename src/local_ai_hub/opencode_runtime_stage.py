"""Stage an existing Python runtime for an experimental Windows sandbox.

The caller owns the empty destination and its cleanup. This copies installed
files only; it does not establish publisher trust or workspace isolation.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_MAX_BYTES = 256 * 1024 * 1024
_MAX_FILES = 20_000
_SKIP_DIRS = {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo"}
_OPENCODE_SHA256 = "0c346fdaf519d2f23a31d3b6cb9d65e369a72d77cac6f027b5e0a06376ec3a43"
_SESSION_ASSETS = (
    "opencode_goal/index.js", "opencode_goal/core.js", "opencode_goal/transport.js", "opencode_goal/package.json",
    "opencode_mcp/index.js", "opencode_mcp/package.json", "opencode_pipe_client.cjs",
    "opencode_sandbox_bootstrap.cjs", "opencode_stop_client.ps1",
)


def _reject_reparse_ancestors(path: Path, stop: Path) -> None:
    current = path
    while True:
        info = current.lstat()
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("runtime path contains a reparse point")
        if current == stop:
            return
        if current.parent == current:
            raise ValueError("runtime path is outside its declared root")
        current = current.parent


def _verify_signed_publisher(path: Path, publisher: str) -> None:
    system_root = os.environ.get("SystemRoot")
    if not system_root or publisher not in {"OpenJS Foundation", "Python Software Foundation"}:
        raise ValueError("signature verification configuration is unavailable")
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = ("$s=Get-AuthenticodeSignature -LiteralPath $env:LAH_VERIFY_FILE; "
              "if ($s.Status -ne 'Valid' -or -not $s.SignerCertificate -or "
              "$s.SignerCertificate.Subject -notmatch ('(^|,\\s*)O=' + [regex]::Escape($env:LAH_VERIFY_PUBLISHER) + '(,|$)')) { exit 1 }")
    env = {**os.environ, "LAH_VERIFY_FILE": str(path), "LAH_VERIFY_PUBLISHER": publisher,
           "PSModulePath": str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "Modules")}
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env, capture_output=True, timeout=20, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise ValueError("executable signature or publisher verification failed")


def stage_session_bundle(destination: Path, install_dir: Path, opencode: Path, node: Path) -> dict[str, Path]:
    """Stage checked session files into a caller-owned fresh directory.

    This is not an interactive launcher or a filesystem isolation boundary.
    """
    if os.name != "nt":
        raise ValueError("session staging requires Windows")
    root, install, cli, node_source = map(Path, (destination, install_dir, opencode, node))
    if not all(p.is_absolute() for p in (root, install, cli, node_source)) or not root.is_dir():
        raise ValueError("absolute existing session paths are required")
    _reject_reparse_ancestors(root, Path(root.anchor))
    for target in (root / "python", root / "src", root / "tools", root / "opencode.exe", root / "node.exe"):
        if target.exists() or target.is_symlink():
            raise FileExistsError("session staging destination contains existing files")
    sources = [(cli, root / "opencode.exe", 400 * 1024 * 1024), (node_source, root / "node.exe", 200 * 1024 * 1024)]
    sources.extend((install / "tools" / name, root / "tools" / name, 2 * 1024 * 1024) for name in _SESSION_ASSETS)
    for source, _, limit in sources:
        _reject_reparse_ancestors(source, Path(source.anchor))
        if not source.is_file() or source.stat().st_size > limit:
            raise ValueError("session asset is missing or exceeds its size limit")
    with cli.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != _OPENCODE_SHA256:
            raise ValueError("OpenCode executable does not match the pinned release")
    _verify_signed_publisher(node_source, "OpenJS Foundation")
    for source, target, _ in sources:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        with source.open("rb") as original, target.open("rb") as staged:
            if hashlib.file_digest(original, "sha256").digest() != hashlib.file_digest(staged, "sha256").digest():
                raise OSError("session asset differs from source")
    with (root / "opencode.exe").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != _OPENCODE_SHA256:
            raise ValueError("staged OpenCode executable failed verification")
    _verify_signed_publisher(root / "node.exe", "OpenJS Foundation")
    python = stage_runtime(root)
    return {"python": python, "node": root / "node.exe", "opencode": root / "opencode.exe",
            "client": root / "tools" / "opencode_pipe_client.cjs", "bootstrap": root / "tools" / "opencode_sandbox_bootstrap.cjs"}


def stage_runtime(destination: Path) -> Path:
    """Copy the current installed interpreter, MCP dependencies and Hub code.

    Creates new ``python`` and ``src`` trees; never replaces existing trees.
    Failures leave partial files in the caller-owned destination.
    """
    if os.name != "nt":
        raise ValueError("runtime staging requires Windows")
    root = Path(destination)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("an absolute, existing, non-reparse destination is required")
    _reject_reparse_ancestors(root, Path(root.anchor))
    runtime, source_target = root / "python", root / "src" / "local_ai_hub"
    if runtime.exists() or (root / "src").exists():
        raise FileExistsError("runtime staging destination is not empty")
    base = Path(sys.base_prefix)
    package = Path(__file__).parent
    runtime.mkdir()
    count = total = 0

    def copy_bounded(source, target):
        nonlocal count, total
        source = Path(source)
        info = source.lstat()
        if source.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or not source.is_file():
            raise ValueError("runtime source must be an ordinary file")
        count += 1
        total += info.st_size
        if count > _MAX_FILES or total > _MAX_BYTES:
            raise ValueError("runtime staging limit exceeded")
        shutil.copyfile(source, target)
        with source.open("rb") as original, Path(target).open("rb") as staged:
            if hashlib.file_digest(original, "sha256").digest() != hashlib.file_digest(staged, "sha256").digest():
                raise OSError("staged runtime file differs from source")
        return str(target)

    def ignore(directory, names):
        skipped = set()
        for name in names:
            entry = Path(directory) / name
            if name in _SKIP_DIRS or name.endswith(".pyc"):
                skipped.add(name)
            elif entry.is_symlink() or getattr(entry.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("runtime source contains a reparse point")
        return skipped

    for name in ("python.exe", "python3.dll", f"python{sys.version_info.major}{sys.version_info.minor}.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        source = base / name
        if source.is_file():
            copy_bounded(source, runtime / name)
    executable = runtime / "python.exe"
    if not executable.is_file():
        raise FileNotFoundError("base Python executable is unavailable")
    _verify_signed_publisher(executable, "Python Software Foundation")
    for name in ("Lib", "DLLs"):
        source = base / name
        if source.is_dir():
            shutil.copytree(source, runtime / name, ignore=ignore, copy_function=copy_bounded)
    site = runtime / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    todo = [("mcp", set(), None), ("watchdog", set(), None), ("PyJWT", {"crypto"}, None), ("jsonschema", set(), None)]
    selected = {}
    requested_extras = {}
    while todo:
        name, extras, specifier = todo.pop()
        key = canonicalize_name(name)
        distribution = selected.get(key) or importlib.metadata.distribution(name)
        if specifier and not specifier.contains(distribution.version, prereleases=True):
            raise ValueError(f"installed dependency version does not satisfy {name}")
        prior = requested_extras.get(key)
        if prior is not None and extras.issubset(prior):
            continue
        active_extras = (prior or set()) | extras
        requested_extras[key] = active_extras
        selected[key] = distribution
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if not requirement.marker or any(requirement.marker.evaluate({"extra": extra}) for extra in {"", *active_extras}):
                todo.append((requirement.name, set(requirement.extras), requirement.specifier))
    for distribution in selected.values():
        source_root = Path(distribution.locate_file("")).resolve(strict=True)
        for item in distribution.files or ():
            if ".." in item.parts:
                continue  # Installed console scripts can live outside site-packages.
            if item.is_absolute() or any(part == "." or ":" in part or "\\" in part for part in item.parts):
                raise ValueError("invalid distribution file path")
            if "__pycache__" in item.parts or item.suffix in {".pyc", ".pth"}:
                continue
            source = Path(distribution.locate_file(item))
            if not source.is_file():
                continue
            _reject_reparse_ancestors(source, source_root)
            resolved = source.resolve(strict=True)
            if not resolved.is_relative_to(source_root):
                raise ValueError("distribution file escaped its source root")
            output = site.joinpath(*item.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            copy_bounded(resolved, output)
    shutil.copytree(package, source_target, ignore=ignore, copy_function=copy_bounded)
    return executable
