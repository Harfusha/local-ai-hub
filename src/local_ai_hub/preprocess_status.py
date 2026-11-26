from __future__ import annotations

from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from .process_utils import canonical_root

logger = logging.getLogger(__name__)
_STATUS_CACHE_TTL_SECONDS = 3.0

__all__ = [
    "_project_git_identity",
    "calculate_speed_and_eta",
    "derive_preprocess_status",
    "fetch_derived_index_counts",
    "fetch_file_and_external_counts",
    "fetch_index_file_counts",
    "fetch_rag_workspace_stats",
    "format_global_diagnostic",
    "format_status_details",
    "root_batches",
]


def _project_git_identity(root: str) -> tuple[str, bool]:
    """Return a local Git common-dir identity without guessing from path names."""
    if not isinstance(root, str) or not root.strip() or "\x00" in root:
        return "", False
    try:
        resolved_root = Path(root).resolve(strict=False)
        marker = resolved_root / ".git"
        if marker.is_dir():
            return str(marker.resolve(strict=False)), False
        if not marker.is_file():
            return str(resolved_root), False

        marker_text = marker.read_text(encoding="utf-8", errors="replace")[:1024]
        prefix, separator, raw_git_dir = marker_text.partition(":")
        if prefix.strip().casefold() != "gitdir" or not separator or not raw_git_dir.strip():
            return str(resolved_root), False
        git_dir = Path(raw_git_dir.strip())
        if not git_dir.is_absolute():
            git_dir = resolved_root / git_dir
        git_dir = git_dir.resolve(strict=False)

        common_dir_file = git_dir / "commondir"
        if not common_dir_file.is_file():
            return str(git_dir), False
        raw_common_dir = common_dir_file.read_text(encoding="utf-8", errors="replace")[:1024].strip()
        if not raw_common_dir:
            return str(resolved_root), False
        common_dir = Path(raw_common_dir)
        if not common_dir.is_absolute():
            common_dir = git_dir / common_dir
        common_dir = common_dir.resolve(strict=False)
        return str(common_dir), common_dir != git_dir
    except (OSError, RuntimeError, ValueError):
        return "", False


def root_batches(values: list[str], batch_size: int = 400) -> Iterator[list[str]]:
    """Yield successive slices of values up to batch_size."""
    for offset in range(0, len(values), batch_size):
        yield values[offset : offset + batch_size]


def fetch_rag_workspace_stats(
    rag: Any, rows: list[Any]
) -> dict[str, dict[str, int]] | None:
    """Read RAG workspace statistics if available."""
    rag_workspace_stats: dict[str, dict[str, int]] | None = None
    rag_stats_reader = getattr(rag, "workspace_stats", None)
    if callable(rag_stats_reader):
        try:
            workspaces = list(dict.fromkeys(
                str(row["workspace"]) for row in rows if row["workspace"]
            ))
            raw_rag_stats = rag_stats_reader(workspaces)
            if isinstance(raw_rag_stats, dict):
                rag_workspace_stats = raw_rag_stats
        except Exception as exc:
            logger.debug("RAG workspace status unavailable (%s)", type(exc).__name__)
    return rag_workspace_stats


def fetch_file_and_external_counts(
    con: sqlite3.Connection,
    roots: list[str],
    enrich_stubs: bool,
    enrichment_model: str,
    enrichment_pipeline: str,
    file_card_max_bytes: int,
) -> tuple[
    dict[str, tuple[int, int, int, int]],
    dict[str, dict[str, dict[str, Any]]],
    dict[str, int],
    dict[str, int],
]:
    """Batch-fetch file counts, external index states, and pending stub card counts."""
    file_counts: dict[str, tuple[int, int, int, int]] = {}
    external_by_root: dict[str, dict[str, dict[str, Any]]] = {value: {} for value in roots}
    pending_stub_counts: dict[str, int] = {}
    failed_enrichment_counts: dict[str, int] = {}

    for batch in root_batches(roots):
        placeholders = ",".join("?" for _ in batch)
        count_rows = con.execute(
            f"""SELECT root, COUNT(*),
                SUM(CASE WHEN card_key IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN needs_hash=0 AND content_hash<>'' THEN 1 ELSE 0 END),
                SUM(CASE WHEN COALESCE(rag_hash,'')=content_hash AND content_hash<>'' THEN 1 ELSE 0 END)
            FROM file_refs WHERE root IN ({placeholders}) GROUP BY root""",
            batch,
        ).fetchall()
        file_counts.update({
            str(count_row[0]): tuple(int(value or 0) for value in count_row[1:5])
            for count_row in count_rows
        })
        if enrich_stubs:
            stub_rows = con.execute(
                f"""SELECT f.root, COUNT(*) FROM file_refs f
                    JOIN content_cards c ON c.card_key=f.card_key
                    WHERE f.root IN ({placeholders})
                      AND c.model IN ('deterministic','deterministic-stub','deterministic-barrel')
                      AND f.size<=? AND NOT EXISTS (
                          SELECT 1 FROM file_card_enrichment e
                          WHERE e.content_hash=f.content_hash AND e.model=? AND e.pipeline_version=?
                            AND e.status='failed' AND e.attempts>=3
                      ) GROUP BY f.root""",
                (*batch, file_card_max_bytes, enrichment_model, enrichment_pipeline),
            ).fetchall()
            pending_stub_counts.update({str(item[0]): int(item[1]) for item in stub_rows})
            failed_rows = con.execute(
                f"""SELECT f.root, COUNT(DISTINCT f.content_hash) FROM file_refs f
                    JOIN content_cards c ON c.card_key=f.card_key
                    JOIN file_card_enrichment e ON e.content_hash=f.content_hash
                      AND e.model=? AND e.pipeline_version=? AND e.status='failed'
                    WHERE f.root IN ({placeholders})
                      AND c.model IN ('deterministic','deterministic-stub','deterministic-barrel')
                      AND f.size<=? GROUP BY f.root""",
                (enrichment_model, enrichment_pipeline, *batch, file_card_max_bytes),
            ).fetchall()
            failed_enrichment_counts.update({str(item[0]): int(item[1]) for item in failed_rows})
        external_rows = con.execute(
            f"SELECT root,backend,status,error,updated_at FROM external_index_state WHERE root IN ({placeholders})",
            batch,
        ).fetchall()
        for external_row in external_rows:
            external_by_root[str(external_row[0])][str(external_row[1])] = {
                "status": "unavailable" if str(external_row[2]) == "skipped" else str(external_row[2]),
                "error": str(external_row[3] or ""),
                "updated_at": float(external_row[4] or 0),
            }

    return file_counts, external_by_root, pending_stub_counts, failed_enrichment_counts


def fetch_derived_index_counts(
    con: sqlite3.Connection,
    roots: list[str],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Batch-fetch source index, module cards, and project cards counts."""
    source_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    project_card_counts: dict[str, int] = {}
    for batch in root_batches(roots):
        placeholders = ",".join("?" for _ in batch)
        for table, target in (
            ("source_index", source_counts),
            ("module_cards", module_counts),
            ("project_cards", project_card_counts),
        ):
            count_rows = con.execute(
                f"SELECT root, COUNT(*) FROM {table} WHERE root IN ({placeholders}) GROUP BY root",
                batch,
            ).fetchall()
            target.update({str(count_row[0]): int(count_row[1] or 0) for count_row in count_rows})
    return source_counts, module_counts, project_card_counts


def fetch_index_file_counts(
    index: Any | None,
    label: str,
    scope_roots: list[str],
) -> dict[str, int]:
    """Query external SQLite index for per-root indexed file counts."""
    result: dict[str, int] = {}
    if index is None or not scope_roots:
        return result
    try:
        with closing(index._connect()) as index_con:
            for batch in root_batches(scope_roots):
                placeholders = ",".join("?" for _ in batch)
                count_rows = index_con.execute(
                    f"SELECT root, COUNT(*) FROM files WHERE root IN ({placeholders}) GROUP BY root",
                    batch,
                ).fetchall()
                result.update({str(count_row[0]): int(count_row[1] or 0) for count_row in count_rows})
    except sqlite3.Error as exc:
        logger.warning("%s status unavailable (%s)", label, type(exc).__name__)
    return result


def calculate_speed_and_eta(
    *,
    root: str,
    status_str: str,
    phase_str: str,
    phase_pct: float,
    total_files: int,
    effective_file_cards: int,
    rag_files: int,
    hashed_files: int,
    ci_count: int,
    det_count: int,
    source_count: int,
    external_indexes: dict[str, Any],
    speed_tracker: dict[str, list[tuple[float, int]]],
    stats_lock: Any | None,
    row_updated_at: float | None,
) -> tuple[str, str, float]:
    """Calculate processing throughput speed, ETA string, and progress age."""
    now = time.time()
    if stats_lock is not None:
        with stats_lock:
            history = speed_tracker.get(root, [])
            cutoff = now - 30.0
            valid = [(t, c) for t, c in history if t >= cutoff]
            speed_tracker[root] = valid
    else:
        history = speed_tracker.get(root, [])
        cutoff = now - 30.0
        valid = [(t, c) for t, c in history if t >= cutoff]
        speed_tracker[root] = valid

    progress_at = valid[-1][0] if valid else float(row_updated_at or now)
    progress_age_seconds = max(0.0, time.time() - progress_at)

    speed_rate = 0.0
    speed_str = "idle"
    eta_str = "—"

    if status_str == "complete" or phase_str == "complete":
        speed_str = "ready"
        eta_str = "0s"
    elif status_str == "running":
        if len(valid) >= 2:
            dt = max(0.5, valid[-1][0] - valid[0][0])
            done_items = sum(c for _, c in valid[1:])
            speed_rate = round(done_items / dt, 1)

        if phase_str in ("files", "modules", "project"):
            unit = "cards/s"
            remaining = max(0, total_files - effective_file_cards)
        elif phase_str == "rag":
            unit = "files/s"
            remaining = max(0, total_files - rag_files)
        elif phase_str in ("hash", "code_index", "deterministic", "lexical"):
            unit = "files/s"
            remaining = max(
                0,
                total_files
                - (
                    hashed_files
                    if phase_str == "hash"
                    else (
                        ci_count
                        if phase_str == "code_index"
                        else (det_count if phase_str == "deterministic" else source_count)
                    )
                ),
            )
        elif phase_str in {"serena", "serena_optional"}:
            unit = "index"
            remaining = (
                0
                if external_indexes.get("serena", {}).get("status")
                in {"ready", "unavailable", "skipped", "degraded"}
                else 1
            )
        else:
            unit = "ops/s"
            remaining = max(0, total_files)

        if remaining <= 0 or phase_pct >= 100.0:
            speed_str = "finalizing"
            eta_str = "next phase"
        elif speed_rate > 0.05:
            speed_str = f"{speed_rate:.1f} {unit}"
            eta_seconds = int(remaining / speed_rate)
            if eta_seconds < 60:
                eta_str = f"{eta_seconds}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds // 60}m {eta_seconds % 60}s"
            else:
                eta_str = f"{eta_seconds // 3600}h {(eta_seconds % 3600) // 60}m"
        else:
            speed_str = "batch in progress"
            eta_str = "measuring…"

    return speed_str, eta_str, progress_age_seconds


def format_status_details(
    *,
    row: Any,
    status_str: str,
    phase_str: str,
    phase_pct: float,
    overall_progress: float,
    total_files: int,
    effective_file_cards: int,
    pending_stub_cards: int,
    rag_files: int,
    hashed_files: int,
    ci_count: int,
    det_count: int,
    source_count: int,
    module_count: int,
    external_indexes: dict[str, Any],
    background_gpu: Any,
    bg_allowed: bool,
    project_limit: int,
) -> tuple[bool, str, str, str, str, float, bool]:
    """Derive waiting state, waiting reason, and active detail string for a project row."""
    last_err = str(row["last_error"] or "")
    last_err_short = last_err.strip().splitlines()[0][:90] if last_err else ""
    retry_after_val = float(row["retry_after"] or 0)
    is_paused_row = bool(row["paused"])
    is_slot_waiting = status_str == "waiting" and not is_paused_row
    is_model_waiting = bool(
        status_str == "running"
        and phase_str == "files"
        and pending_stub_cards
        and background_gpu is not None
        and bool(getattr(background_gpu, "enabled", True))
        and not background_gpu.ready()
    )
    is_scheduler_waiting = status_str == "running" and phase_str == "rag" and not bg_allowed
    is_queue_waiting = status_str == "queued" and not is_paused_row
    is_waiting_row = is_slot_waiting or is_model_waiting or is_scheduler_waiting or is_queue_waiting

    waiting_reason = ""
    if is_paused_row:
        waiting_reason = "Project is paused"
    elif is_slot_waiting:
        waiting_reason = f"Waiting for preprocessing slot (max {project_limit})"
    elif status_str == "error":
        waiting_reason = f"Error: {last_err_short}" if last_err_short else "Project encountered an error"
    elif retry_after_val > time.time():
        waiting_reason = f"Cooldown ({int(retry_after_val - time.time())}s remaining)"
    elif status_str == "complete":
        waiting_reason = (
            f"Index complete; {pending_stub_cards} card enrichments remain"
            if pending_stub_cards
            else "100% complete and up to date"
        )
    elif is_model_waiting:
        waiting_reason = "Waiting for preprocessing model or resources"
    elif is_scheduler_waiting:
        waiting_reason = "Waiting for scheduler background capacity"
    elif status_str == "running":
        waiting_reason = f"Processing phase: {phase_str}"
    elif status_str == "queued":
        if not bg_allowed:
            waiting_reason = "Waiting for scheduler background capacity"
        else:
            waiting_reason = "Queued for worker execution"

    active_detail = ""
    if status_str == "complete" or phase_str == "complete" or overall_progress >= 100.0:
        active_detail = (
            f"Index complete · {pending_stub_cards} awaiting enrichment"
            if pending_stub_cards
            else "100% ready · Real-time file sync"
        )
    elif is_paused_row:
        active_detail = "Project is paused"
    elif is_slot_waiting:
        active_detail = f"Waiting for preprocessing slot (max {project_limit})"
    elif is_model_waiting:
        active_detail = (
            f"{waiting_reason}: {effective_file_cards}/{total_files} files "
            f"({phase_pct}%) · {pending_stub_cards} awaiting enrichment"
        )
    elif is_scheduler_waiting:
        active_detail = (
            f"{waiting_reason}: RAG-synced files {rag_files}/{total_files} "
            f"({phase_pct}%)"
        )
    elif status_str == "error":
        active_detail = f"Error: {last_err_short}" if last_err_short else "Error during processing"
    elif phase_str == "inventory":
        active_detail = f"Discovering file inventory ({total_files} files)"
    elif phase_str == "hash":
        active_detail = f"Hashing content: {hashed_files}/{total_files} files ({phase_pct}%)"
    elif phase_str == "code_index":
        active_detail = f"AST symbol extraction: {ci_count}/{total_files} files ({phase_pct}%)"
    elif phase_str == "deterministic":
        active_detail = f"Facts & routes extraction: {det_count}/{total_files} files ({phase_pct}%)"
    elif phase_str in {"serena", "serena_optional"}:
        ext = external_indexes.get("serena", {})
        s_st = ext.get("status", "running")
        reason = (
            f": {ext.get('error')}"
            if s_st in {"unavailable", "skipped", "degraded"} and ext.get("error")
            else ""
        )
        active_detail = f"Serena LSP project indexing ({s_st}{reason})"
    elif phase_str == "lexical":
        active_detail = f"FTS5 full-text indexing: {source_count}/{total_files} files ({phase_pct}%)"
    elif phase_str == "rag":
        active_detail = f"RAG-synced files: {rag_files}/{total_files} files ({phase_pct}%)"
    elif phase_str == "files":
        active_detail = f"Generating semantic cards: {effective_file_cards}/{total_files} files ({phase_pct}%)"
        if pending_stub_cards:
            active_detail += f" · {pending_stub_cards} awaiting enrichment"
    elif phase_str == "modules":
        active_detail = f"Module graph synthesis ({module_count} modules)"
    elif phase_str == "project":
        active_detail = "Project architecture synthesis"
    elif phase_str == "hot_queries":
        active_detail = "Pre-warming top query embeddings & capsules"
    else:
        active_detail = f"Processing {phase_str} ({phase_pct}%)"

    return (
        is_waiting_row,
        waiting_reason,
        active_detail,
        last_err,
        last_err_short,
        retry_after_val,
        is_paused_row,
    )


def format_global_diagnostic(
    *,
    enabled: bool,
    is_paused: bool,
    projects: list[dict[str, Any]],
    bg_allowed: bool,
) -> str:
    """Format global preprocessing diagnostic message."""
    if not enabled:
        return "Preprocessing is disabled in config (preprocessing.enabled = false)."
    if is_paused:
        return "Preprocessing is GLOBALLY PAUSED."
    if not projects:
        return "No projects registered. Register a repository path to start background preprocessing."
    if any(p["status"] == "error" for p in projects):
        err_names = [p["project"] for p in projects if p["status"] == "error"]
        return f"Errors detected in project(s): {', '.join(err_names)}."
    if all(p["status"] == "complete" for p in projects):
        return f"All {len(projects)} registered project(s) are 100% indexed and up to date."
    if not bg_allowed:
        return "Background processing is waiting for scheduler capacity."
    return "Background preprocessing is actively running."


def derive_preprocess_status(
    preprocessor: Any,
    root: str | None = None,
) -> dict[str, Any]:
    """Calculate and return live preprocessing status snapshot for all or a specific project."""
    now_mono = time.monotonic()
    key = str(root or "__all__")
    mode_paused = not (
        preprocessor._background_work_allowed()
        if hasattr(preprocessor, "_background_work_allowed")
        else True
    )
    if not hasattr(preprocessor, "_status_cache"):
        preprocessor._status_cache = {}
    cached = preprocessor._status_cache.get(key)
    if cached and cached.get("mode_paused") == mode_paused and now_mono - cached["time"] < _STATUS_CACHE_TTL_SECONDS:
        return dict(cached["data"])

    with closing(preprocessor._connect()) as con:
        if root is not None:
            norm_root = (
                preprocessor._root(root)
                if hasattr(preprocessor, "_root")
                else canonical_root(root)
            )
            rows = con.execute("SELECT * FROM projects WHERE root=?", (norm_root,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()

        rag_workspace_stats = fetch_rag_workspace_stats(getattr(preprocessor, "rag", None), rows)

        roots = [str(row["root"]) for row in rows]
        incomplete_roots = [
            str(row["root"])
            for row in rows
            if str(row["status"] or "queued") != "complete"
            and str(row["phase"] or "inventory") != "complete"
        ]

        enrich_stubs = (
            preprocessor._file_card_enrichment_enabled()
            if hasattr(preprocessor, "_file_card_enrichment_enabled")
            else False
        )
        enrichment_model = (
            preprocessor._configured_preprocessing_model()
            if hasattr(preprocessor, "_configured_preprocessing_model")
            else ""
        )
        enrichment_pipeline = (
            preprocessor._file_card_pipeline_version()
            if hasattr(preprocessor, "_file_card_pipeline_version")
            else ""
        )
        cfg = getattr(preprocessor, "cfg", {}) or {}
        file_card_max_bytes = int(cfg.get("file_card_max_bytes", 180000))

        (
            file_counts,
            external_by_root,
            pending_stub_counts,
            failed_enrichment_counts,
        ) = fetch_file_and_external_counts(
            con=con,
            roots=roots,
            enrich_stubs=enrich_stubs,
            enrichment_model=enrichment_model,
            enrichment_pipeline=enrichment_pipeline,
            file_card_max_bytes=file_card_max_bytes,
        )

        source_counts, module_counts, project_card_counts = fetch_derived_index_counts(con, roots)

        code_index_counts = fetch_index_file_counts(
            getattr(preprocessor, "code_index", None), "Code-index", roots
        )
        deterministic_counts = fetch_index_file_counts(
            getattr(preprocessor, "deterministic", None), "Deterministic-index", incomplete_roots
        )

        projects: list[dict[str, Any]] = []
        bg_allowed = (
            preprocessor._scheduler_background_allowed()
            if hasattr(preprocessor, "_scheduler_background_allowed")
            else True
        )
        project_limit = (
            preprocessor._project_limit()
            if hasattr(preprocessor, "_project_limit")
            else getattr(preprocessor, "max_preprocessing_projects", 1)
        )
        phases = getattr(preprocessor, "PHASES", ())
        total_phases = len(phases)

        for row in rows:
            git_common_dir, is_worktree = _project_git_identity(str(row["root"]))
            status_str = str(row["status"] or "queued")
            phase_str = "complete" if status_str == "complete" else str(row["phase"] or "inventory")
            try:
                phase_index = phases.index(phase_str) + 1
            except (ValueError, AttributeError):
                phase_index = total_phases if status_str == "complete" else 1

            counts = file_counts.get(str(row["root"]), (0, 0, 0, 0))
            total_files = int(counts[0] or 0)
            file_cards = min(total_files, int(counts[1] or 0))
            pending_stub_cards = pending_stub_counts.get(str(row["root"]), 0)
            effective_file_cards = max(0, file_cards - pending_stub_cards)
            hashed_files = min(total_files, int(counts[2] or 0))
            rag_files = min(total_files, int(counts[3] or 0))

            source_count = source_counts.get(str(row["root"]), 0)
            ci_count = min(total_files, max(0, code_index_counts.get(str(row["root"]), 0)))
            det_count = 0
            if status_str != "complete" and phase_str != "complete":
                det_count = min(total_files, max(0, deterministic_counts.get(str(row["root"]), 0)))
            module_count = module_counts.get(str(row["root"]), 0)
            project_card_count = project_card_counts.get(str(row["root"]), 0)
            external_indexes = external_by_root.get(str(row["root"]), {})

            rag_workspace = (
                rag_workspace_stats.get(str(row["workspace"] or ""), {})
                if rag_workspace_stats is not None
                else None
            )
            rag_indexed_files = (
                max(0, int(rag_workspace.get("files", 0)))
                if isinstance(rag_workspace, dict)
                else None
            )
            rag_chunked_files = (
                max(0, int(rag_workspace.get("chunked_files", 0)))
                if isinstance(rag_workspace, dict)
                else None
            )
            rag_chunks = (
                max(0, int(rag_workspace.get("chunks", 0)))
                if isinstance(rag_workspace, dict)
                else None
            )
            rag_read_uncertain_files = (
                max(0, int(rag_workspace.get("read_uncertain_files", 0)))
                if isinstance(rag_workspace, dict)
                else None
            )

            # Phase progress percentage
            if status_str == "complete" or phase_str == "complete":
                status_str = "complete"
                phase_str = "complete"
                phase_index = total_phases
                phase_pct = 100.0
                overall_progress = 100.0
            elif phase_str == "inventory":
                phase_pct = 100.0
                overall_progress = round((1.0 / total_phases) * 100, 1) if total_phases else 0.0
            elif phase_str == "hash" and total_files:
                phase_pct = round((hashed_files / total_files) * 100, 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "code_index" and total_files:
                phase_pct = round(min(100.0, (ci_count / total_files) * 100), 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "deterministic" and total_files:
                phase_pct = round(min(100.0, (det_count / total_files) * 100), 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str in {"serena", "serena_optional"}:
                ext_state = external_indexes.get("serena", {}).get("status", "")
                phase_pct = 100.0 if ext_state in {"ready", "unavailable", "skipped", "degraded"} else 25.0
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "lexical" and total_files:
                phase_pct = round(min(100.0, (source_count / total_files) * 100), 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "rag" and total_files:
                phase_pct = round((rag_files / total_files) * 100, 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "files" and total_files:
                phase_pct = round((effective_file_cards / total_files) * 100, 1)
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "modules":
                phase_pct = (
                    round(min(100.0, (module_count / max(1, module_count + 1)) * 100), 1)
                    if module_count
                    else 50.0
                )
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "project":
                phase_pct = 100.0 if project_card_count else 50.0
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            elif phase_str == "hot_queries":
                phase_pct = 75.0
                frac = phase_pct / 100.0
                overall_progress = (
                    round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                    if total_phases
                    else 0.0
                )
            else:
                phase_pct = 0.0
                overall_progress = 0.0

            if hasattr(preprocessor, "calculate_overall_progress"):
                overall_progress = preprocessor.calculate_overall_progress(
                    phase_str, phase_pct, status_str == "complete" or phase_str == "complete"
                )

            speed_str, eta_str, progress_age_seconds = calculate_speed_and_eta(
                root=str(row["root"]),
                status_str=status_str,
                phase_str=phase_str,
                phase_pct=phase_pct,
                total_files=total_files,
                effective_file_cards=effective_file_cards,
                rag_files=rag_files,
                hashed_files=hashed_files,
                ci_count=ci_count,
                det_count=det_count,
                source_count=source_count,
                external_indexes=external_indexes,
                speed_tracker=getattr(preprocessor, "_speed_tracker", {}),
                stats_lock=getattr(preprocessor, "_stats_lock", None),
                row_updated_at=float(row["updated_at"] or 0) if row["updated_at"] else None,
            )

            (
                is_waiting_row,
                waiting_reason,
                active_detail,
                last_err,
                last_err_short,
                retry_after_val,
                is_paused_row,
            ) = format_status_details(
                row=row,
                status_str=status_str,
                phase_str=phase_str,
                phase_pct=phase_pct,
                overall_progress=overall_progress,
                total_files=total_files,
                effective_file_cards=effective_file_cards,
                pending_stub_cards=pending_stub_cards,
                rag_files=rag_files,
                hashed_files=hashed_files,
                ci_count=ci_count,
                det_count=det_count,
                source_count=source_count,
                module_count=module_count,
                external_indexes=external_indexes,
                background_gpu=getattr(preprocessor, "background_gpu", None),
                bg_allowed=bg_allowed,
                project_limit=project_limit,
            )

            project_stats = json.loads(row["stats_json"] or "{}")
            if isinstance(project_stats, dict):
                changed_paths = project_stats.pop("changed_paths", None)
                if isinstance(changed_paths, list):
                    project_stats["changed_paths_count"] = len(changed_paths)
            else:
                project_stats = {}

            projects.append({
                "root": row["root"], "project": Path(row["root"]).name, "workspace": row["workspace"],
                "git_common_dir": git_common_dir, "is_worktree": is_worktree,
                "status": status_str, "phase": phase_str,
                "paused": is_paused_row, "waiting": is_waiting_row, "last_error": last_err, "last_error_short": last_err_short,
                "retry_after": retry_after_val, "waiting_reason": waiting_reason,
                "active_detail": active_detail,
                "phase_index": phase_index, "total_phases": total_phases,
                "phase_progress_pct": phase_pct, "overall_progress_pct": overall_progress,
                "phase_progress_measured": phase_str in {"hash", "code_index", "deterministic", "lexical", "rag", "files", "complete"} and (total_files > 0 or phase_str == "complete"),
                "speed_str": speed_str, "eta_str": eta_str, "last_complete_at": row["last_complete_at"],
                "progress_age_seconds": round(progress_age_seconds, 1),
                "files": total_files, "file_cards": file_cards, "hashed_files": hashed_files, "rag_files": rag_files,
                "rag_indexed_files": rag_indexed_files,
                "rag_chunked_files": rag_chunked_files, "rag_chunks": rag_chunks,
                "rag_read_uncertain_files": rag_read_uncertain_files,
                "lexical_files": source_count,
                "deterministic_files": det_count if status_str != "complete" else None,
                "module_cards": module_count, "project_cards": project_card_count,
                "pending_stub_cards": pending_stub_cards,
                "pending_file_card_enrichment": pending_stub_cards,
                "failed_file_card_enrichment": failed_enrichment_counts.get(str(row["root"]), 0),
                "code_index_files": ci_count,
                "code_index_coverage": {
                    "complete": False, "scope": "demand_indexed_files",
                    "indexed_files": ci_count, "project_files": total_files,
                },
                "stats": project_stats, "external_indexes": external_indexes,
            })

    is_paused = (
        preprocessor._paused.is_set()
        if hasattr(preprocessor, "_paused") and hasattr(preprocessor._paused, "is_set")
        else False
    )
    enabled = getattr(preprocessor, "enabled", True)
    global_diagnostic = format_global_diagnostic(
        enabled=enabled,
        is_paused=is_paused,
        projects=projects,
        bg_allowed=bg_allowed,
    )

    reuse_rate_fn = getattr(preprocessor, "ingestion_reuse_rate", None)
    reuse_rate = reuse_rate_fn() if callable(reuse_rate_fn) else 0.0

    res = {
        "success": True, "enabled": enabled, "paused": is_paused or mode_paused,
        "phases": list(phases), "projects": projects,
        "scheduler_background_allowed": bg_allowed,
        "global_diagnostic": global_diagnostic,
        "ingestion_reuse_rate": reuse_rate,
    }
    preprocessor._status_cache[key] = {"time": now_mono, "data": dict(res), "mode_paused": mode_paused}
    return res
