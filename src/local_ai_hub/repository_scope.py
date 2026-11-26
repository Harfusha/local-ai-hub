"""Repository confinement for the single local owner.

Credentials authorize operations; repository roots delimit filesystem access.
Neither agents nor repositories introduce a separate owner identity.
"""

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _is_junction(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        info = path.lstat()
    except OSError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    mount_point_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
    return (
        bool(int(getattr(info, "st_file_attributes", 0) or 0) & reparse_attribute)
        and int(getattr(info, "st_reparse_tag", 0) or 0) == mount_point_tag
    )


def _is_redirecting_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


class RepositoryScopeError(ValueError):
    def __init__(self, message: str, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def canonical_repository_root(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 4096:
        raise RepositoryScopeError("root must be an absolute repository directory", "invalid_root")
    candidate = Path(raw.strip()).expanduser()
    try:
        if not candidate.is_absolute() or any(
            _is_redirecting_link(item) for item in (candidate, *candidate.parents)
        ):
            raise RepositoryScopeError("root must be absolute and contain no symlinks or junctions", "invalid_root")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise RepositoryScopeError("root must be a directory", "invalid_root")
        return resolved
    except RepositoryScopeError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryScopeError("root is unavailable", "invalid_root") from exc


def confine_child_path(root: Path | str, relative_child: Path | str) -> Path:
    """Resolve and confine a child path strictly within canonical root."""
    canonical_root = canonical_repository_root(root) if not isinstance(root, Path) else root
    child_str = os.fspath(relative_child)
    if not child_str or "\x00" in child_str:
        raise RepositoryScopeError("path is invalid or contains null bytes", "invalid_path", 400)
    child_path = Path(child_str)
    if child_path.is_absolute():
        resolved = child_path.resolve(strict=False)
    else:
        resolved = (canonical_root / child_path).resolve(strict=False)
    try:
        resolved.relative_to(canonical_root)
    except (ValueError, OSError) as exc:
        raise RepositoryScopeError(f"path {child_str} escapes repository root", "path_escape", 403) from exc
    curr = resolved
    while curr != canonical_root and curr != curr.parent:
        if _is_redirecting_link(curr):
            try:
                target = curr.resolve(strict=True)
                target.relative_to(canonical_root)
            except (ValueError, OSError) as exc:
                raise RepositoryScopeError(f"link component {curr} escapes repository root", "link_escape", 403) from exc
        curr = curr.parent
    return resolved


def authorized_repository_root(config: Mapping[str, Any], raw: Any) -> str:
    root = canonical_repository_root(raw)
    security = config.get("security", {})
    if not isinstance(security, Mapping):
        raise RepositoryScopeError("invalid security configuration", "invalid_security", 403)
    allowed = security.get("allowed_roots", [])
    if not isinstance(allowed, list):
        raise RepositoryScopeError("invalid root authorization configuration", "invalid_security", 403)
    # A missing allowlist retains the historical local-owner policy. An
    # explicitly configured empty allowlist is a deny-all, not an override
    # permitting every readable directory.
    if "allowed_roots" in security and not allowed:
        raise RepositoryScopeError("no repository roots are allowed", "root_not_allowed", 403)
    if allowed:
        for entry in allowed:
            try:
                root.relative_to(canonical_repository_root(entry))
                return str(root)
            except (ValueError, OSError):
                continue
        raise RepositoryScopeError("root is outside allowed_roots", "root_not_allowed", 403)
    return str(root)


def reject_retired_tenancy_fields(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise RepositoryScopeError("payload must be an object", "invalid_payload")
    containers: list[tuple[str, Mapping[str, Any]]] = [("", payload)]
    record = payload.get("record")
    if isinstance(record, Mapping):
        containers.append(("record.", record))
    for label, container in tuple(containers):
        for name in ("provenance", "metadata"):
            value = container.get(name)
            if isinstance(value, Mapping):
                containers.append((f"{label}{name}.", value))
    for label, container in containers:
        for name in ("tenant", "tenant_key", "tenant_id", "tenant_scope", "tenant_identity", "tenant_partition"):
            if name in container:
                raise RepositoryScopeError(
                    f"retired tenancy field: {label}{name}", "retired_tenancy_field"
                )
