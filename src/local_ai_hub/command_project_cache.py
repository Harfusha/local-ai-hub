"""Project configuration and Git identity fingerprint helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def _project_config_cache_key(root: Path, state_dir: Path) -> str | None:
    """Fingerprint project config files and the exact Git HEAD without storing paths."""
    try:
        project_root = root.expanduser().resolve(strict=True)
        root_identity = hashlib.sha256(os.fsencode(str(project_root))).hexdigest()

        git_marker: Path | None = None
        for parent in (project_root, *project_root.parents):
            marker = parent / ".git"
            if marker.exists() or marker.is_symlink():
                git_marker = marker
                break

        common_dir: Path | None = None
        git_dir: Path | None = None
        git_revision: str | None = None
        git_signatures: list[tuple[str, tuple[Any, ...]]] = []
        primary_root: Path | None = None
        if git_marker is not None:
            marker_signature = _project_file_signature(git_marker)
            if marker_signature is None:
                return None
            git_signatures.append(("git-marker", marker_signature))
            if git_marker.is_dir():
                git_dir = git_marker.resolve(strict=True)
            elif git_marker.is_file():
                marker_text = git_marker.read_text(encoding="utf-8", errors="replace")[:4096]
                prefix, separator, raw_git_dir = marker_text.partition(":")
                if prefix.strip().lower() != "gitdir" or not separator:
                    return None
                git_dir = Path(raw_git_dir.strip())
                if not git_dir.is_absolute():
                    git_dir = git_marker.parent / git_dir
                git_dir = git_dir.resolve(strict=True)
            else:
                return None

            common_file = git_dir / "commondir"
            if common_file.exists():
                common_signature = _project_file_signature(common_file)
                if common_signature is None:
                    return None
                git_signatures.append(("git-common-dir", common_signature))
                raw_common_dir = common_file.read_text(
                    encoding="utf-8", errors="replace"
                )[:4096].strip()
                common_dir = Path(raw_common_dir)
                if not common_dir.is_absolute():
                    common_dir = git_dir / common_dir
                common_dir = common_dir.resolve(strict=True)
            else:
                common_dir = git_dir
            if common_dir.name.lower() != ".git":
                return None
            primary_root = common_dir.parent
            primary_marker = primary_root / ".git"
            if not primary_marker.is_dir() or primary_marker.resolve(strict=True) != common_dir:
                return None

            head_file = git_dir / "HEAD"
            head_signature = _project_file_signature(head_file)
            if head_signature is None:
                return None
            git_signatures.append(("git-head", head_signature))
            head_value = head_file.read_text(encoding="ascii", errors="replace")[:4096].strip()
            if head_value.startswith("ref: "):
                ref_name = head_value[5:].strip()
                parts = ref_name.split("/")
                if not ref_name.startswith("refs/") or any(part in {"", ".", ".."} for part in parts):
                    return None
                ref_file: Path | None = None
                for base in (git_dir, common_dir):
                    candidate = base.joinpath(*parts)
                    try:
                        resolved_ref = candidate.resolve(strict=True)
                        resolved_ref.relative_to(base.resolve(strict=True))
                        ref_file = resolved_ref
                        break
                    except (OSError, RuntimeError, ValueError):
                        continue
                if ref_file is not None:
                    ref_signature = _project_file_signature(ref_file)
                    if ref_signature is None:
                        return None
                    git_signatures.append(("git-ref", ref_signature))
                    git_revision = ref_file.read_text(encoding="ascii", errors="replace")[:128].strip()
                else:
                    packed_refs = common_dir / "packed-refs"
                    packed_signature = _project_file_signature(packed_refs)
                    if packed_signature is None:
                        return None
                    if packed_refs.stat().st_size > 4 * 1024 * 1024:
                        return None
                    git_signatures.append(("git-packed-refs", packed_signature))
                    packed_text = packed_refs.read_text(encoding="ascii", errors="replace")
                    for line in packed_text.splitlines():
                        fields = line.split(" ", 1)
                        if len(fields) == 2 and fields[1] == ref_name:
                            git_revision = fields[0]
                            break
            else:
                git_revision = head_value
            if not isinstance(git_revision, str) or not re.fullmatch(
                r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", git_revision
            ):
                return None

        config_paths = [
            ("project", project_root / ".local-ai.toml"),
            ("worktree", project_root / ".local-ai.worktree.toml"),
        ]
        if primary_root is not None and primary_root != project_root:
            config_paths.append(("primary", primary_root / ".local-ai.toml"))
        if common_dir is not None:
            config_paths.append(("machine", common_dir / "info" / "local-ai.toml"))
        config_signatures: list[tuple[str, tuple[Any, ...]]] = []
        for label, path in config_paths:
            signature = _project_file_signature(path, missing_ok=True)
            if signature is None:
                return None
            config_signatures.append((label, signature))
        state_identity = hashlib.sha256(
            os.fsencode(str(state_dir.expanduser().resolve(strict=False)))
        ).hexdigest()
        payload = {
            "root": root_identity,
            "state_dir": state_identity,
            "git_revision": git_revision,
            "git_signatures": git_signatures,
            "config_signatures": config_signatures,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    except (OSError, RuntimeError, ValueError, UnicodeError):
        return None


def _project_file_signature(
    path: Path, *, missing_ok: bool = False
) -> tuple[Any, ...] | None:
    try:
        link_info = path.lstat()
    except FileNotFoundError:
        return ("missing",) if missing_ok else None
    except OSError:
        return None
    try:
        resolved = path.resolve(strict=True)
        target_info = resolved.stat()
    except (OSError, RuntimeError, ValueError):
        return None
    return (
        "file",
        link_info.st_dev,
        link_info.st_ino,
        link_info.st_size,
        link_info.st_mtime_ns,
        link_info.st_ctime_ns,
        link_info.st_mode,
        hashlib.sha256(os.fsencode(str(resolved))).hexdigest(),
        target_info.st_dev,
        target_info.st_ino,
        target_info.st_size,
        target_info.st_mtime_ns,
        target_info.st_ctime_ns,
        target_info.st_mode,
    )
