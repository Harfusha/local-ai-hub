"""Normalize context identity hints and related settings values."""

import hashlib
import os
from collections.abc import Mapping
from typing import NotRequired, TypedDict


class ContextPathHint(TypedDict):
    """Path hint with optional provenance and context metadata."""

    path: str
    purpose: NotRequired[str]
    scope: NotRequired[str]
    evidence_id: NotRequired[str]
    provenance: NotRequired[str]
    repository_revision: NotRequired[str]
    config_digest: NotRequired[str]
    expires_at: NotRequired[str]


ContextPathHintInput = ContextPathHint | str


_CONTEXT_HINT_FIELDS = frozenset(
    {
        "path",
        "purpose",
        "scope",
        "evidence_id",
        "provenance",
        "repository_revision",
        "config_digest",
        "expires_at",
    }
)
_OPTIONAL_CONTEXT_HINT_FIELDS = (
    "purpose",
    "scope",
    "evidence_id",
    "provenance",
    "repository_revision",
    "config_digest",
    "expires_at",
)
_MAX_CONTEXT_HINT_CHARS = 65_536
_INLINE_IDENTITY_CHARS = 1024


def normalize_context_path_hints(value: object) -> tuple[ContextPathHint, ...]:
    """Validate and normalize up to 64 context path hints."""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("context path hints must be a list or tuple")

    normalized: list[ContextPathHint] = []
    for item in value[:64]:
        if isinstance(item, str):
            item = {"path": item}
        elif not isinstance(item, Mapping):
            raise ValueError("each context path hint must be a mapping")
        if any(not isinstance(key, str) or key not in _CONTEXT_HINT_FIELDS for key in item):
            raise ValueError("context path hint contains an unknown key")

        path = item.get("path")
        if not isinstance(path, str):
            raise ValueError("context path hint path must be a string")
        path = path.strip()
        if not path or len(path) > _MAX_CONTEXT_HINT_CHARS or not path.isprintable():
            raise ValueError("context path hint path is invalid")

        hint: ContextPathHint = {"path": path}
        for field in _OPTIONAL_CONTEXT_HINT_FIELDS:
            if field not in item:
                continue
            field_value = item[field]
            if not isinstance(field_value, str):
                raise ValueError(f"context path hint {field} must be a string")
            field_value = field_value.strip()
            if not field_value:
                continue
            if len(field_value) > _MAX_CONTEXT_HINT_CHARS or not field_value.isprintable():
                raise ValueError(f"context path hint {field} is invalid")
            hint[field] = field_value
        normalized.append(hint)

    return tuple(normalized)


def context_path_hints_identity(value: object) -> tuple[dict[str, object], ...]:
    """Return normalized hints with long text replaced by stable hashes."""

    normalized = normalize_context_path_hints(value)
    result: list[dict[str, object]] = []
    for hint in normalized:
        identity_hint: dict[str, object] = {}
        for field, text in hint.items():
            if len(text) <= _INLINE_IDENTITY_CHARS:
                identity_hint[field] = text
            else:
                identity_hint[field] = {
                    "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
                    "chars": len(text),
                }
        result.append(identity_hint)
    return tuple(result)


def normalize_settings_digest(value: object) -> str | None:
    """Return a usable settings digest, omitting malformed values."""

    if not isinstance(value, str):
        return None
    digest = value.strip()
    if not digest or len(digest) > 128 or not digest.isprintable():
        return None
    return digest


def combine_settings_digests(*values: object) -> str | None:
    """Combine valid configuration digests without losing any cache input."""

    digests = sorted({digest for value in values if (digest := normalize_settings_digest(value))})
    if not digests:
        return None
    if len(digests) == 1:
        return digests[0]
    payload = "context-settings-v1\0" + "\0".join(digests)
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:32]


def is_valid_settings_digest(value: object) -> bool:
    """Return True when value normalizes to a valid settings digest."""

    return normalize_settings_digest(value) is not None


def has_context_path_hints(value: object) -> bool:
    """Return True when value normalizes to at least one valid context path hint."""

    try:
        return bool(normalize_context_path_hints(value))
    except ValueError:
        return False


def normalize_context_root(value: object) -> str:
    """Normalize root path using the host operating system's path rules."""

    if value is None or isinstance(value, bool):
        return ""
    root = str(value).replace("\x00", "").strip()
    if not root:
        return ""
    return os.path.normcase(os.path.normpath(root))
