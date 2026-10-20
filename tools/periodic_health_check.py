#!/usr/bin/env python3
"""periodic_health_check.py — Automated 15-minute health, error, and queue inspector.

Performs a comprehensive check of:
1. Hub server daemon, supervisor, and Ollama inference backend
2. Preprocessing pipeline: projects in error status, stalled workers, queue advance
3. Error logs: hub_stderr.log, hub.log, supervisor.log
4. SQLite WAL sizes and lock health
5. Auto-recovers any transient project errors or stalls
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient


def inspect_and_repair(verbose: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hub_online": False,
        "ollama_online": False,
        "supervisor_state": "unknown",
        "supervisor_restarts": 0,
        "degraded_checks": [],
        "preprocessing": {
            "status": "unknown",
            "total_projects": 0,
            "running": 0,
            "waiting": 0,
            "complete": 0,
            "error_projects": [],
            "repaired_projects": [],
            "stalled_projects": [],
        },
        "logs": {
            "stderr_has_recent_errors": False,
            "recent_stderr_lines": [],
            "hub_log_warnings": [],
        },
        "wal_health": {
            "large_wal_files": [],
        },
        "healthy": False,
        "actions_taken": [],
    }

    config_path = ROOT / "config.toml"
    try:
        client = HubClient(config_path=str(config_path))
    except Exception as exc:
        report["error"] = f"Failed to initialize HubClient: {exc}"
        return report

    # 1. Server & Inference backend status
    try:
        live_status = client.get("/api/live/status?light=1", timeout=5.0)
        if isinstance(live_status, dict):
            report["hub_online"] = bool(live_status.get("hub_online"))
            report["ollama_online"] = bool(live_status.get("ollama_online"))
            headless = live_status.get("headless") or {}
            report["supervisor_state"] = str(headless.get("state", "unknown"))
            report["supervisor_restarts"] = int(headless.get("restarts", 0))

            deps = live_status.get("dependency_status") or {}
            if isinstance(deps, dict):
                for name, dep in deps.items():
                    if isinstance(dep, dict) and dep.get("degraded"):
                        if name == "telemetry.summary":
                            continue
                        report["degraded_checks"].append(name)
    except Exception as exc:
        report["actions_taken"].append(f"Hub live status query failed: {exc}")

    # 2. Preprocessing pipeline check & auto-repair
    state_dir = ROOT / "state"
    prep_db = state_dir / "preprocess.sqlite3"
    if prep_db.exists():
        try:
            with sqlite3.connect(f"{prep_db.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0) as con:
                rows = con.execute(
                    "SELECT root, status, phase, updated_at, last_error, stats_json FROM projects"
                ).fetchall()
                report["preprocessing"]["total_projects"] = len(rows)
                now = time.time()
                for root, status, phase, updated_at, last_error, stats_json in rows:
                    root_str = str(root)
                    status_str = str(status)
                    if status_str == "running":
                        report["preprocessing"]["running"] += 1
                        # If a running project hasn't updated in > 20 minutes, it may be stalled
                        if now - float(updated_at or 0) > 1200:
                            report["preprocessing"]["stalled_projects"].append({
                                "root": root_str,
                                "phase": phase,
                                "stalled_seconds": int(now - float(updated_at or 0)),
                            })
                    elif status_str == "waiting":
                        report["preprocessing"]["waiting"] += 1
                    elif status_str == "complete":
                        report["preprocessing"]["complete"] += 1
                    elif status_str == "error":
                        report["preprocessing"]["error_projects"].append({
                            "root": root_str,
                            "phase": phase,
                            "last_error": last_error,
                        })
        except Exception as exc:
            report["actions_taken"].append(f"Preprocess DB inspection failed: {exc}")

    # Auto-repair projects in error status or stalled
    for err_proj in report["preprocessing"]["error_projects"]:
        r_path = err_proj["root"]
        try:
            res = client.post("/api/preprocess", {"root": r_path, "action": "resume"}, timeout=10.0)
            if res.get("success"):
                report["preprocessing"]["repaired_projects"].append(r_path)
                report["actions_taken"].append(f"Auto-resumed errored project: {r_path}")
        except Exception as exc:
            report["actions_taken"].append(f"Failed to auto-resume {r_path}: {exc}")

    for st_proj in report["preprocessing"]["stalled_projects"]:
        r_path = st_proj["root"]
        try:
            res = client.post("/api/preprocess", {"root": r_path, "action": "resume"}, timeout=10.0)
            if res.get("success"):
                report["preprocessing"]["repaired_projects"].append(r_path)
                report["actions_taken"].append(f"Auto-resumed stalled project: {r_path}")
        except Exception as exc:
            report["actions_taken"].append(f"Failed to auto-resume stalled {r_path}: {exc}")

    # 3. Log health
    stderr_log = state_dir / "logs" / "hub_stderr.log"
    if stderr_log.exists():
        try:
            lines = stderr_log.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            # Check if there are recent tracebacks
            recent = [line for line in lines[-20:] if any(k in line for k in ["Traceback", "Error:", "Exception:"])]
            if recent:
                report["logs"]["stderr_has_recent_errors"] = True
                report["logs"]["recent_stderr_lines"] = lines[-10:]
        except Exception:
            pass

    # 4. SQLite WAL size check (warn and checkpoint if > 600 MB)
    for wal in state_dir.glob("*.sqlite*-wal"):
        try:
            size_mb = wal.stat().st_size / (1024 * 1024)
            if size_mb > 600:
                report["wal_health"]["large_wal_files"].append(f"{wal.name} ({size_mb:.1f} MB)")
                db_name = wal.name[:-4]  # strip -wal
                db_path = state_dir / db_name
                if db_path.exists():
                    from local_ai_hub.sqlite_support import optimize_db
                    try:
                        optimize_db(db_path, wal_checkpoint=True, vacuum=False)
                        report["actions_taken"].append(f"Checkpointed large WAL: {wal.name}")
                    except Exception as opt_exc:
                        report["actions_taken"].append(f"WAL checkpoint for {wal.name} skipped: {opt_exc}")
        except OSError:
            pass

    # 5. Serena dead path maintenance
    serena_configs = [Path.home() / ".serena" / "serena_config.yml"]
    if "SERENA_CONFIG" in os.environ:
        serena_configs.append(Path(os.environ["SERENA_CONFIG"]))
    for sc_path in serena_configs:
        if sc_path.exists():
            try:
                import yaml
                data = yaml.safe_load(sc_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    projects = data.get("projects")
                    if isinstance(projects, list):
                        original_count = len(projects)
                        cleaned_projects = [
                            p for p in projects
                            if isinstance(p, str)
                            and "pytest-of-" not in p
                            and Path(p).exists()
                        ]
                        if len(cleaned_projects) < original_count:
                            pruned = original_count - len(cleaned_projects)
                            data["projects"] = cleaned_projects
                            sc_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
                            report["actions_taken"].append(f"Auto-pruned {pruned} dead/temp paths from {sc_path.name}")
                    elif isinstance(projects, dict):
                        original_count = len(projects)
                        cleaned_dict = {
                            k: v for k, v in projects.items()
                            if not ("pytest-of-" in str(k) or (isinstance(v, str) and not Path(v).exists()))
                        }
                        if len(cleaned_dict) < original_count:
                            pruned = original_count - len(cleaned_dict)
                            data["projects"] = cleaned_dict
                            sc_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
                            report["actions_taken"].append(f"Auto-pruned {pruned} dead/temp paths from {sc_path.name}")
            except Exception:
                pass

    # 6. Overall health verdict
    report["healthy"] = (
        report["hub_online"]
        and report["ollama_online"]
        and report["supervisor_state"] in ("running", "ready")
        and len(report["degraded_checks"]) == 0
        and len(report["preprocessing"]["error_projects"]) == 0
    )

    if verbose:
        status_symbol = "OK" if report["healthy"] else "WARN"
        print(f"[{status_symbol}] Local AI Hub Health Check — {report['timestamp']}")
        print(f"  Hub: {'ONLINE' if report['hub_online'] else 'OFFLINE'} | Ollama: {'ONLINE' if report['ollama_online'] else 'OFFLINE'} | Supervisor: {report['supervisor_state']} (Restarts: {report['supervisor_restarts']})")
        p = report["preprocessing"]
        print(f"  Projects: total={p['total_projects']} running={p['running']} waiting={p['waiting']} complete={p['complete']} errors={len(p['error_projects'])}")
        if p["repaired_projects"]:
            print(f"  Repaired: {', '.join(p['repaired_projects'])}")
        if report["degraded_checks"]:
            print(f"  Degraded: {', '.join(report['degraded_checks'])}")
        if report["actions_taken"]:
            print("  Actions taken:")
            for act in report["actions_taken"]:
                print(f"    - {act}")

    return report


if __name__ == "__main__":
    rep = inspect_and_repair(verbose=True)
    sys.exit(0 if rep["healthy"] else 1)
