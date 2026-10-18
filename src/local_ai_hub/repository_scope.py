"""Repository confinement for the single local owner.

Credentials authorize operations; repository roots delimit filesystem access.
Neither agents nor repositories introduce a separate owner identity.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


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
            item.is_symlink() for item in (candidate, *candidate.parents)
        ):
            raise RepositoryScopeError("root must be absolute and contain no symlinks", "invalid_root")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise RepositoryScopeError("root must be a directory", "invalid_root")
        return resolved
    except RepositoryScopeError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryScopeError("root is unavailable", "invalid_root") from exc


def authorized_repository_root(config: Mapping[str, Any], raw: Any) -> str:
    root = canonical_repository_root(raw)
    security = config.get("security", {})
    if not isinstance(security, Mapping):
        raise RepositoryScopeError("invalid security configuration", "invalid_security", 403)
    token = security.get("api_token", "")
    allowed = security.get("allowed_roots", [])
    if not isinstance(token, str) or not isinstance(allowed, list):
        raise RepositoryScopeError("invalid root authorization configuration", "invalid_security", 403)
    if token or allowed:
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
