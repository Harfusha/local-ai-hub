"""Read-only export of cards already persisted in the Hub preprocessing index."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

# The training CLI runs from the checkout in its own environment.
from src.local_ai_hub.file_locks import exclusive_file_update

from .teacher_cards import build_messages, load_roots


_SYNTHETIC_CARD_MODELS = {
    "deterministic",
    "deterministic-stub",
    "deterministic-barrel",
    "deterministic-oversized",
}
_MAX_EXPORT_ROWS = 100_000
_MAX_EXPORT_BYTES = 512 * 1024 * 1024
_MAX_ROOTS_PER_QUERY = 900
_STAGING_PREFIX = ".card-export-"
_STAGING_NAME = re.compile(re.escape(_STAGING_PREFIX) + r"[0-9a-f]{64}", re.IGNORECASE)
_STAGED_FILES = ("dataset.tmp", "manifest.tmp", "retrieval-cases.tmp")

_FILE_CARD_ROWS = """SELECT f.root,f.path,f.content_hash,f.needs_hash,c.card_json,c.model,c.analyzer_version,
                           c.content_hash AS card_source_hash,s.content_hash AS source_hash
                    FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key
                    LEFT JOIN source_index s ON s.root=f.root AND s.path=f.path
                    WHERE f.root IN ({placeholders})
                    ORDER BY f.root,f.path,c.card_key"""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _root_identity(root: str | Path) -> tuple[str, str]:
    candidate = Path(root)
    if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
        raise ValueError(f"project root is a symlink or junction: {root}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"project root is not a real directory: {root}")
    canonical = os.path.normcase(str(resolved))
    return canonical, _sha256(canonical.encode("utf-8"))


def _index_connection(database: Path) -> sqlite3.Connection:
    if database.is_symlink() or not database.is_file():
        raise ValueError(f"preprocessing index is missing or unsafe: {database}")
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=2000")
    return connection


def _authorized_roots(connection: sqlite3.Connection, roots_file: Path | str | None) -> tuple[dict[str, str], int]:
    registered: dict[str, str] = {}
    for row in connection.execute("SELECT root FROM projects ORDER BY root"):
        try:
            canonical, _ = _root_identity(str(row[0]))
        except (OSError, ValueError):
            continue
        registered[canonical] = str(row[0])
    if roots_file is None:
        if not registered:
            raise ValueError("no existing project roots are registered in the preprocessing index")
        return registered, len(registered)

    authorized: dict[str, str] = {}
    for item in load_roots(roots_file):
        canonical, _ = _root_identity(item["path"])
        if canonical not in registered:
            raise ValueError(f"project root is not registered in the existing preprocessing index: {item['id']}")
        authorized[canonical] = registered[canonical]
    if not authorized:
        raise ValueError("roots file has no registered project roots")
    if len(authorized) > _MAX_ROOTS_PER_QUERY:
        raise ValueError(f"project root count exceeds SQLite query limit ({_MAX_ROOTS_PER_QUERY})")
    return authorized, len(authorized)


def _card_text(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        raise ValueError("stored card must be a non-empty JSON object")
    parts: list[str] = []

    def append(prefix: str, item: Any) -> None:
        if isinstance(item, str):
            if item.strip():
                parts.append(f"{prefix}: {item.strip()}")
        elif isinstance(item, list):
            for child in item:
                append(prefix, child)
        elif isinstance(item, dict):
            for key in sorted(item):
                append(f"{prefix}.{key}" if prefix else str(key), item[key])

    append("", value)
    if not parts:
        raise ValueError("stored card has no searchable text")
    return "\n".join(parts)


def _card_identity(root_id: str, card_kind: str, card_key: str, card_json: str) -> tuple[Any, str, str]:
    try:
        card = json.loads(card_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored {card_kind} card is invalid JSON") from exc
    card_hash = _sha256(_canonical(card).encode("utf-8"))
    row_id = _sha256(f"{root_id}\0{card_kind}\0{card_key}\0{card_hash}".encode("utf-8"))
    return card, card_hash, row_id


def _current_file_card_hash(record: sqlite3.Row, format: str) -> str | None:
    source_hash = record["content_hash"]
    if not isinstance(source_hash, str) or not source_hash:
        return None
    if record["needs_hash"] != 0 or record["card_source_hash"] != source_hash:
        return None
    if format == "card-training" and record["source_hash"] != source_hash:
        return None
    return source_hash


def _card_row(
    *, root_id: str, card_kind: str, card_key: str, card_json: str,
    card_model: str, card_version: str,
    path: str = "", source_hash: str = "", source_text: str = "",
) -> dict[str, Any]:
    card, card_hash, row_id = _card_identity(root_id, card_kind, card_key, card_json)
    canonical_card = _canonical(card)
    provenance: dict[str, Any] = {
        "source": "existing_hub_preprocess_card",
        "data_class": "existing_local",
        "card_kind": card_kind,
        "root_id": root_id,
        "card_sha256": card_hash,
        "card_model": card_model,
        "card_version": card_version,
    }
    if path:
        provenance["relative_path"] = path
    if source_hash:
        provenance["source_sha256"] = source_hash

    if source_text:
        messages = build_messages(path, source_text)
        messages.append({"role": "assistant", "content": canonical_card})
        return {
            "id": row_id,
            "group_id": root_id,
            "source_sha256": source_hash,
            "messages": messages,
            "provenance": provenance,
        }
    return {
        "id": row_id,
        "group_id": root_id,
        "text": _card_text(card),
        "provenance": provenance,
    }


def _regular_owned_file(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _prepare_staging(output: Path) -> Path:
    key = _sha256(os.path.normcase(output.name).encode("utf-8"))
    staging = output.parent / (_STAGING_PREFIX + key)
    staging.mkdir(mode=0o700, exist_ok=True)
    info = staging.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError("card export staging path is not a regular directory")
    owner = staging / "owner"
    identity = f"local-ai-hub existing card export staging v1\n{key}\n".encode("ascii")
    try:
        info = owner.lstat()
    except FileNotFoundError:
        if next(staging.iterdir(), None) is not None:
            raise ValueError("card export staging directory has no ownership marker") from None
        with owner.open("xb") as stream:
            stream.write(identity)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        if not _regular_owned_file(info) or info.st_size != len(identity) or owner.read_bytes() != identity:
            raise ValueError("card export staging ownership marker is invalid")

    interrupted = []
    for name in _STAGED_FILES:
        path = staging / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not _regular_owned_file(info):
            raise ValueError("card export staging file is unsafe")
        interrupted.append(path)
    for path in interrupted:
        path.unlink()
    return staging


@contextmanager
def _stage_bytes(path: Path, chunks: Iterable[bytes]) -> Iterator[str]:
    created = False
    digest = hashlib.sha256()
    try:
        with path.open("xb") as stream:
            created = True
            for chunk in chunks:
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        yield digest.hexdigest()
    finally:
        if created:
            path.unlink(missing_ok=True)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _benchmark_inputs(
    *, output: Path, staging: Path, state_root: Path, format: str, dataset_sha256: str,
    benchmark_cases_file: Path | str | None = None,
    benchmark_root: Path | str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if format == "embedding-corpus":
        result: dict[str, Any] = {
            "prepared": False,
            "reason": "embedding fine-tuning labels are not present",
        }
        if benchmark_cases_file is None:
            return result
        if benchmark_root is None:
            return {**result, "retrieval_evaluation": {
                "prepared": False, "reason": "benchmark root is required to bind case paths",
            }}
        raw_cases_path = Path(benchmark_cases_file)
        if (raw_cases_path.is_symlink()
                or (hasattr(raw_cases_path, "is_junction") and raw_cases_path.is_junction())):
            return {**result, "retrieval_evaluation": {
                "prepared": False, "reason": "benchmark cases path is unsafe",
            }}
        raw_root = Path(benchmark_root)
        if raw_root.is_symlink() or (hasattr(raw_root, "is_junction") and raw_root.is_junction()):
            return {**result, "retrieval_evaluation": {
                "prepared": False, "reason": "benchmark root is unsafe",
            }}
        try:
            cases_path = raw_cases_path.resolve(strict=True)
            root_path = raw_root.resolve(strict=True)
            if not cases_path.is_file() or not cases_path.is_relative_to(root_path):
                raise ValueError("benchmark cases must be a file inside benchmark root")
            cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
            cases = cases_data.get("cases") if isinstance(cases_data, dict) else None
            if not isinstance(cases_data, dict) or cases_data.get("schema_version") != 1 or not isinstance(cases, list):
                raise ValueError("unsupported benchmark cases schema")
            _, benchmark_root_id = _root_identity(root_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return {**result, "retrieval_evaluation": {
                "prepared": False, "reason": "benchmark cases are invalid or outside benchmark root",
            }}

        available_paths = {
            str(row.get("provenance", {}).get("relative_path", "")).replace("\\", "/")
            for row in (rows or [])
            if row.get("provenance", {}).get("root_id") == benchmark_root_id
            and row.get("provenance", {}).get("relative_path")
        }
        positive_cases = [case for case in cases if isinstance(case, dict) and case.get("negative") is not True]
        seen_ids: set[str] = set()
        invalid_cases = 0
        unresolved_paths: set[str] = set()
        fully_resolved = 0
        resolved_cases: list[dict[str, Any]] = []
        excluded_case_ids: list[str] = []
        for case in cases:
            if isinstance(case, dict) and case.get("negative") is True:
                case_id = case.get("id")
                query = case.get("query") or case.get("query_b64")
                if not isinstance(case_id, str) or not case_id or case_id in seen_ids or not isinstance(query, str) or not query:
                    invalid_cases += 1
                    continue
                seen_ids.add(case_id)
                resolved_cases.append(case)
        for case in positive_cases:
            case_id = case.get("id")
            query = case.get("query") or case.get("query_b64")
            expected = case.get("expected_paths")
            if (not isinstance(case_id, str) or not case_id or case_id in seen_ids
                    or not isinstance(query, str) or not query.strip()
                    or not isinstance(expected, list) or not expected
                    or any(not isinstance(path, str) or not path or path.startswith(("/", "\\"))
                           or ".." in path.replace("\\", "/").split("/") for path in expected)):
                invalid_cases += 1
                continue
            seen_ids.add(case_id)
            missing = {path.replace("\\", "/") for path in expected} - available_paths
            unresolved_paths.update(missing)
            if not missing:
                fully_resolved += 1
                resolved_cases.append(case)
            else:
                excluded_case_ids.append(case_id)
        retrieval_ready = invalid_cases == 0 and fully_resolved > 0
        try:
            relative_case_path = cases_path.relative_to(root_path).as_posix()
        except ValueError:
            relative_case_path = cases_path.name
        case_output = staging / "retrieval-cases.json"
        if (case_output.is_symlink()
                or (hasattr(case_output, "is_junction") and case_output.is_junction())):
            return {**result, "retrieval_evaluation": {
                "prepared": False, "reason": "retrieval case output path is unsafe",
            }}
        subset_data = dict(cases_data)
        subset_data["source_case_set"] = cases_data.get("case_set")
        subset_data["case_set"] = f"{cases_data.get('case_set', 'existing-cases')}-existing-card-subset"
        subset_data["labeling"] = (
            str(cases_data.get("labeling", ""))
            + " Filtered to cases whose expected paths exist in the selected root's already-exported cards."
        ).strip()
        subset_data["cases"] = resolved_cases
        staged_cases = staging / "retrieval-cases.tmp"
        with _stage_bytes(staged_cases, (_json_bytes(subset_data),)) as subset_sha256:
            staged_cases.replace(case_output)
        result["retrieval_evaluation"] = {
            "prepared": retrieval_ready,
            "status": (
                "prepared_complete" if retrieval_ready and fully_resolved == len(positive_cases)
                else "prepared_subset" if retrieval_ready else "unresolved"
            ),
            "reason": (
                "the filtered existing case subset resolves to exported cards; it is retrieval evaluation data, "
                "not embedding fine-tuning labels"
                if retrieval_ready else "no valid positive cases resolve to this root's exported cards"
            ),
            "source": relative_case_path,
            "source_sha256": _file_sha256(cases_path),
            "case_set": cases_data.get("case_set"),
            "prepared_cases": case_output.relative_to(state_root).as_posix(),
            "prepared_cases_sha256": subset_sha256,
            "case_count": len(resolved_cases),
            "source_case_count": len(cases),
            "positive_case_count": sum(case.get("negative") is not True for case in resolved_cases),
            "fully_resolved_case_count": fully_resolved,
            "excluded_case_ids": excluded_case_ids,
            "unresolved_expected_path_count": len(unresolved_paths),
            "invalid_case_count": invalid_cases,
            "benchmark_root_id": benchmark_root_id,
        }
        return result

    manifest_path = output.with_name(output.name.removesuffix(".jsonl") + ".dataset-manifest.json")
    if manifest_path.is_symlink() or (hasattr(manifest_path, "is_junction") and manifest_path.is_junction()):
        return {"prepared": False, "reason": "group-safe dataset manifest is unsafe"}
    try:
        manifest_path = manifest_path.resolve(strict=True)
        if not manifest_path.is_relative_to(state_root) or not manifest_path.is_file():
            raise ValueError("dataset manifest escaped state_dir")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {"prepared": False, "reason": "group-safe dataset manifest is unavailable"}

    if not isinstance(manifest, dict):
        return {"prepared": False, "reason": "group-safe dataset manifest is invalid"}
    source = manifest.get("source")
    train = manifest.get("train")
    evaluation = manifest.get("evaluation")
    integrity = manifest.get("split_integrity")
    if (
        manifest.get("dataset_format") != "card-training"
        or not isinstance(source, dict) or source.get("sha256") != dataset_sha256
        or not isinstance(train, dict) or not isinstance(evaluation, dict)
        or not isinstance(integrity, dict)
        or any(integrity.get(key) != 0 for key in ("id_overlap_count", "group_overlap_count", "content_hash_overlap_count"))
    ):
        return {"prepared": False, "reason": "group-safe dataset manifest does not match this export"}

    verified_sections: dict[str, dict[str, Any]] = {}
    for name, section in (("train", train), ("evaluation", evaluation)):
        rel = section.get("path")
        expected_hash = section.get("sha256")
        if not isinstance(rel, str) or not isinstance(expected_hash, str):
            return {"prepared": False, "reason": "group-safe dataset manifest has invalid file references"}
        path = (state_root / rel)
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            return {"prepared": False, "reason": "group-safe split contains an unsafe path"}
        try:
            path = path.resolve(strict=True)
            if not path.is_relative_to(state_root) or not path.is_file() or _file_sha256(path) != expected_hash:
                return {"prepared": False, "reason": "group-safe split hash does not match its manifest"}
        except OSError:
            return {"prepared": False, "reason": "group-safe split file is unavailable"}
        verified_sections[name] = {
            "path": path.relative_to(state_root).as_posix(),
            "sha256": expected_hash,
            "row_count": section.get("row_count"),
            "group_count": section.get("group_count"),
        }
    return {
        "prepared": True,
        "evaluation_status": "dataset_only",
        "reason": "group-held-out files and hashes are verified; existing card outputs are not independent quality labels",
        "dataset_manifest": manifest_path.relative_to(state_root).as_posix(),
        **verified_sections,
    }


def _validate_resume_output(path: Path, manifest_path: Path, format: str) -> None:
    manifest = None
    try:
        if manifest_path.exists():
            if not manifest_path.is_file() or manifest_path.stat().st_size > _MAX_EXPORT_BYTES:
                raise ValueError("existing card export manifest is not a bounded file")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
                    or manifest.get("dataset_kind") != "existing_hub_preprocess_cards"
                    or manifest.get("format") != format):
                raise ValueError("existing card export manifest does not match the requested format")
        if not path.exists():
            return
        if not path.is_file() or path.stat().st_size > _MAX_EXPORT_BYTES:
            raise ValueError("existing card export is not a bounded file")
        if manifest is not None and _file_sha256(path) == manifest.get("dataset_sha256"):
            return

        # A crash between replacing the dataset and its manifest leaves a complete JSONL file.
        content_field, content_type = ("messages", list) if format == "card-training" else ("text", str)
        seen: set[str] = set()
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                provenance = row.get("provenance") if isinstance(row, dict) else None
                if (not isinstance(provenance, dict) or provenance.get("source") != "existing_hub_preprocess_card"
                        or not isinstance(row.get("id"), str) or not row["id"]
                        or not isinstance(row.get(content_field), content_type)):
                    raise ValueError(f"existing card export line {line_number} has unrecognized provenance or format")
                if row["id"] in seen or len(seen) >= _MAX_EXPORT_ROWS:
                    raise ValueError("existing card export has duplicate rows or exceeds the row limit")
                seen.add(row["id"])
        if not seen and manifest is None:
            raise ValueError("cannot resume an empty existing card export without its manifest")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot resume existing card export: {exc}") from exc


def list_existing_card_candidates(
    *,
    state_dir: Path | str,
    format: str,
    roots_file: Path | str | None = None,
) -> dict[str, Any]:
    """List eligible card IDs and metadata without returning card or source text."""
    if format not in {"card-training", "embedding-corpus"}:
        raise ValueError("format must be card-training or embedding-corpus")
    raw_state_root = Path(state_dir)
    if raw_state_root.is_symlink() or (hasattr(raw_state_root, "is_junction") and raw_state_root.is_junction()):
        raise ValueError("state_dir cannot be a symlink or junction")
    state_root = raw_state_root.resolve(strict=True)
    if not state_root.is_dir():
        raise ValueError("state_dir must be an existing real directory")
    candidates: list[dict[str, Any]] = []
    counts = {"file_cards": 0, "module_cards": 0, "project_cards": 0,
              "missing_source_pairs": 0, "deterministic_cards_skipped": 0}
    database = state_root / "preprocess.sqlite3"
    with closing(_index_connection(database)) as connection:
        connection.execute("BEGIN")
        roots, root_count = _authorized_roots(connection, roots_file)
        stored_roots = sorted(roots.values())
        if len(stored_roots) > _MAX_ROOTS_PER_QUERY:
            raise ValueError(f"project root count exceeds SQLite query limit ({_MAX_ROOTS_PER_QUERY})")
        if not stored_roots:
            raise ValueError("no authorized roots found in the preprocessing index")
        placeholders = ",".join("?" for _ in stored_roots)
        query = _FILE_CARD_ROWS.format(placeholders=placeholders)
        for record in connection.execute(query, stored_roots):
            root_key, root_id = _root_identity(record["root"])
            if root_key not in roots:
                continue
            model = str(record["model"] or "")
            if model in _SYNTHETIC_CARD_MODELS:
                counts["deterministic_cards_skipped"] += 1
                continue
            path = str(record["path"])
            source_hash = _current_file_card_hash(record, format)
            if source_hash is None:
                counts["missing_source_pairs"] += 1
                continue
            _, card_hash, row_id = _card_identity(root_id, "file", path, str(record["card_json"]))
            candidates.append({
                "row_id": row_id,
                "root_id": root_id,
                "card_kind": "file",
                "relative_path": path,
                "card_sha256": card_hash,
                "source_sha256": source_hash,
                "card_model": model,
                "card_version": str(record["analyzer_version"] or ""),
            })
            counts["file_cards"] += 1

        if format == "embedding-corpus":
            for record in connection.execute(
                f"SELECT root,module,revision_hash,card_json FROM module_cards WHERE root IN ({placeholders}) ORDER BY root,module",
                stored_roots,
            ):
                root_key, root_id = _root_identity(record["root"])
                if root_key in roots:
                    card_key = str(record["module"])
                    _, card_hash, row_id = _card_identity(root_id, "module", card_key, str(record["card_json"]))
                    candidates.append({
                        "row_id": row_id, "root_id": root_id, "card_kind": "module",
                        "relative_path": "", "card_sha256": card_hash, "source_sha256": "",
                        "card_model": "", "card_version": str(record["revision_hash"]),
                    })
                    counts["module_cards"] += 1
            for record in connection.execute(
                f"SELECT root,revision_hash,card_json FROM project_cards WHERE root IN ({placeholders}) ORDER BY root",
                stored_roots,
            ):
                root_key, root_id = _root_identity(record["root"])
                if root_key in roots:
                    _, card_hash, row_id = _card_identity(root_id, "project", "project", str(record["card_json"]))
                    candidates.append({
                        "row_id": row_id, "root_id": root_id, "card_kind": "project",
                        "relative_path": "", "card_sha256": card_hash, "source_sha256": "",
                        "card_model": "", "card_version": str(record["revision_hash"]),
                    })
                    counts["project_cards"] += 1
    if len(candidates) > _MAX_EXPORT_ROWS:
        raise ValueError("existing card candidate count exceeds configured row limit")
    if not candidates:
        raise ValueError("no eligible existing Hub cards were found for this export format")
    return {
        "success": True, "format": format, "project_count": root_count,
        "candidate_count": len(candidates), "candidates": candidates,
        "counts": counts, "content_included": False,
    }


def export_existing_cards(
    *,
    state_dir: Path | str,
    output_path: Path | str,
    format: str,
    roots_file: Path | str | None = None,
    resume: bool = False,
    benchmark_cases_file: Path | str | None = None,
    benchmark_root: Path | str | None = None,
) -> dict[str, Any]:
    """Export stored Hub cards; never preprocess, call a model, or mutate the index."""
    if format not in {"card-training", "embedding-corpus"}:
        raise ValueError("format must be card-training or embedding-corpus")
    if benchmark_cases_file is not None and format != "embedding-corpus":
        raise ValueError("benchmark cases can be attached only to embedding-corpus exports")
    if benchmark_root is not None and benchmark_cases_file is None:
        raise ValueError("benchmark root requires benchmark cases")
    raw_state_root = Path(state_dir)
    if raw_state_root.is_symlink() or (hasattr(raw_state_root, "is_junction") and raw_state_root.is_junction()):
        raise ValueError("state_dir cannot be a symlink or junction")
    state_root = raw_state_root.resolve(strict=True)
    if not state_root.is_dir():
        raise ValueError("state_dir must be an existing real directory")
    requested_output = Path(output_path)
    if not requested_output.is_absolute():
        requested_output = state_root / requested_output
    if requested_output.is_symlink() or (hasattr(requested_output, "is_junction") and requested_output.is_junction()):
        raise ValueError("card dataset output cannot be a symlink or junction")
    output = requested_output.resolve(strict=False)
    if output == state_root or not output.is_relative_to(state_root):
        raise ValueError("card dataset output must remain inside configured state_dir")
    if any(_STAGING_NAME.fullmatch(part) for part in output.relative_to(state_root).parts):
        raise ValueError("card dataset output cannot be inside the private card export directory")
    database = state_root / "preprocess.sqlite3"
    index_paths = {database.with_name(database.name + suffix) for suffix in ("", "-wal", "-shm", "-journal")}
    if output in index_paths:
        raise ValueError("card dataset output cannot replace the preprocessing index or its side files")
    if output.name.casefold().endswith(".export.lock"):
        raise ValueError("card dataset output cannot replace an export lock")
    output.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_update(output.with_name(output.name + ".export")):
        return _export_existing_cards_locked(
            state_root=state_root, database=database, output=output, format=format, roots_file=roots_file,
            resume=resume, benchmark_cases_file=benchmark_cases_file, benchmark_root=benchmark_root,
        )


def _export_existing_cards_locked(
    *, state_root: Path, database: Path, output: Path, format: str, roots_file: Path | str | None,
    resume: bool, benchmark_cases_file: Path | str | None, benchmark_root: Path | str | None,
) -> dict[str, Any]:
    if output.is_symlink() or (hasattr(output, "is_junction") and output.is_junction()):
        raise ValueError("card dataset output cannot be a symlink or junction")
    manifest_path = output.with_name(output.name + ".manifest.json")
    if manifest_path.is_symlink() or (hasattr(manifest_path, "is_junction") and manifest_path.is_junction()):
        raise ValueError("card dataset manifest cannot be a symlink or junction")
    if (output.exists() or manifest_path.exists()) and not resume:
        raise ValueError(f"output exists; pass resume=True to rebuild it from the current index: {output}")
    if resume:
        _validate_resume_output(output, manifest_path, format)
    staging = _prepare_staging(output)

    rows: list[dict[str, Any]] = []
    output_bytes = 0
    counts = {"file_cards": 0, "module_cards": 0, "project_cards": 0, "missing_source_pairs": 0,
             "deterministic_cards_skipped": 0}

    def append_row(row: dict[str, Any]) -> None:
        nonlocal output_bytes
        output_bytes += len(_canonical(row).encode("utf-8")) + 1
        if len(rows) >= _MAX_EXPORT_ROWS or output_bytes > _MAX_EXPORT_BYTES:
            raise ValueError("existing card export exceeds configured row or byte limit")
        rows.append(row)

    with closing(_index_connection(database)) as connection:
        connection.execute("BEGIN")
        roots, root_count = _authorized_roots(connection, roots_file)
        stored_roots = sorted(roots.values())
        if len(stored_roots) > _MAX_ROOTS_PER_QUERY:
            raise ValueError(f"project root count exceeds SQLite query limit ({_MAX_ROOTS_PER_QUERY})")
        if not stored_roots:
            raise ValueError("no authorized roots found in the preprocessing index")
        placeholders = ",".join("?" for _ in stored_roots)

        query = _FILE_CARD_ROWS.format(placeholders=placeholders)
        for record in connection.execute(query, stored_roots):
            root_key, root_id = _root_identity(record["root"])
            if root_key not in roots:
                continue
            model = str(record["model"] or "")
            if model in _SYNTHETIC_CARD_MODELS:
                counts["deterministic_cards_skipped"] += 1
                continue
            source_hash = _current_file_card_hash(record, format)
            if source_hash is None:
                counts["missing_source_pairs"] += 1
                continue
            card_json = str(record["card_json"])
            source_text = ""
            if format == "card-training":
                source_record = connection.execute(
                    "SELECT text,content_hash FROM source_index WHERE root=? AND path=?",
                    (record["root"], record["path"]),
                ).fetchone()
                if (source_record is None or source_record["content_hash"] != source_hash
                        or not isinstance(source_record["text"], str) or not source_record["text"]):
                    counts["missing_source_pairs"] += 1
                    continue
                source_text = str(source_record["text"])
            exported = _card_row(
                root_id=root_id, card_kind="file", card_key=str(record["path"]),
                card_json=card_json, card_model=model,
                card_version=str(record["analyzer_version"] or ""),
                path=str(record["path"]), source_hash=source_hash, source_text=source_text,
            )
            append_row(exported)
            counts["file_cards"] += 1

        if format == "embedding-corpus":
            for record in connection.execute(
                f"SELECT root,module,revision_hash,card_json FROM module_cards WHERE root IN ({placeholders}) ORDER BY root,module",
                stored_roots,
            ):
                root_key, root_id = _root_identity(record["root"])
                if root_key in roots:
                    card_key = str(record["module"])
                    card_json = str(record["card_json"])
                    exported = _card_row(
                        root_id=root_id, card_kind="module", card_key=card_key,
                        card_json=card_json, card_model="", card_version=str(record["revision_hash"]),
                    )
                    append_row(exported)
                    counts["module_cards"] += 1
            for record in connection.execute(
                f"SELECT root,revision_hash,card_json FROM project_cards WHERE root IN ({placeholders}) ORDER BY root",
                stored_roots,
            ):
                root_key, root_id = _root_identity(record["root"])
                if root_key in roots:
                    card_json = str(record["card_json"])
                    exported = _card_row(
                        root_id=root_id, card_kind="project", card_key="project",
                        card_json=card_json, card_model="", card_version=str(record["revision_hash"]),
                    )
                    append_row(exported)
                    counts["project_cards"] += 1

    if not rows and not (resume and output.is_file()):
        raise ValueError("no eligible existing Hub cards were found for this export format")
    chunks = ((_canonical(row) + "\n").encode("utf-8") for row in rows)
    dataset_file = staging / "dataset.tmp"
    manifest_file = staging / "manifest.tmp"
    with _stage_bytes(dataset_file, chunks) as dataset_sha256:
        manifest = {
            "schema_version": 1,
            "dataset_kind": "existing_hub_preprocess_cards",
            "format": format,
            "data_class": "local_scoped" if format == "card-training" else "existing_local",
            "source": "already_indexed_preprocess_cards",
            "project_count": root_count,
            "row_count": len(rows),
            "group_count": len({row["group_id"] for row in rows}),
            "counts": counts,
            "dataset_sha256": dataset_sha256,
            "model_calls": 0,
            "preprocessing_started": False,
            "benchmark_inputs": _benchmark_inputs(
                output=output, staging=staging, state_root=state_root, format=format, dataset_sha256=dataset_sha256,
                benchmark_cases_file=benchmark_cases_file, benchmark_root=benchmark_root, rows=rows,
            ),
        }
        with _stage_bytes(manifest_file, (_json_bytes(manifest),)):
            dataset_file.replace(output)
            manifest_file.replace(manifest_path)
    return {
        "success": True,
        "format": format,
        "output_path": str(output),
        "row_count": len(rows),
        "project_count": root_count,
        "counts": counts,
        "manifest_path": str(manifest_path),
        "dataset_sha256": dataset_sha256,
        "benchmark_inputs_prepared": manifest["benchmark_inputs"]["prepared"],
        "retrieval_evaluation_prepared": manifest["benchmark_inputs"].get("retrieval_evaluation", {}).get("prepared", False),
        "model_calls": 0,
        "preprocessing_started": False,
    }
