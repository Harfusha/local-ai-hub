from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Iterable


class SnapshotError(ValueError):
    pass


def _is_junction(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        info = path.lstat()
    except OSError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    mount_point_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
    return (
        bool(int(getattr(info, "st_file_attributes", 0) or 0) & reparse_attribute)
        and int(getattr(info, "st_reparse_tag", 0) or 0) == mount_point_tag
    )


def _redirecting_component(path: Path) -> Path | None:
    absolute = path.expanduser().absolute()
    components = (absolute, *absolute.parents)
    for component in components:
        is_junction = getattr(component, "is_junction", None)
        if (
            component.is_symlink()
            or (is_junction is not None and is_junction())
            or _is_junction(component)
        ):
            return component
    return None


def _validate_coverage(values: Iterable[str]) -> list[str]:
    coverage = list(values)
    required = {"code", "config", "state"}
    if len(coverage) != len(required) or set(coverage) != required:
        raise SnapshotError("complete rollback snapshot must cover code, config and state")
    return sorted(coverage)


def _root_kind(path: Path) -> str:
    if path.is_symlink():
        raise SnapshotError(f"snapshot roots cannot be symlinks: {path}")
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    raise SnapshotError(f"snapshot root is missing or unsupported: {path}")


def _validate_roots(roots: dict[str, Path], *, allow_missing: bool = False) -> list[tuple[str, Path, str]]:
    if not roots:
        raise SnapshotError("at least one --root is required")
    validated: list[tuple[str, Path, str]] = []
    for name, raw_path in roots.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise SnapshotError(f"invalid root label: {name!r}")
        path = raw_path.expanduser()
        redirected = _redirecting_component(path)
        if redirected is not None:
            raise SnapshotError(f"snapshot roots cannot pass through symlinks or junctions: {redirected}")
        path = path.resolve()
        kind = "missing" if allow_missing and not path.exists() else _root_kind(path)
        validated.append((name, path, kind))
    for index, (_, left, _) in enumerate(validated):
        for _, right, _ in validated[index + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise SnapshotError(f"snapshot roots overlap: {left} and {right}")
    return validated


def _digest(path: Path, kind: str) -> str:
    digest = hashlib.sha256()
    if kind == "file":
        digest.update(b"file\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    digest.update(b"directory\0")
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix().encode("utf-8", "surrogateescape")
        if child.is_symlink():
            digest.update(b"link\0" + relative + b"\0")
            digest.update(os.readlink(child).encode("utf-8", "surrogateescape"))
        elif child.is_dir():
            digest.update(b"dir\0" + relative + b"\0")
        elif child.is_file():
            digest.update(b"file\0" + relative + b"\0")
            with child.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def _copy(source: Path, destination: Path, kind: str) -> None:
    if kind == "directory":
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def create_snapshot(
    output: Path, roots: dict[str, Path], *, coverage: Iterable[str], service_stopped: bool,
) -> Path:
    if not service_stopped:
        raise SnapshotError("stop the Hub service before creating a rollback snapshot")
    coverage = _validate_coverage(coverage)
    validated = _validate_roots(roots)
    output = output.expanduser()
    redirected = _redirecting_component(output)
    if redirected is not None:
        raise SnapshotError(f"snapshot output cannot pass through symlinks or junctions: {redirected}")
    output = output.resolve()
    for _, source, _ in validated:
        if output == source or source in output.parents:
            raise SnapshotError(f"snapshot output must be outside source roots: {source}")
    if output.exists():
        raise SnapshotError(f"snapshot output already exists: {output}")

    output.mkdir(parents=True)
    entries = []
    try:
        payload_root = output / "payload"
        payload_root.mkdir()
        for index, (name, source, kind) in enumerate(validated):
            relative = f"payload/{index:03d}"
            payload = output / relative
            _copy(source, payload, kind)
            entries.append({
                "name": name,
                "source": str(source),
                "kind": kind,
                "payload": relative,
                "sha256": _digest(payload, kind),
            })
        manifest = {"version": 1, "coverage": coverage, "roots": entries}
        manifest_path = output / "manifest.json"
        temporary_manifest = output / "manifest.json.tmp"
        temporary_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_manifest, manifest_path)
    except Exception:
        _remove(output)
        raise
    return output


def _load_manifest(snapshot: Path, roots: dict[str, Path], coverage: Iterable[str]) -> list[dict[str, str]]:
    coverage = _validate_coverage(coverage)
    snapshot = snapshot.expanduser()
    redirected = _redirecting_component(snapshot)
    if redirected is not None:
        raise SnapshotError(f"snapshot directory cannot pass through symlinks or junctions: {redirected}")
    snapshot = snapshot.resolve()
    if not snapshot.is_dir():
        raise SnapshotError(f"snapshot directory is missing or unsupported: {snapshot}")
    try:
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"cannot read snapshot manifest: {exc}") from exc
    if (
        not isinstance(manifest, dict) or manifest.get("version") != 1
        or manifest.get("coverage") != coverage or not isinstance(manifest.get("roots"), list)
    ):
        raise SnapshotError("unsupported or invalid snapshot manifest")

    validated = _validate_roots(roots, allow_missing=True)
    requested = {name: (path, kind) for name, path, kind in validated}
    entries = manifest["roots"]
    if len(entries) != len(requested):
        raise SnapshotError("restore --root labels must match the snapshot")
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SnapshotError("invalid root entry in snapshot manifest")
        name = entry.get("name")
        target = requested.get(name)
        expected_payload = f"payload/{index:03d}"
        if target is None or name in seen or entry.get("payload") != expected_payload:
            raise SnapshotError("restore --root labels must match the snapshot")
        seen.add(name)
        target_path, target_kind = target
        if str(target_path) != entry.get("source"):
            raise SnapshotError(f"restore path for {name!r} differs from its snapshot path")
        kind = entry.get("kind")
        if kind not in {"file", "directory"} or target_kind not in {"missing", kind}:
            raise SnapshotError(f"restore root type changed for {name!r}")
        payload = snapshot / expected_payload
        if payload.is_symlink() or _root_kind(payload) != kind:
            raise SnapshotError(f"snapshot payload is missing or has the wrong type for {name!r}")
        if _digest(payload, kind) != entry.get("sha256"):
            raise SnapshotError(f"snapshot payload integrity check failed for {name!r}")
        if not target_path.parent.is_dir():
            raise SnapshotError(f"restore parent directory is missing for {name!r}: {target_path.parent}")
        if target_path.is_symlink():
            raise SnapshotError(f"restore target cannot be a symlink: {target_path}")
        result.append({
            "name": name,
            "target": str(target_path),
            "kind": kind,
            "payload": str(payload),
        })
    return result


def restore_snapshot(
    snapshot: Path, roots: dict[str, Path], *, coverage: Iterable[str], service_stopped: bool,
) -> list[Path]:
    if not service_stopped:
        raise SnapshotError("stop the Hub service before restoring a rollback snapshot")
    entries = _load_manifest(snapshot, roots, coverage)
    staged: list[tuple[Path, Path]] = []
    preserved: list[tuple[Path, Path | None]] = []
    try:
        for entry in entries:
            target = Path(entry["target"])
            staging = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}")
            _copy(Path(entry["payload"]), staging, entry["kind"])
            if _digest(staging, entry["kind"]) != _digest(Path(entry["payload"]), entry["kind"]):
                raise SnapshotError(f"staged restore integrity check failed for {entry['name']!r}")
            staged.append((target, staging))

        for target, staging in staged:
            current = None
            if target.exists() or target.is_symlink():
                current = target.with_name(f"{target.name}.pre-rollback-{uuid.uuid4().hex[:12]}")
                os.replace(target, current)
            try:
                os.replace(staging, target)
            except Exception:
                if current is not None:
                    os.replace(current, target)
                raise
            preserved.append((target, current))
    except Exception:
        for target, current in reversed(preserved):
            _remove(target)
            if current is not None:
                os.replace(current, target)
        raise
    finally:
        for _, staging in staged:
            _remove(staging)
    return [current for _, current in preserved if current is not None]


def _parse_roots(values: Iterable[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not raw_path:
            raise SnapshotError("--root must use LABEL=PATH")
        if name in roots:
            raise SnapshotError(f"duplicate root label: {name}")
        roots[name] = Path(raw_path)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and restore matched Local AI Hub rollback snapshots.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--root", action="append", required=True, metavar="LABEL=PATH")
    create.add_argument("--covers", nargs="+", choices=("code", "config", "state"), required=True)
    create.add_argument("--service-stopped", action="store_true", help="confirm the Hub service is stopped")
    restore = commands.add_parser("restore")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--root", action="append", required=True, metavar="LABEL=PATH")
    restore.add_argument("--covers", nargs="+", choices=("code", "config", "state"), required=True)
    restore.add_argument("--service-stopped", action="store_true", help="confirm the Hub service is stopped")
    args = parser.parse_args(argv)
    try:
        roots = _parse_roots(args.root)
        if args.command == "create":
            result = create_snapshot(args.output, roots, coverage=args.covers, service_stopped=args.service_stopped)
            print(f"Complete rollback snapshot verified: {result}")
        else:
            preserved = restore_snapshot(args.snapshot, roots, coverage=args.covers, service_stopped=args.service_stopped)
            print("Rollback restored and verified.")
            for path in preserved:
                print(f"Current pre-rollback copy preserved: {path}")
        return 0
    except (OSError, SnapshotError) as exc:
        print(f"Rollback snapshot error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
