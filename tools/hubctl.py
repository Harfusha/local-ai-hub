from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.config import load_config
from local_ai_hub.llama_cpp_runtime import llama_cpp_backend_selection
from local_ai_hub.process_utils import hidden_run_kwargs

ROOT_CONFIG = ROOT / "config.toml"
ACTIVITY_MODES = ("active", "gaming", "maintenance", "preprocessing")


def is_valid_activity_mode(mode: Any) -> bool:
    """Return True if mode is a supported Local AI Hub activity mode."""
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() in ACTIVITY_MODES


def _config_arg(explicit: Path | None = None) -> str | None:
    if explicit is not None:
        if not isinstance(explicit, (str, Path)) or "\x00" in str(explicit):
            return None
        return str(Path(explicit).expanduser())
    configured = os.environ.get("LOCAL_AI_CONFIG")
    if configured and "\x00" not in configured:
        return configured
    return str(ROOT_CONFIG) if ROOT_CONFIG.is_file() else None


def client() -> HubClient:
    return HubClient(config_path=_config_arg())


def status(explicit_config: Path | None = None) -> dict:
    c = HubClient(config_path=_config_arg(explicit_config))
    if not c._online(timeout=2.0):
        return {"running": False}
    try:
        # The live light endpoint intentionally omits model inventory. The
        # status command must also report configured llama.cpp models.
        data = c.get("/api/status")
    except Exception:
        data = {}
    data["running"] = True
    return data


def _activity_mode_request(mode: str | None = None, *, config_path: str | None = None) -> dict[str, Any]:
    """Read or change activity mode through the loopback-only Hub API."""
    try:
        c = HubClient(config_path=config_path or _config_arg(), auto_start=False)
        if not c._online(timeout=2.0):
            if mode == "preprocessing":
                return {"success": False, "server_status": "offline", "error": "preprocessing mode requires a running Hub"}
            config = load_config(config_path or _config_arg())
            server = config.get("server", {})
            state_dir = server.get("state_dir") if isinstance(server, dict) else None
            if not state_dir:
                return {"success": False, "server_status": "offline", "error": "operational mode state directory is not configured"}
            from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode

            snapshot = (
                load_operational_mode(state_dir)
                if mode is None
                else set_operational_mode(state_dir, mode)
            )
            if snapshot.degraded:
                return {"success": False, "server_status": "offline", "error": snapshot.error}
            result = {"success": True, **snapshot.to_dict(), "server_status": "offline"}
            if mode == "gaming":
                result["runtime_unload"] = {"success": False, "backend_available": False}
            return result
        if mode is None:
            result = c.get("/api/mode", timeout=3.0)
        else:
            result = c.post("/api/admin/mode", {"mode": mode}, timeout=3.0)
    except Exception as exc:
        return {"success": False, "server_status": "offline", "error": str(exc)}

    if not isinstance(result, dict):
        return {"success": False, "error": "invalid response from mode API"}
    if result.get("server_status") == "offline":
        return {**result, "success": False, "error": result.get("error") or "Local AI Hub is offline"}
    if result.get("success") is not True:
        return {**result, "success": False, "error": result.get("error") or "mode request failed"}

    confirmed_mode = result.get("mode")
    if confirmed_mode not in ACTIVITY_MODES:
        return {"success": False, "error": f"invalid mode returned by server: {confirmed_mode!r}"}
    if mode is not None and confirmed_mode != mode:
        return {"success": False, "error": f"server returned mode {confirmed_mode!r} after requesting {mode!r}"}
    return {**result, "success": True, "mode": confirmed_mode}


def _activity_mode_error(result: dict[str, Any]) -> str:
    status_code = result.get("status_code")
    if result.get("server_status") == "offline":
        return "Local AI Hub is offline or unreachable"
    if status_code == 400:
        return f"server rejected mode (HTTP 400): {result.get('error', 'invalid mode')}"
    suffix = f" (HTTP {status_code})" if status_code else ""
    return f"mode request failed{suffix}: {result.get('error', 'unknown error')}"


def _activity_mode_transition_failures(result: dict[str, Any], requested_mode: str | None) -> list[str]:
    if not isinstance(result, dict):
        return ["invalid result"]
    failures: list[str] = []
    if requested_mode == "preprocessing":
        started = result.get("preprocessing_start")
        if not isinstance(started, dict) or started.get("success") is not True:
            failures.append("preprocessing start")
    if requested_mode == "gaming":
        unload = result.get("runtime_unload")
        unload_ok = False
        if isinstance(unload, dict):
            if unload.get("success") is True:
                unload_ok = True
            elif unload.get("backend_available") is True:
                rem_ollama = (unload.get("remaining_by_backend") or {}).get("ollama")
                failed = unload.get("failed") or {}
                if rem_ollama == [] and not failed.get("ollama"):
                    non_ollama_failures = [v for k, v in failed.items() if k not in {"ollama", "verification"}]
                    if non_ollama_failures and all("unavailable" in str(v).lower() for v in non_ollama_failures):
                        unload_ok = True
        if not unload_ok:
            failures.append("VRAM unload")
        accelerator_release = result.get("accelerator_release")
        if not isinstance(accelerator_release, dict) or accelerator_release.get("success") is not True:
            failures.append("accelerator release")
    if requested_mode in {"gaming", "maintenance", "preprocessing"}:
        job_cancellation = result.get("job_cancellation")
        if "job_cancellation" in result and (
            not isinstance(job_cancellation, dict) or job_cancellation.get("success") is not True
        ):
            failures.append("job cancellation")
    return failures


def _service(action: str) -> bool:
    service = ROOT / "tools" / "service.py"
    if not service.exists():
        return False
    try:
        timeout = _startup_wait_seconds() + 10.0 if action in {"start", "restart"} else 35.0
        completed = subprocess.run([sys.executable, str(service), action], check=False, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_run_kwargs())
        return completed.returncode == 0
    except Exception:
        return False


def _startup_wait_seconds() -> float:
    """Match supervisor startup grace and leave time for a cold Hub to become ready."""
    try:
        grace = float(load_config(_config_arg()).get("headless", {}).get("startup_grace_seconds", 120.0))
    except Exception:
        grace = 120.0
    return min(330.0, max(12.0, grace + 30.0))


def _confirmed_service_stop(completed: subprocess.CompletedProcess[str]) -> bool:
    # A native service stop proves owner identity, role exit and listener
    # release. Never substitute an untrusted PID from /api/status or equate
    # HTTP unreachability with a stopped supervisor.
    if completed.returncode == 0:
        return completed.stdout.strip() == "stopped"
    if completed.returncode != 1:
        return False
    try:
        receipt = json.loads(completed.stdout)
    except (TypeError, ValueError):
        return False
    if not isinstance(receipt, dict):
        return False
    manager = receipt.get("service_manager")
    if not isinstance(manager, dict) or manager.get("supported") is not False:
        return False
    reason = manager.get("reason")
    # Linux/macOS installations without a registered user service may use
    # the detached supervisor. Accept only the explicit missing-manager
    # reason with every owned process and port positively confirmed stopped.
    return (
        reason in ("managed_user_unit_not_installed", "managed_launch_agent_not_installed")
        and receipt.get("errors") == [reason]
        and all(receipt.get(key) is True for key in (
            "stopped", "supervisor_stopped", "hub_stopped", "managed_ollama_stopped",
        ))
        and "port_listener_pid" in receipt
        and receipt["port_listener_pid"] is None
    )


def stop() -> bool:
    service = ROOT / "tools" / "service.py"
    if not service.is_file():
        print("Service controller unavailable; shutdown not confirmed.", file=sys.stderr)
        return False
    try:
        completed = subprocess.run(
            [sys.executable, str(service), "stop"], check=False, timeout=35.0,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Service controller failed; shutdown outcome unknown.", file=sys.stderr)
        return False
    if not _confirmed_service_stop(completed):
        print("Service controller did not confirm owned shutdown: " +
              (completed.stdout.strip() or completed.stderr.strip())[-2000:], file=sys.stderr)
        return False
    c = HubClient(config_path=_config_arg(), auto_start=False)
    try:
        return not c._online(timeout=2.0)
    finally:
        c.close()


def start(verbose: bool = True) -> bool:
    if _service("start"):
        deadline = time.time() + _startup_wait_seconds()
        c = client()
        start_t = time.time()
        is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        last_feedback = 0.0
        while time.time() < deadline:
            if c._online():
                if is_tty and verbose:
                    sys.stdout.write(f"\rLocal AI Hub started in {time.time() - start_t:.1f}s.        \n")
                    sys.stdout.flush()
                return True
            if is_tty and verbose and (time.time() - last_feedback >= 1.0):
                last_feedback = time.time()
                elapsed = int(last_feedback - start_t)
                sys.stdout.write(f"\rWaiting for Local AI Hub cold start... ({elapsed}s)")
                sys.stdout.flush()
            time.sleep(0.2)
        if is_tty and verbose:
            sys.stdout.write("\n")
            sys.stdout.flush()
        # A successfully launched managed supervisor owns startup. Do not make the
        # control client race it with a direct spawn after an ordinary cold start.
        return c._online()
    return client().ensure_server()


def status_inventory_lines(st: dict) -> tuple[str, str]:
    """Do not present omitted process-scope inventories as empty global state."""
    models = st.get("installed_models")
    if st.get("snapshot_stale") is True:
        model_line = "Models:       Stale inventory (unverified)"
    elif (st.get("installed_models_available") is not False and isinstance(models, list)
          and all(isinstance(name, str) and name.strip() for name in models)):
        sample = f" ({', '.join(models[:3])}{'...' if len(models) > 3 else ''})" if models else ""
        model_line = f"Models:       {len(models)} installed{sample}"
    else:
        model_line = "Models:       Inventory unreported"
    state = st.get("agent_state")
    state = state if isinstance(state, dict) else {}
    labels = []
    for key in ("tasks", "leases"):
        items = state.get(key)
        if isinstance(items, list) and all(isinstance(item, dict) for item in items):
            labels.append(f"{len(items)} reported {key}")
        else:
            labels.append(f"{key} unreported")
    return model_line, "Agent OS:     " + ", ".join(labels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the Local AI Hub singleton")
    parser.add_argument("action", choices=["status", "start", "stop", "restart", "watch", "desktop", "dashboard", "service-status", "agent-state", "cleanup", "clean", "generate", "tasks", "plans", "memory", "doctor", "logs", "pause", "resume", "mode", "caveman-compress", "compress-instructions", "client", "knowledge"])
    parser.add_argument("sub_arg", nargs="?", default=None, metavar="ARG", help="Mode name (for mode action) or client subcommand (status, detect, inject, remove, config)")
    parser.add_argument("--client", dest="client_name", type=str, default="", help="Client ID for client commands (antigravity, codex, claude, opencode, cursor, windsurf, devin, vscode, gemini_cli)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml")
    parser.add_argument("--install", action="store_true", help="Also deploy generated skill/instructions to configured agents")
    parser.add_argument("--all-agents", action="store_true", help="Discover and compress instructions across all configured agent directories (.gemini, .codex, .claude, etc.)")
    parser.add_argument("--apply", action="store_true", help="Apply reviewed compressed candidates in-place (default: preview/stage only)")
    parser.add_argument("--model", type=str, default="", help="Model name for caveman compression (defaults to configured model)")
    parser.add_argument("--staging-dir", type=Path, default=None, help="Directory for backups and candidates")
    parser.add_argument("--manifest", type=Path, default=None, help="Exact staged instruction manifest for review-staged, apply-staged or restore-staged")
    parser.add_argument("--manifest-sha256", default="", help="Digest of the reviewed staged instruction manifest")
    parser.add_argument("--task-id", type=str, default="", help="Task ID for task lookup")
    parser.add_argument("--status", type=str, default="", help="Task status filter (planned, active, verifying, completed, failed, blocked)")
    parser.add_argument("--complete", action="store_true", help="Mark task as completed")
    parser.add_argument("--fail", action="store_true", help="Mark task as failed")
    parser.add_argument("--reason", type=str, default="", help="Reason for completing or failing task")
    parser.add_argument("--root", type=Path, default=None, help="Repository root path (defaults to current working directory)")
    parser.add_argument("--scope", type=str, default="", help="Memory scope filter (task, session, branch, project, user, global)")
    parser.add_argument("--key", type=str, default="", help="Memory key filter")
    parser.add_argument("--query", type=str, default="", help="Memory or knowledge search query")
    parser.add_argument("--record-file", type=Path, default=None, help="Knowledge record JSON input")
    parser.add_argument("--expected-revision", default=None, help="Exact knowledge record revision; empty string for create")
    parser.add_argument("--operation-id", default="", help="Optional retry-safe knowledge operation ID")
    parser.add_argument("--project-id", default="", help="Explicit project UUID for a replayable knowledge initialization")
    parser.add_argument("--knowledge-mode", choices=["shared", "review_only", "read_only"], default="shared")
    parser.add_argument("--preview-digest", default="", help="Exact reviewed handoff export digest")
    parser.add_argument("--include-historical-verification", action="store_true", help="Include redacted historical receipt summaries in handoff export")
    parser.add_argument("--after-task-id", default="", help="Offline migration continuation cursor")
    parser.add_argument("--snapshot", default="", help="Expected offline task inventory snapshot")
    parser.add_argument("--handoff-id", default="", help="Portable Agent OS handoff ID")
    parser.add_argument("--base", default="", help="Base Git commit/ref for committed knowledge diff")
    parser.add_argument("--head", default="HEAD", help="Head Git commit/ref for committed knowledge diff")
    parser.add_argument("--changed-path", action="append", default=[], help="Repository-relative path for knowledge impact (repeatable)")
    parser.add_argument("--finding-id", default="", help="Knowledge quality finding ID")
    parser.add_argument("--subject-digest", default="", help="Conflict subject digest from the current catalog")
    parser.add_argument("--decision", choices=["acceptable", "expected", "confirmed_issue", "false_positive", "deferred"])
    parser.add_argument("--limit", type=int, default=50, help="Maximum items to return")
    parser.add_argument("--compact", action="store_true", help="Compact older memory records into digest summaries")
    parser.add_argument("--vacuum", action="store_true", help="Run SQLite WAL checkpoint and VACUUM during cleanup")
    parser.add_argument("--ports", action="store_true", help="Report listeners on ports 11436, 11437, 11439; do not signal them")
    parser.add_argument("-f", "--follow", action="store_true", help="Stream log output continuously (like tail -f)")
    parser.add_argument("--json", dest="raw_json", action="store_true", help="Output raw JSON")
    parser.add_argument("--no-auto-start", action="store_true", help="Do not start Hub implicitly for knowledge operations")
    args = parser.parse_args()
    if args.action == "mode":
        if args.sub_arg is not None and args.sub_arg not in ACTIVITY_MODES:
            parser.error(f"MODE must be one of: {', '.join(ACTIVITY_MODES)}")
        requested_mode = args.sub_arg
    elif args.action in {"pause", "resume"}:
        if args.sub_arg is not None:
            parser.error(f"Action '{args.action}' takes no arguments")
        requested_mode = None
    elif args.action == "knowledge":
        if args.sub_arg not in {"catalog", "query", "validate", "audit", "sync-status", "impact", "remediate", "init", "save", "review", "handoff-export", "handoff-resume", "handoff-list", "handoff-preflight", "diff", "batch-preview", "batch-apply", "batch-recover", "legacy-task-batch", "legacy-memory-batch", "legacy-incident-batch", "projection-rebuild"}:
            parser.error("knowledge requires catalog, query, validate, audit, sync-status, impact, remediate, init, save, review, handoff-export, handoff-resume, handoff-list, handoff-preflight, diff, batch-preview, batch-apply, batch-recover, legacy-task-batch, legacy-memory-batch, legacy-incident-batch or projection-rebuild")
        if args.root is None:
            parser.error("knowledge requires an explicit --root")
        if args.sub_arg in {"init", "save", "review"} and (not args.apply or args.dry_run):
            parser.error("knowledge mutations require explicit --apply (review content first)")
        if args.sub_arg in {"batch-preview", "batch-apply", "batch-recover"}:
            if args.record_file is None:
                parser.error("knowledge batch requires --record-file")
            if args.sub_arg == "batch-preview" and args.apply:
                parser.error("batch-preview is read-only")
            if args.sub_arg != "batch-preview" and (
                not args.apply or args.dry_run or not args.preview_digest or not args.operation_id
            ):
                parser.error("batch-apply/recover requires --apply, --preview-digest and --operation-id")
        if args.sub_arg == "init" and args.operation_id and not args.project_id:
            parser.error("knowledge init with --operation-id requires --project-id for deterministic retry")
        if args.sub_arg == "impact" and not args.changed_path:
            parser.error("knowledge impact requires --changed-path")
        if args.sub_arg == "remediate" and not all((args.finding_id, args.subject_digest)):
            parser.error("knowledge remediate requires --finding-id and --subject-digest")
        if args.sub_arg == "remediate" and args.apply and (args.dry_run or not args.task_id):
            parser.error("knowledge remediate --apply requires explicit new --task-id and no --dry-run")
        if args.sub_arg == "handoff-export" and not args.task_id:
            parser.error("handoff-export requires --task-id")
        if args.sub_arg == "handoff-export" and args.apply and (args.dry_run or args.expected_revision is None or not args.preview_digest):
            parser.error("handoff-export --apply requires --expected-revision, --preview-digest and no --dry-run")
        if args.sub_arg == "handoff-resume" and not args.handoff_id:
            parser.error("handoff-resume requires --handoff-id")
        if args.sub_arg == "handoff-resume" and args.apply and (args.dry_run or not args.expected_revision or not args.preview_digest or not args.task_id):
            parser.error("handoff-resume --apply requires reviewed --expected-revision, --preview-digest and explicit new --task-id")
        if args.sub_arg in {"save", "review"} and args.expected_revision is None:
            parser.error("knowledge save/review requires --expected-revision (empty string for create)")
        if args.sub_arg == "save" and args.record_file is None:
            parser.error("knowledge save requires --record-file")
        if args.sub_arg == "review" and not all((args.finding_id, args.subject_digest, args.decision, args.reason)):
            parser.error("knowledge review requires --finding-id, --subject-digest, --decision and --reason")
        requested_mode = None
    elif args.action == "client":
        if args.sub_arg is not None and args.sub_arg not in {"status", "detect", "inject", "remove", "config"}:
            parser.error("CLIENT_SUBCOMMAND must be one of: status, detect, inject, remove, config")
        if args.apply and (args.sub_arg != "config" or args.client_name != "vscode"):
            parser.error("--apply for client config currently requires 'config --client vscode'")
        if args.apply and args.root is None:
            parser.error("client config --apply requires an explicit --root workspace path")
        requested_mode = None
    elif args.action == "agent-state" and args.sub_arg == "storage-inventory":
        if args.apply:
            parser.error("agent-state storage-inventory is read-only")
        requested_mode = None
    elif args.sub_arg is not None:
        parser.error(f"Unrecognized argument '{args.sub_arg}' for action '{args.action}'")
    else:
        requested_mode = None

    if args.action == "knowledge":
        from local_ai_hub.repo_knowledge import (
            RepoKnowledgeStore,
            build_finding_review,
            detect_declared_claim_conflicts,
            query_declared_knowledge,
        )
        from local_ai_hub.repo_plan.schema_validation import RepoPlanError, parse_plan_json
        from uuid import uuid4

        try:
            store = RepoKnowledgeStore(args.root)
            if args.sub_arg in {"batch-preview", "batch-apply", "batch-recover"}:
                from local_ai_hub.repo_knowledge_batch import apply_knowledge_batch, preview_knowledge_batch

                with args.record_file.open("rb") as stream:
                    raw = stream.read(200001)
                if len(raw) > 200000:
                    raise ValueError("Knowledge batch input exceeds 200000 bytes")
                batch = parse_plan_json(raw)
                if set(batch) != {"records"}:
                    raise ValueError("Knowledge batch input requires records")
                if args.sub_arg == "batch-preview":
                    result = preview_knowledge_batch(store, batch["records"])
                else:
                    result = apply_knowledge_batch(
                        store, batch["records"], preview_digest=args.preview_digest,
                        operation_id=args.operation_id,
                        authorize_write=lambda: args.apply is True and not args.dry_run,
                        recover=args.sub_arg == "batch-recover",
                    )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["success"] else 1
            if args.sub_arg == "diff":
                from local_ai_hub.repo_knowledge_sync import compare_knowledge_revisions

                if args.apply or not args.base:
                    parser.error("knowledge diff is read-only and requires --base")
                result = compare_knowledge_revisions(store.root, args.base, args.head)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["complete"] else 1
            if args.sub_arg == "sync-status":
                from local_ai_hub.repo_knowledge_sync import checkout_sync_status

                result = checkout_sync_status(store.root)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["complete"] and result["state"] == "clean_shared_paths" else 1
            if args.sub_arg == "legacy-task-batch":
                from local_ai_hub.agent_state_migration import preview_legacy_task_batch
                from local_ai_hub.repository_scope import authorized_repository_root

                if args.apply or not 1 <= args.limit <= 16:
                    parser.error("legacy-task-batch is read-only; use --limit 1 through 16")
                config = load_config(_config_arg(args.config))
                authorized_repository_root(config, str(store.root))
                result = preview_legacy_task_batch(
                    config["server"]["state_dir"], store, limit=args.limit,
                    after_task_id=args.after_task_id, expected_snapshot=args.snapshot,
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["inventory_complete"] and all(
                    row["state"] in {"review_required", "already_published"} for row in result["states"]
                ) else 1
            if args.sub_arg == "legacy-memory-batch":
                from local_ai_hub.agent_state_migration import preview_legacy_memory_batch
                from local_ai_hub.repository_scope import authorized_repository_root

                if args.apply or not 1 <= args.limit <= 16:
                    parser.error("legacy-memory-batch is read-only; use --limit 1 through 16")
                config = load_config(_config_arg(args.config))
                authorized_repository_root(config, str(store.root))
                result = preview_legacy_memory_batch(
                    config["server"]["state_dir"], store, limit=args.limit,
                    after_record_id=args.after_task_id, expected_snapshot=args.snapshot,
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["inventory_complete"] and all(
                    row["state"] in {"review_required", "already_published"} for row in result["states"]
                ) else 1
            if args.sub_arg == "legacy-incident-batch":
                from local_ai_hub.agent_state_migration import preview_legacy_incident_batch
                from local_ai_hub.repository_scope import authorized_repository_root

                if args.apply or not 1 <= args.limit <= 16:
                    parser.error("legacy-incident-batch is read-only; use --limit 1 through 16")
                config = load_config(_config_arg(args.config))
                authorized_repository_root(config, str(store.root))
                result = preview_legacy_incident_batch(
                    config["server"]["state_dir"], store, limit=args.limit,
                    after_incident_id=args.after_task_id, expected_snapshot=args.snapshot,
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["inventory_complete"] and all(
                    row["state"] in {"review_required", "already_published"} for row in result["states"]
                ) else 1
            if args.sub_arg == "projection-rebuild":
                from local_ai_hub.repo_agent_state import rebuild_agent_state_projection
                from local_ai_hub.repository_scope import authorized_repository_root

                config = load_config(_config_arg(args.config))
                authorized_repository_root(config, str(store.root))
                result = rebuild_agent_state_projection(store.root, config["server"]["state_dir"])
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result.get("success") else 1
            if args.sub_arg == "handoff-preflight":
                from local_ai_hub.repo_task_handoff import preflight_task_handoffs

                if args.apply or not 1 <= args.limit <= 64:
                    parser.error("handoff-preflight is read-only; limit must be 1 through 64")
                response = HubClient(config_path=_config_arg(args.config), auto_start=not args.no_auto_start).post(
                    "/api/agent-state/tasks", {
                        "action": "list", "root": str(store.root),
                        "limit": args.limit + 1, "include_stale": True,
                    },
                )
                tasks = response.get("tasks")
                if response.get("success") is not True or not isinstance(tasks, list):
                    print(json.dumps({"success": False, "error": "Scoped legacy task inventory unavailable"}))
                    return 1
                result = preflight_task_handoffs(
                    store, tasks[:args.limit],
                    inventory_complete=len(tasks) < args.limit + 1 and not response.get("query_truncated"),
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["complete"] and all(
                    row["state"] in {"review_required", "already_published"} for row in result["records"]
                ) else 1
            if args.sub_arg == "handoff-list":
                from local_ai_hub.repo_task_handoff import list_task_handoffs

                result = list_task_handoffs(store, limit=args.limit)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result["complete"] else 1
            if args.sub_arg in {"handoff-export", "handoff-resume"}:
                from local_ai_hub.repo_task_handoff import build_task_handoff, preview_handoff_resume

                target_root = str(store.root)
                if args.sub_arg == "handoff-export":
                    from local_ai_hub.repo_knowledge import _digest_value
                    from local_ai_hub.repo_task_handoff import attach_historical_verification, attach_source_dependencies

                    handoff_client = HubClient(config_path=_config_arg(args.config), auto_start=not args.no_auto_start)
                    response = handoff_client.get_task(args.task_id, root=target_root)
                    if response.get("success") is not True or not isinstance(response.get("task"), dict):
                        print(json.dumps({"success": False, "error": "Scoped task unavailable"}))
                        return 1
                    task = response["task"]
                    record = attach_source_dependencies(store, build_task_handoff(store, task))
                    if args.include_historical_verification:
                        exported = handoff_client.post("/api/agent-state/verification", {
                            "action": "export", "root": target_root,
                            "task_id": args.task_id, "format": "json",
                        })
                        if exported.get("success") is not True or not isinstance(exported.get("receipts"), list):
                            print(json.dumps({"success": False, "error": "Scoped historical verification unavailable"}))
                            return 1
                        record = attach_historical_verification(record, task, exported["receipts"])
                    manifest_revision = store.manifest()[1]
                    try:
                        current_revision = store.get("handoff", record["id"], verify_sources=False)["revision"]
                    except FileNotFoundError:
                        current_revision = ""
                    preview_digest = _digest_value([manifest_revision, current_revision, record])
                    if args.apply:
                        if args.preview_digest != preview_digest or args.expected_revision != current_revision:
                            print(json.dumps({"success": False, "error": "Handoff changed; preview again"}))
                            return 1
                        result = store.save(
                            record, expected_revision=args.expected_revision, owner="local-operator",
                            idempotency_key=args.operation_id or str(uuid4()),
                            authorize_write=lambda: (
                                args.apply is True and not args.dry_run
                                and store.manifest()[1] == manifest_revision
                            ),
                        )
                        print(json.dumps({**result, "handoff_id": record["id"]}, indent=2))
                        return 0 if result.get("success") is True else 1
                    print(json.dumps({"preview": True, "record": record, "expected_revision": current_revision,
                                      "preview_digest": preview_digest}, indent=2, ensure_ascii=False))
                    return 0
                preview = preview_handoff_resume(store, args.handoff_id)
                if not args.apply:
                    print(json.dumps(preview, indent=2, ensure_ascii=False))
                    return 0 if preview["resume_allowed"] else 1
                if not preview["resume_allowed"]:
                    print(json.dumps({"success": False, "error": "Handoff dependencies missing or changed",
                                      "dependencies": preview["dependencies"]}, indent=2))
                    return 1
                if preview["revision"] != args.expected_revision or preview["preview_digest"] != args.preview_digest:
                    print(json.dumps({"success": False, "error": "Handoff or dependencies changed; review again"}))
                    return 1
                result = HubClient(config_path=_config_arg(args.config), auto_start=not args.no_auto_start).post(
                    "/api/agent-state/tasks", {
                        "action": "create", "root": target_root, "task_id": args.task_id,
                        "contract": preview["contract"],
                        "handoff_resume": {
                            "handoff_id": args.handoff_id, "revision": preview["revision"],
                            "preview_digest": preview["preview_digest"],
                        },
                    },
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result.get("success") is True else 1
            if args.sub_arg in {"init", "save", "review"}:
                operation_id = args.operation_id or str(uuid4())
                # This is an explicit local operator command, not a remotely
                # supplied actor or a permission granted by Git metadata.
                def authorize_local_operator() -> bool:
                    return args.apply is True and not args.dry_run

                if args.sub_arg == "init":
                    project_id = args.project_id or str(uuid4())
                    result = store.bootstrap(project_id, mode=args.knowledge_mode,
                                             owner="local-operator", idempotency_key=operation_id,
                                             authorize_write=authorize_local_operator)
                    result["project_id"] = project_id
                else:
                    if args.sub_arg == "save":
                        with args.record_file.open("rb") as stream:
                            record = parse_plan_json(stream.read(10001))
                    else:
                        record = build_finding_review(store.catalog(), args.finding_id,
                                                      args.subject_digest, args.decision, args.reason)
                    result = store.save(record, expected_revision=args.expected_revision,
                                        owner="local-operator", idempotency_key=operation_id,
                                        authorize_write=authorize_local_operator)
                print(json.dumps({**result, "operation_id": operation_id}, indent=2, ensure_ascii=False))
                return 0 if result.get("success") is True else 1
            catalog = store.catalog()
            if args.sub_arg == "audit":
                from local_ai_hub.repo_knowledge_quality import quality_report

                result = quality_report(catalog)
            elif args.sub_arg == "impact":
                from local_ai_hub.repo_knowledge_quality import knowledge_impact

                result = knowledge_impact(catalog, args.changed_path)
            elif args.sub_arg == "remediate":
                from local_ai_hub.repo_knowledge_quality import build_remediation_contract

                contract = build_remediation_contract(catalog, args.finding_id, args.subject_digest)
                if not args.apply:
                    print(json.dumps({"preview": True, "contract": contract}, indent=2, ensure_ascii=False))
                    return 0
                result = HubClient(config_path=_config_arg(args.config), auto_start=not args.no_auto_start).create_task(
                    contract, task_id=args.task_id, root=str(store.root),
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if result.get("success") is True else 1
            elif args.sub_arg == "query":
                result = query_declared_knowledge(catalog, args.query, limit=min(args.limit, 32))
            elif args.sub_arg == "validate":
                from local_ai_hub.repo_knowledge_graph import process_flow_findings
                from local_ai_hub.repo_knowledge_quality import quality_report

                quality = quality_report(catalog)
                result = {
                    "project_id": catalog["project_id"], "complete": catalog["complete"],
                    "issues": catalog["issues"], "record_count": len(catalog["records"]),
                    "stale_count": sum(item["freshness"] == "stale" for item in catalog["records"]),
                    "unknown_count": sum(item["freshness"] == "unknown" for item in catalog["records"]),
                    "conflict_candidates": detect_declared_claim_conflicts(catalog),
                    "graph_issues": catalog.get("graph_issues", []),
                    "process_candidates": process_flow_findings(catalog),
                    "quality_complete": quality["complete"],
                    "quality_candidates": quality["findings"],
                }
            else:
                result = catalog
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.sub_arg == "validate":
                return 0 if result["complete"] and result["quality_complete"] and not result["quality_candidates"] else 1
            return 0 if result["complete"] else 1
        except (OSError, RepoPlanError, ValueError) as exc:
            print(json.dumps({"success": False, "error": type(exc).__name__}))
            return 1
    if args.action in {"pause", "resume", "mode"}:
        if args.action == "pause":
            requested_mode = "gaming"
        elif args.action == "resume":
            requested_mode = "active"
        result = _activity_mode_request(requested_mode, config_path=_config_arg(args.config))
        if result.get("success") is not True:
            if args.raw_json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(_activity_mode_error(result), file=sys.stderr)
            return 1
        mode = str(result["mode"])
        transition_failures = _activity_mode_transition_failures(result, requested_mode)
        if args.raw_json:
            print(
                json.dumps(
                    {
                        **result,
                        "complete": not transition_failures,
                        "transition_failures": transition_failures,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 1 if transition_failures else 0
        if transition_failures:
            print(f"Mode persisted as {mode}.")
            print(f"Mode transition incomplete: {', '.join(transition_failures)}.", file=sys.stderr)
            return 1
        print(f"Activity mode: {mode}" if requested_mode is None else f"Mode set to {mode}")
        return 0
    if args.action == "client":
        from local_ai_hub.client_adapters.registry import (
            ClientRegistry,
        )

        from local_ai_hub.client_adapters.instruction_engine import (
            InstructionEngine,
        )
        target_root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
        subcmd = args.sub_arg or "status"

        if subcmd == "detect":
            detected_id = ClientRegistry.detect(repo_root=target_root)
            adapter = ClientRegistry.get(detected_id)
            result = {
                "success": True,
                "detected_client": detected_id,
                "display_name": adapter.capabilities.display_name,
                "repo_root": str(target_root),
            }
            if args.raw_json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"Detected client: {detected_id} ({adapter.capabilities.display_name})")
            return 0

        if subcmd == "status":
            if args.client_name:
                adapter = ClientRegistry.get(args.client_name)
                rep = adapter.capability_report(repo_root=str(target_root))
                rep["success"] = True
                if args.raw_json:
                    print(json.dumps(rep, indent=2, ensure_ascii=False))
                else:
                    print(f"Client: {rep['display_name']} ({rep['client_id']})")
                    print(f"Hook Support:        {rep['hook_support']}")
                    print(f"Instruction Targets: {', '.join(rep['instruction_targets'])}")
                    print(f"Prompt Cache Shield: {rep.get('prompt_cache_shield', False)}")
                    print(f"Token Tracking:      {rep['has_token_tracking']}")
                    print(f"Reasoning Slicing:   {rep['has_reasoning_tokens']}")
                    print(f"Tool Filter:         {', '.join(rep['tool_filter']) if rep['tool_filter'] else 'None'}")
                    print(f"Support Level:       {rep.get('support_level', 'unknown')}")
                return 0

            adapters = ClientRegistry.list_adapters()
            detected_id = ClientRegistry.detect(repo_root=target_root)
            reports = {}
            for cid in sorted(adapters):
                ad = ClientRegistry.get(cid)
                reports[cid] = ad.capability_report(repo_root=str(target_root))
            result = {
                "success": True,
                "detected_client": detected_id,
                "clients": reports,
            }
            if args.raw_json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"Active/Detected Client: {detected_id}\n")
                print(f"{'Client ID':<15} {'Display Name':<25} {'Hooks':<12} {'Cache Shield':<14} {'Targets'}")
                print("-" * 80)
                for cid, rep in reports.items():
                    targets = ", ".join(rep['instruction_targets'][:2])
                    if len(rep['instruction_targets']) > 2:
                        targets += "..."
                    print(f"{cid:<15} {rep['display_name']:<25} {rep['hook_support']:<12} {str(rep.get('prompt_cache_shield', False)):<14} {targets}")
            return 0

        if subcmd in {"inject", "remove"}:
            client_id = args.client_name or ClientRegistry.detect(repo_root=target_root)
            engine = InstructionEngine(client_id=client_id, repo_root=target_root)
            res = engine.remove(dry_run=args.dry_run) if subcmd == "remove" else engine.inject(dry_run=args.dry_run)
            result = {
                "success": all(v.get("success", False) for v in res.values()) if res else True,
                "client_id": client_id,
                "action": subcmd,
                "dry_run": args.dry_run,
                "files": res,
            }
            if args.raw_json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                action_name = "Removed" if subcmd == "remove" else "Injected"
                mode_str = " (dry run)" if args.dry_run else ""
                print(f"{action_name} instructions for {client_id}{mode_str}:")
                if not res:
                    print("  No target files applicable for this client.")
                for fpath, fstat in res.items():
                    status_text = "updated" if fstat.get("changed") else "unchanged"
                    if not fstat.get("success"):
                        status_text = f"failed: {fstat.get('error')}"
                    print(f"  {fpath} -> {status_text}")
            return 0 if result["success"] else 1

        if subcmd == "config":
            client_id = args.client_name or ClientRegistry.detect(repo_root=target_root)
            adapter = ClientRegistry.get(client_id)
            configs: dict[str, Any] = {}
            if client_id == "vscode" or hasattr(adapter, "get_mcp_config"):
                configs[".vscode/mcp.json"] = adapter.get_mcp_config(hub_install_dir=str(ROOT))
            elif client_id == "opencode" or hasattr(adapter, "get_js_plugin_server_config"):
                configs["opencode_plugin_storage"] = adapter.get_js_plugin_server_config(
                    hub_install_dir=str(ROOT),
                    python_exe=sys.executable,
                )
            if args.apply:
                from tools import setup as setup_mod
                from tools.install_ownership import MANIFEST_NAME, read_install_manifest

                config_path = target_root / ".vscode" / "mcp.json"
                install_root = ROOT.resolve()
                ownership_path = install_root / MANIFEST_NAME
                rollback_tracking = "backup_only"
                previous_install_root = setup_mod._ACTIVE_INSTALL_ROOT
                try:
                    if ownership_path.exists() or ownership_path.is_symlink():
                        # Validate the owner marker before making it responsible
                        # for rollback of an external workspace config.
                        read_install_manifest(install_root)
                        setup_mod._ACTIVE_INSTALL_ROOT = install_root
                        rollback_tracking = "install_manifest"
                    with contextlib.redirect_stdout(sys.stderr if args.raw_json else sys.stdout):
                        setup_mod.vscode_mcp_merge(
                            config_path,
                            configs[".vscode/mcp.json"]["servers"],
                            backup_enabled=True,
                        )
                    written = json.loads(config_path.read_text(encoding="utf-8"))
                    if written.get("servers", {}).get("local-ai") != configs[".vscode/mcp.json"]["servers"]["local-ai"]:
                        raise RuntimeError("VS Code MCP route was not applied because the existing entry is not Hub-owned")
                except (OSError, ValueError, RuntimeError) as exc:
                    failure = {
                        "success": False,
                        "client_id": client_id,
                        "applied": False,
                        "error": str(exc),
                    }
                    if args.raw_json:
                        print(json.dumps(failure, indent=2, ensure_ascii=False))
                    else:
                        print(f"Could not apply VS Code MCP configuration: {exc}", file=sys.stderr)
                    return 1
                finally:
                    setup_mod._ACTIVE_INSTALL_ROOT = previous_install_root
            result = {
                "success": True,
                "client_id": client_id,
                "configs": configs,
                **({"applied": True, "workspace_config": str(config_path), "rollback_tracking": rollback_tracking} if args.apply else {}),
            }
            if args.raw_json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"Generated configuration for {client_id}:")
                for cname, cdata in configs.items():
                    print(f"\n--- {cname} ---")
                    print(json.dumps(cdata, indent=2, ensure_ascii=False))
            return 0
    if args.action == "generate":
        cfg = load_config(_config_arg(args.config))
        from local_ai_hub.generator import write_all_generated
        from tools import setup as setup_mod
        python_bin = setup_mod.venv_python(ROOT / ".venv")
        if not python_bin.exists():
            python_bin = Path(sys.executable)
        res = write_all_generated(cfg, ROOT, python_bin)
        install_dir = setup_mod.expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
        if install_dir.resolve() != ROOT.resolve():
            write_all_generated(cfg, install_dir, python_bin)
        if args.install or bool(cfg.get("setup", {}).get("install_agent_configs", False)):
            setup_mod.configure_agents(install_dir, python_bin, None, cfg)
        print(json.dumps({"success": True, "generated": res}, indent=2, ensure_ascii=False))
        return 0
    if args.action in {"caveman-compress", "compress-instructions"}:
        cfg = load_config(_config_arg(args.config))
        from local_ai_hub import caveman_instructions
        from tools import setup as setup_mod

        state_dir = Path(cfg.get("server", {}).get("state_dir", ROOT / "state"))
        staging_dir = args.staging_dir or (state_dir / "caveman-staging")
        if args.sub_arg in {"review-staged", "apply-staged", "restore-staged"}:
            if args.root is None or args.manifest is None or args.all_agents or args.apply:
                parser.error("staged instruction operations require --root and --manifest, without --all-agents or --apply")
            operation = {"review-staged": "inspect", "apply-staged": "apply", "restore-staged": "restore"}[args.sub_arg]
            try:
                result = caveman_instructions.reviewed_instruction_manifest(
                    args.manifest, repository_root=args.root, stage_root=staging_dir,
                    action=operation, expected_digest=args.manifest_sha256,
                )
            except (OSError, ValueError) as exc:
                print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.sub_arg is not None or args.manifest is not None or args.manifest_sha256:
            parser.error("unknown compression subcommand or misplaced manifest options")

        roots: list[Path] = []
        if args.all_agents:
            for u_home in setup_mod.get_user_homes():
                for d_name in (".gemini", ".codex", ".claude", ".agents", ".cursor", ".copilot"):
                    d_path = u_home / d_name
                    if d_path.is_dir():
                        roots.append(d_path)
        else:
            target_root = args.root or Path.cwd()
            roots.append(Path(target_root).resolve())

        try:
            files = caveman_instructions.discover_instruction_files(roots)
        except Exception as exc:
            print(f"Discovery error: {exc}", file=sys.stderr)
            return 1

        if not files:
            print(f"No eligible instruction files found under: {', '.join(str(r) for r in roots)}")
            return 0

        model = args.model or cfg.get("models", {}).get("reasoning") or cfg.get("models", {}).get("heavy_code") or "qwen3.5:9b-nvfp4"
        review_model = cfg.get("models", {}).get("reasoning") or model
        endpoint = cfg.get("ollama", {}).get("endpoint") or "http://127.0.0.1:11434"

        staging_dir.mkdir(parents=True, exist_ok=True)

        print(f"Found {len(files)} instruction file(s) across {len(roots)} root(s).")
        print(f"Compressor model: {model} | Review model: {review_model}")
        print(f"Staging/backup: {staging_dir}")
        print(f"Mode: {'APPLY (in-place replacement)' if args.apply else 'PREVIEW / STAGE (pass --apply to overwrite)'}\n")

        prepared = []
        backup_failures = 0
        for f in files:
            try:
                prepared.append(caveman_instructions.backup_instruction(f, staging_dir))
            except Exception as exc:
                backup_failures += 1
                print(f"[SKIP] Backup failed for {f.name}: {exc}")

        applied = 0
        failed = backup_failures
        total_before = 0
        total_after = 0

        for item in prepared:
            try:
                res = caveman_instructions.compress_backed_up_instruction(
                    item,
                    lambda text: caveman_instructions.compress_with_caveman(
                        text, model=model, endpoint=endpoint
                    ),
                    lambda orig, cand: caveman_instructions.review_instruction_semantics(
                        orig, cand, model=review_model, endpoint=endpoint
                    ),
                )
                before = len(res.backup.read_bytes())
                after = len(res.candidate.read_bytes()) if res.candidate else before
                saved_pct = ((before - after) / before) * 100 if before > 0 else 0
                total_before += before
                total_after += after

                if args.apply:
                    caveman_instructions.apply_instruction(res)
                    status_lbl = "APPLIED"
                    applied += 1
                else:
                    status_lbl = "STAGED"

                print(f"[{status_lbl}] {item.source.name} ({item.source.parent.name}) — {before}B -> {after}B (-{saved_pct:.1f}%) in {res.duration_seconds:.1f}s")
                if res.candidate is not None:
                    print(f"Manifest: {res.candidate.parent / 'manifest.json'}")
            except Exception as exc:
                failed += 1
                print(f"[FAILED] {item.source.name}: {exc}")

        net_saved = ((total_before - total_after) / total_before) * 100 if total_before > 0 else 0
        print("\n" + "=" * 55)
        print(f"Summary: {len(files) - failed}/{len(files)} succeeded. Total bytes: {total_before}B -> {total_after}B (-{net_saved:.1f}%)")
        if not args.apply and (len(files) - failed) > 0:
            print("Review a manifest using compress-instructions review-staged --root ROOT --manifest PATH.")
            print("Then use apply-staged with the reviewed --manifest-sha256; this never regenerates the candidate.")
        return 0 if failed == 0 else 1
    if args.action == "watch":
        return subprocess.call([sys.executable, str(ROOT / "tools" / "monitor.py")])
    if args.action in {"desktop", "dashboard"}:
        # Compatibility alias opens the native application, never an HTTP UI.
        name = "local-ai-hub-desktop.exe" if os.name == "nt" else "local-ai-hub-desktop"
        import tomllib
        version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        candidates = (ROOT / "bin" / "desktop" / version / name, ROOT / "desktop" / "target" / "release" / name, ROOT / "bin" / name)
        binary = next((path for path in candidates if path.is_file()), None)
        if binary is None:
            print("Desktop binary missing. Build: cargo build --manifest-path desktop/Cargo.toml --release", file=sys.stderr)
            return 1
        env = os.environ.copy()
        env["LOCAL_AI_HUB_ROOT"] = str(ROOT)
        env["LOCAL_AI_DESKTOP_PYTHON"] = sys.executable
        config = _config_arg(args.config)
        if config:
            env["LOCAL_AI_CONFIG"] = str(Path(config).expanduser().resolve())
        try:
            subprocess.Popen([str(binary)], cwd=ROOT, env=env, **hidden_run_kwargs())
        except OSError as exc:
            print(f"Desktop launch failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.action == "service-status":
        path = Path(load_config(_config_arg(args.config))["server"]["state_dir"]) / "supervisor.status.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"running": False}, indent=2)); return 0
    if args.action == "agent-state":
        if args.sub_arg == "storage-inventory":
            from local_ai_hub.agent_state_inventory import inspect_agent_state_inventory

            config = load_config(_config_arg(args.config))
            report = inspect_agent_state_inventory(config["server"]["state_dir"])
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["success"] and report["complete"] else 1
        c = client()
        print(json.dumps(c.status(detail="agent_state"), indent=2, ensure_ascii=False))
        return 0
    if args.action == "cleanup":
        cleaned_ports: list[dict[str, Any]] = []
        skipped_ports: list[dict[str, Any]] = []
        if args.ports:
            from local_ai_hub.process_utils import find_listening_pid
            for port in [11436, 11437, 11439]:
                pid = find_listening_pid(port)
                if pid and pid > 0:
                    skipped_ports.append({
                        "port": port, "pid": pid, "status": "skipped",
                        "reason": "ownership_unverified",
                    })
        c: HubClient | None = None
        try:
            c = HubClient(config_path=_config_arg(args.config), auto_start=False)
            res = c.post("/api/agent-state/cleanup", {}, timeout=3.0)
        except Exception as e:
            res = {"success": False, "server_status": "offline", "detail": str(e)}
        finally:
            if c is not None:
                c.close()
        res["cleaned_ports"] = cleaned_ports
        res["skipped_ports"] = skipped_ports

        vacuum_results: list[dict[str, Any]] = []
        if args.vacuum:
            from local_ai_hub.sqlite_support import optimize_db
            cfg = load_config(_config_arg(args.config))
            state_dir = Path(cfg.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser().resolve()
            if state_dir.exists():
                for db_file in state_dir.rglob("*.sqlite3"):
                    try:
                        res_opt = optimize_db(db_file, wal_checkpoint=True, vacuum=True)
                        vacuum_results.append(res_opt)
                    except Exception as e:
                        vacuum_results.append({"path": str(db_file), "success": False, "error": str(e)})
        if vacuum_results:
            res["vacuum_results"] = vacuum_results

        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("success", True) else 1
    if args.action == "clean":
        from tools.clean import clean as run_clean
        dirs, files = run_clean(ROOT, all_clean=args.ports)
        if args.raw_json:
            print(json.dumps({"success": True, "dirs_removed": dirs, "files_removed": files}, indent=2))
        else:
            print(f"Cleaned {dirs} directories and {files} cache/build files.")
        return 0
    if args.action == "plans":
        c = client()
        target_root = str(args.root.resolve()) if args.root else "."
        if args.task_id:
            res = c.get_plan(args.task_id, root=target_root)
            if args.raw_json:
                print(json.dumps(res, indent=2))
            else:
                plan = res.get("plan", {})
                print(f"Plan: {plan.get('plan_id')} - {plan.get('title')} [{plan.get('status')}]")
                print(f"Goal: {plan.get('goal')}")
                print("Tasks:")
                for tid, t in plan.get("tasks", {}).items():
                    print(f"  [{t.get('work_status'):<12}] {tid:<20} {t.get('title')}")
            return 0
        res = c.list_plans(root=target_root)
        if args.raw_json:
            print(json.dumps(res, indent=2))
        else:
            plans = res.get("plans", [])
            if not plans:
                print("No plans found in repository.")
            for p in plans:
                print(f"{p.get('status', 'draft'):<12} {p.get('plan_id', ''):<24} {p.get('title', '')}")
        return 0
    if args.action == "tasks":
        c = client()
        target_root = str(args.root.resolve()) if args.root else None
        root_kw = {"root": target_root} if target_root else {}
        if args.complete or args.fail:
            if not args.task_id:
                print("Error: --task-id is required when completing or failing a task.", file=sys.stderr)
                return 1
            reason = args.reason or ("completed via hubctl" if args.complete else "failed via hubctl")
            res = c.complete_task(args.task_id, reason=reason, **root_kw) if args.complete else c.fail_task(args.task_id, reason=reason, **root_kw)
            if args.raw_json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
                return 0 if res.get("success", True) else 1
            if res.get("success", False):
                status_word = "completed" if args.complete else "failed"
                print(f"Task {args.task_id} {status_word}: {reason}")
                return 0
            else:
                print(f"Failed to update task {args.task_id}: {res.get('error', 'unknown error')}", file=sys.stderr)
                return 1
        if args.task_id:
            res = c.get_task(args.task_id, **root_kw)
        else:
            res = c.list_tasks(status=args.status or None, limit=args.limit, **root_kw)
        if args.raw_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("success", True) else 1
        if not res.get("success", True):
            print(f"Failed to query tasks: {res.get('error', 'unknown error')}", file=sys.stderr)
            return 1
        if args.task_id:
            t = res.get("task")
            if not t:
                print(f"Task {args.task_id} not found: {res.get('error', 'unknown error')}", file=sys.stderr)
                return 1
            print(f"Task ID:   {t.get('task_id')}")
            print(f"Status:    {t.get('status')}")
            print(f"Goal:      {t.get('contract', {}).get('goal')}")
            criteria = t.get("contract", {}).get("acceptance_criteria", [])
            if criteria:
                print(f"Criteria:  {', '.join(criteria)}")
            chk = t.get("checkpoint")
            if chk:
                print(f"Phase:     {chk.get('phase', '')} -> {chk.get('next_action', '')}")
            return 0
        tasks = res.get("tasks", [])
        if not tasks:
            print("No agent tasks found.")
            return 0
        print(f"{'STATUS':<12} {'TASK ID':<24} {'GOAL'}")
        print("-" * 65)
        for t in tasks:
            st = str(t.get("status", "")).upper()
            tid = str(t.get("task_id", ""))[:23]
            goal = str(t.get("contract", {}).get("goal", ""))
            if len(goal) > 40:
                goal = goal[:37] + "..."
            print(f"{st:<12} {tid:<24} {goal}")
        return 0
    if args.action == "memory":
        c = client()
        target_root = str(args.root.resolve()) if args.root else None
        root_kw = {"root": target_root} if target_root else {}
        if args.compact:
            res = c.coord("memory_compact", scope=args.scope or None, limit=args.limit, **root_kw)
            if args.raw_json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print(f"Compacted {res.get('compacted_records', 0)} records into {res.get('compacted_groups', 0)} digest group(s).")
            return 0 if res.get("success", True) else 1
        res = c.find_memory(scope=args.scope or None, key=args.key or None, query=args.query or None, limit=args.limit, **root_kw)
        if args.raw_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("success", True) else 1
        if not res.get("success", True):
            print(f"Failed to find memory: {res.get('error', 'unknown error')}", file=sys.stderr)
            return 1
        records = res.get("records", [])
        if not records:
            print("No memory records found.")
            return 0
        print(f"{'SCOPE':<10} {'KIND':<8} {'KEY':<24} {'VALUE'}")
        print("-" * 65)
        for r in records:
            sc = str(r.get("scope", "")).lower()
            kd = str(r.get("kind", "")).lower()
            k = str(r.get("key", ""))[:23]
            v = str(r.get("value", ""))
            if len(v) > 30:
                v = v[:27] + "..."
            print(f"{sc:<10} {kd:<8} {k:<24} {v}")
        return 0
    if args.action == "doctor":
        c = client()
        res = c.doctor()
        if args.raw_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("success", True) else 1
        checks = res.get("checks", [])
        if checks:
            print(f"{'STATUS':<8} {'COMPONENT':<25} {'DETAIL'}")
            print("-" * 65)
            for c_item in checks:
                status_symbol = "[OK]" if c_item.get("status") == "OK" else f"[{c_item.get('status', 'WARN')}]"
                comp = str(c_item.get("component", ""))[:24]
                det = str(c_item.get("detail", ""))
                print(f"{status_symbol:<8} {comp:<25} {det}")
        else:
            for k, v in res.items():
                print(f"{k}: {v}")
        return 0 if res.get("success", True) else 1
    if args.action == "logs":
        c = client()
        res = c.logs(lines=args.limit or 200)
        lines = res.get("lines", [])
        if res.get("success") is False:
            status_code = res.get("status_code")
            status_suffix = f" (HTTP {status_code})" if status_code else ""
            error = res.get("error")
            detail = error if isinstance(error, str) and error else "request failed"
            print(f"Local AI Hub logs unavailable{status_suffix}: {detail}", file=sys.stderr)
            return 1
        for line in lines:
            print(line)
        if not args.follow:
            return 0 if res.get("success", True) else 1
        last_seen = lines[-1] if lines else None
        try:
            while True:
                time.sleep(1.0)
                follow_res = c.logs(lines=50)
                new_lines = follow_res.get("lines", [])
                if not new_lines:
                    continue
                if last_seen and last_seen in new_lines:
                    idx = len(new_lines) - 1 - new_lines[::-1].index(last_seen)
                    to_print = new_lines[idx + 1:]
                else:
                    to_print = new_lines
                for line in to_print:
                    print(line)
                if new_lines:
                    last_seen = new_lines[-1]
        except KeyboardInterrupt:
            return 0
    if args.action == "status":
        st = status(args.config)
        cfg = load_config(_config_arg(args.config))
        mode_result = _activity_mode_request(config_path=_config_arg(args.config))
        if st.get("running"):
            st["activity_mode"] = mode_result.get("mode") if mode_result.get("success") is True else "unknown"
            if mode_result.get("success") is not True:
                st["activity_mode_error"] = _activity_mode_error(mode_result)
        elif mode_result.get("success") is True:
            st["activity_mode"] = mode_result["mode"]
        if args.raw_json:
            print(json.dumps(st, indent=2, ensure_ascii=False))
            return 0
        if not st.get("running"):
            print("Local AI Hub: Offline (stopped)")
            if mode_result.get("success") is True:
                print(f"Activity mode: {mode_result['mode']}")
            else:
                print(f"Activity mode: Unknown ({_activity_mode_error(mode_result)})")
            return 0

        pid = st.get("hub_pid", "N/A")
        ver = st.get("version", "unknown")
        ollama_ok = st.get("ollama_online", False)
        ollama_cfg = cfg.get("ollama", {})
        ollama_enabled = bool(ollama_cfg.get("enabled", False)) if isinstance(ollama_cfg, dict) else False
        active_model = (st.get("scheduler") or {}).get("active_model") or "None"
        llama_status = (st.get("ollama_profile") or {}).get("llama_cpp", {})
        llama_models = llama_status.get("online_models", []) if isinstance(llama_status, dict) else []
        hardware = st.get("hardware") or {}
        gpus = hardware.get("gpus") or []
        gpu_name = gpus[0].get("name", "N/A") if (gpus and isinstance(gpus[0], dict)) else "N/A"
        vram_mb = gpus[0].get("vram_mb", 0) if (gpus and isinstance(gpus[0], dict)) else 0

        gen_cache = st.get("generation_cache") or {}
        cache_hits = gen_cache.get("hits", 0) or 0
        cache_misses = gen_cache.get("misses", 0) or 0

        model_inventory_line, agent_inventory_line = status_inventory_lines(st)

        print(f"Local AI Hub v{ver} - Online (PID: {pid})")
        print("=" * 55)
        if mode_result and mode_result.get("success") is True:
            print(f"Activity mode: {mode_result['mode']}")
        else:
            print(f"Activity mode: Unknown ({_activity_mode_error(mode_result or {})})")
        provider = llama_cpp_backend_selection(cfg)
        if provider == "ollama":
            ollama_state = 'Online' if ollama_ok else 'Offline'
            print(f"Backend:      Ollama {ollama_state} (Active: {active_model})")
        elif provider == "disabled":
            print("Backend:      Disabled by policy")
        else:
            online = bool(llama_status.get("online", False)) or bool(llama_models)
            llama_state = "Online" if online else "Offline"
            mode = str(llama_status.get("mode", "") or "")
            suffix = f"; device: {mode}" if provider == "llama.cpp (managed)" and mode else ""
            print(f"Backend:      {provider} {llama_state} ({len(llama_models)} models online{suffix})")
        if provider != "ollama":
            print(f"Ollama:       {'Enabled' if ollama_enabled else 'Disabled by policy'}")
        print(model_inventory_line)
        if gpu_name != "N/A":
            vram_str = f" ({vram_mb // 1024} GB)" if vram_mb else ""
            print(f"GPU:          {gpu_name}{vram_str}")
        print(f"Cache:        {cache_hits} hits, {cache_misses} misses")
        print(agent_inventory_line)
        return 0
    if args.action == "stop":
        ok = stop(); print("stopped" if ok else "stop failed"); return 0 if ok else 1
    if args.action == "start":
        ok = start(); print("started" if ok else "start failed"); return 0 if ok else 1
    ok = stop()
    if not ok:
        print("restart: stop failed", file=sys.stderr); return 1
    ok = start(); print("restarted" if ok else "restart: start failed"); return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
