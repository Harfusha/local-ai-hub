"""Versioned ownership manifest for a Local AI Hub installation."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = ".local-ai-hub-install-ownership.json"
SCHEMA_VERSION = 2


def _canonical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _relative_paths(paths: list[str] | None) -> list[str]:
    result: set[str] = set()
    for raw in paths or []:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError("managed paths must be non-empty relative strings")
        path = PurePosixPath(raw.replace("\\", "/"))
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"unsafe managed path: {raw}")
        result.add(path.as_posix())
    return sorted(result)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(encoded)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        if os.name != "nt":
            path.chmod(0o600)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _read_valid_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST_NAME
    if path.is_symlink():
        raise ValueError("ownership marker must not be a symlink or reparse point")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ownership marker is unreadable or invalid") from exc
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") not in {1, SCHEMA_VERSION}
        or data.get("product") != "local-ai-hub"
        or not isinstance(data.get("install_id"), str)
        or not data["install_id"].strip()
        or data.get("install_root") != str(root)
        or not isinstance(data.get("managed_paths"), list)
    ):
        raise ValueError("ownership marker identity or schema is invalid")
    entries = data.get("external_ownership", [])
    if not isinstance(entries, list):
        raise ValueError("ownership marker external records are invalid")
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") not in {"text_block", "json_key", "json_list_item", "json_container", "whole_file"}:
            raise ValueError("ownership marker external record is invalid")
        target = entry.get("path")
        marker = entry.get("owner_marker")
        if (not isinstance(target, str) or not Path(target).is_absolute()
                or not isinstance(marker, dict)
                or type(entry.get("created_by_hub")) is not bool
                or not isinstance(entry.get("last_hub_written_digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["last_hub_written_digest"])
                or (entry.get("preimage_digest") is not None
                    and (not isinstance(entry["preimage_digest"], str)
                         or not re.fullmatch(r"[0-9a-f]{64}", entry["preimage_digest"])))):
            raise ValueError("ownership marker external record is invalid")
        if entry["kind"] == "text_block":
            if (not isinstance(marker.get("begin"), str) or not marker["begin"]
                    or not isinstance(marker.get("end"), str) or not marker["end"]):
                raise ValueError("ownership marker text record is invalid")
        elif entry["kind"] == "json_key":
            if (not isinstance(marker.get("container"), str)
                    or not isinstance(marker.get("key"), str) or not marker["key"]):
                raise ValueError("ownership marker JSON record is invalid")
        elif entry["kind"] == "json_list_item":
            if (not isinstance(marker.get("container"), str)
                    or not isinstance(marker.get("item"), str) or not marker["item"]):
                raise ValueError("ownership marker JSON-list record is invalid")
        elif entry["kind"] == "whole_file":
            if marker:
                raise ValueError("whole-file ownership marker must be empty")
        elif entry["kind"] == "json_container":
            if (not isinstance(marker.get("path"), str) or marker.get("container_type") not in {"object", "list"}):
                raise ValueError("ownership marker JSON-container record is invalid")
        else:
            raise ValueError("ownership marker JSON record is invalid")
        rollback_reference = entry.get("rollback_reference")
        if rollback_reference is not None:
            if not isinstance(rollback_reference, str):
                raise ValueError("ownership marker rollback reference is invalid")
            relative = PurePosixPath(rollback_reference.replace("\\", "/"))
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise ValueError("ownership marker rollback reference is unsafe")
        normalized.append({**entry, "path": str(_canonical(Path(target))), "owner_marker": dict(marker)})
    data["managed_paths"] = _relative_paths(data["managed_paths"])
    data["external_ownership"] = normalized
    return data


def write_install_manifest(
    install_dir: Path, managed_paths: list[str] | None = None,
    external_ownership: list[dict[str, Any]] | None = None,
) -> Path:
    """Atomically mark an install as owned by this product, without storing secrets."""
    root = _canonical(Path(install_dir))
    if not root.is_absolute() or root == Path(root.anchor) or not root.is_dir():
        raise ValueError(f"invalid install root: {root}")
    manifest_path = root / MANIFEST_NAME
    prior = _read_valid_manifest(root)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product": "local-ai-hub",
        "install_id": prior["install_id"] if prior else uuid.uuid4().hex,
        "install_root": str(root),
        "managed_paths": _relative_paths(managed_paths),
        "external_ownership": external_ownership if external_ownership is not None else (prior or {}).get("external_ownership", []),
    }
    _atomic_json(manifest_path, manifest)
    return manifest_path


def record_external_block(
    install_dir: Path, path: Path, *, kind: str, owner_marker: dict[str, str],
    preimage: str | None, postimage: str,
) -> None:
    """Record ownership of a marked text block without storing its content."""
    if kind != "text_block" or not isinstance(postimage, str):
        raise ValueError("unsupported external ownership record")
    begin, end = owner_marker.get("begin"), owner_marker.get("end")
    if not isinstance(begin, str) or not begin or not isinstance(end, str) or not end:
        raise ValueError("text block owner markers are invalid")
    if postimage.count(begin) != 1 or postimage.count(end) != 1 or postimage.index(begin) >= postimage.index(end):
        raise ValueError("postimage must contain exactly one ordered owner marker pair")
    root = _canonical(Path(install_dir))
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("invalid install root")
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    key = (str(target), begin, end)
    entries = list(prior["external_ownership"])
    matching = next((entry for entry in entries if entry["kind"] == "text_block"
                     and (entry["path"], entry["owner_marker"]["begin"], entry["owner_marker"]["end"]) == key), None)
    if preimage is not None:
        if matching is None or matching["last_hub_written_digest"] != _digest(preimage):
            raise ValueError(f"unowned or edited external block: {target}")
    rollback_reference = matching.get("rollback_reference") if matching is not None else None
    preimage_digest = matching.get("preimage_digest") if matching is not None else None
    created_by_hub = matching.get("created_by_hub", True) if matching is not None else preimage is None
    if preimage is not None and matching is None:
        raise ValueError(f"unowned external block: {target}")
    if preimage is not None and matching.get("created_by_hub") is False and rollback_reference is None:
        raise ValueError(f"owned external block has no rollback reference: {target}")
    if preimage is not None and matching.get("created_by_hub") is False:
        preimage_digest = matching.get("preimage_digest")
    elif preimage is not None and matching.get("created_by_hub") is True:
        preimage_digest = None
    if preimage is not None and rollback_reference is None and matching.get("created_by_hub") is False:
        rollback_dir = root / ".ownership" / "rollback"
        rollback_dir.mkdir(parents=True, exist_ok=True)
        rollback_name = _digest(f"{target}\0{begin}\0{end}\0{preimage}") + ".txt"
        rollback_path = rollback_dir / rollback_name
        if not rollback_path.exists():
            fd, temporary_name = tempfile.mkstemp(prefix="block.", suffix=".tmp", dir=rollback_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    stream.write(preimage)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, rollback_path)
                if os.name != "nt":
                    rollback_path.chmod(0o600)
            except BaseException:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
                raise
        rollback_reference = rollback_path.relative_to(root).as_posix()
    record = {
        "path": str(target),
        "kind": kind,
        "owner_marker": {"begin": begin, "end": end},
        "created_by_hub": created_by_hub,
        "preimage_digest": preimage_digest,
        "last_hub_written_digest": _digest(postimage),
        "rollback_reference": rollback_reference,
    }
    if matching is None:
        entries.append(record)
    else:
        entries[entries.index(matching)] = record
    write_install_manifest(root, prior["managed_paths"], entries)


def assert_external_block_writable(
    install_dir: Path, path: Path, *, owner_marker: dict[str, str], current_block: str | None,
) -> None:
    """Fail closed when a marked block is absent from ownership or was edited."""
    if current_block is None:
        return
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    begin, end = owner_marker.get("begin"), owner_marker.get("end")
    for entry in prior["external_ownership"]:
        if entry["kind"] != "text_block":
            continue
        marker = entry["owner_marker"]
        if entry["path"] == str(target) and marker["begin"] == begin and marker["end"] == end:
            if entry["last_hub_written_digest"] == _digest(current_block):
                return
            raise ValueError(f"owned external block was edited: {target}")
    raise ValueError(f"external block has no ownership record: {target}")


def assert_external_json_key_writable(
    install_dir: Path, path: Path, *, container: str, key: str, current_value: Any,
    kind: str = "json_key",
) -> None:
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    for entry in prior["external_ownership"]:
        marker = entry["owner_marker"]
        if (entry["kind"] == kind and entry["path"] == str(target)
                and marker["container"] == container and marker["key"] == key):
            if entry["last_hub_written_digest"] == _json_digest(current_value):
                return
            raise ValueError(f"owned external JSON key was edited: {target}#{container}.{key}")
    raise ValueError(f"external JSON key has no ownership record: {target}#{container}.{key}")


def record_external_json_key(
    install_dir: Path, path: Path, *, container: str, key: str,
    preimage: Any | None, postimage: Any, kind: str = "json_key",
) -> None:
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    key_id = (str(target), container, key)
    entries = list(prior["external_ownership"])
    matching = next((entry for entry in entries if entry["kind"] == kind
                     and (entry["path"], entry["owner_marker"]["container"], entry["owner_marker"]["key"]) == key_id), None)
    if preimage is not None and (matching is None or matching["last_hub_written_digest"] != _json_digest(preimage)):
        raise ValueError(f"unowned or edited external JSON key: {target}#{container}.{key}")
    record = {
        "path": str(target),
        "kind": kind,
        "owner_marker": {"container": container, "key": key},
        "created_by_hub": matching.get("created_by_hub", True) if matching else preimage is None,
        "preimage_digest": matching.get("preimage_digest") if matching else None,
        "last_hub_written_digest": _json_digest(postimage),
        "rollback_reference": matching.get("rollback_reference") if matching else None,
    }
    if matching is None:
        entries.append(record)
    else:
        entries[entries.index(matching)] = record
    write_install_manifest(root, prior["managed_paths"], entries)


def record_external_json_list_item(
    install_dir: Path, path: Path, *, container: str, item: str,
) -> None:
    """Record a Hub-added string in a JSON list without claiming other list items."""
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    marker = {"container": container, "item": item}
    key_id = (str(target), container, item)
    entries = list(prior["external_ownership"])
    matching = next((entry for entry in entries if entry["kind"] == "json_list_item"
                     and (entry["path"], entry["owner_marker"]["container"], entry["owner_marker"]["item"]) == key_id), None)
    record = {
        "path": str(target), "kind": "json_list_item", "owner_marker": marker,
        "created_by_hub": matching.get("created_by_hub", True) if matching else True,
        "preimage_digest": matching.get("preimage_digest") if matching else None,
        "last_hub_written_digest": _json_digest(item),
        "rollback_reference": matching.get("rollback_reference") if matching else None,
    }
    if matching is None:
        entries.append(record)
    else:
        entries[entries.index(matching)] = record
    write_install_manifest(root, prior["managed_paths"], entries)


def record_external_json_container(install_dir: Path, path: Path, *, container_path: str, container_type: str) -> None:
    if container_type not in {"object", "list"}:
        raise ValueError("unsupported JSON container type")
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    marker = {"path": container_path, "container_type": container_type}
    key_id = (str(target), container_path, container_type)
    entries = list(prior["external_ownership"])
    matching = next((entry for entry in entries if entry["kind"] == "json_container"
                     and (entry["path"], entry["owner_marker"]["path"], entry["owner_marker"]["container_type"]) == key_id), None)
    record = {
        "path": str(target), "kind": "json_container", "owner_marker": marker,
        "created_by_hub": True, "preimage_digest": None,
        "last_hub_written_digest": _json_digest({} if container_type == "object" else []),
        "rollback_reference": None,
    }
    if matching is None:
        entries.append(record)
    else:
        entries[entries.index(matching)] = record
    write_install_manifest(root, prior["managed_paths"], entries)


def assert_external_file_writable(install_dir: Path, path: Path, current_text: str | bytes) -> None:
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    for entry in prior["external_ownership"]:
        if entry["kind"] == "whole_file" and entry["path"] == str(target):
            current_digest = hashlib.sha256(current_text).hexdigest() if isinstance(current_text, bytes) else _digest(current_text)
            if entry["last_hub_written_digest"] == current_digest:
                return
            raise ValueError(f"owned external file was edited: {target}")
    raise ValueError(f"external file has no ownership record: {target}")


def record_external_file(install_dir: Path, path: Path, content: str | bytes) -> None:
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    entries = list(prior["external_ownership"])
    matching = next((entry for entry in entries if entry["kind"] == "whole_file" and entry["path"] == str(target)), None)
    content_digest = hashlib.sha256(content).hexdigest() if isinstance(content, bytes) else _digest(content)
    record = {
        "path": str(target), "kind": "whole_file", "owner_marker": {},
        "created_by_hub": matching.get("created_by_hub", True) if matching else True,
        "preimage_digest": matching.get("preimage_digest") if matching else None,
        "last_hub_written_digest": content_digest,
        "rollback_reference": matching.get("rollback_reference") if matching else None,
    }
    if matching is None:
        entries.append(record)
    else:
        entries[entries.index(matching)] = record
    write_install_manifest(root, prior["managed_paths"], entries)


def forget_external_record(install_dir: Path, path: Path, *, kind: str, owner_marker: dict[str, str]) -> None:
    root = _canonical(Path(install_dir))
    prior = _read_valid_manifest(root)
    if prior is None:
        raise ValueError("ownership marker is missing")
    target = _canonical(Path(path))
    entries = [
        entry for entry in prior["external_ownership"]
        if not (entry["kind"] == kind and entry["path"] == str(target)
                and entry["owner_marker"] == owner_marker)
    ]
    if len(entries) != len(prior["external_ownership"]):
        write_install_manifest(root, prior["managed_paths"], entries)


def read_install_manifest(install_dir: Path) -> dict[str, Any]:
    root = _canonical(Path(install_dir))
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink():
        raise ValueError("ownership marker must not be a symlink or reparse point")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("ownership marker is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ownership marker is unreadable or invalid") from exc
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") not in {1, SCHEMA_VERSION}
        or data.get("product") != "local-ai-hub"
        or not isinstance(data.get("install_id"), str)
        or not data["install_id"].strip()
        or data.get("install_root") != str(root)
        or not isinstance(data.get("managed_paths"), list)
    ):
        raise ValueError("ownership marker identity or schema is invalid")
    validated = _read_valid_manifest(root)
    if validated is None:
        raise ValueError("ownership marker is missing")
    return validated
