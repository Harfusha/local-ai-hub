from __future__ import annotations

import argparse
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
from local_ai_hub.process_utils import hidden_run_kwargs, terminate_tree

ROOT_CONFIG = ROOT / "config.toml"


def _config_arg(explicit: Path | None = None) -> str | None:
    if explicit is not None:
        return str(explicit.expanduser())
    return str(ROOT_CONFIG) if ROOT_CONFIG.is_file() else None


def client() -> HubClient:
    return HubClient(tenant="hubctl", config_path=_config_arg())


def status() -> dict:
    c = client()
    if not c._online():
        return {"running": False}
    try:
        data = c.status()
    except Exception:
        data = {}
    data["running"] = True
    return data


def _service(action: str) -> bool:
    service = ROOT / "tools" / "service.py"
    if not service.exists():
        return False
    try:
        completed = subprocess.run([sys.executable, str(service), action], check=False, timeout=35, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_run_kwargs())
        return completed.returncode == 0
    except Exception:
        return False


def _startup_wait_seconds() -> float:
    """Match the supervisor's cold-start contract, with a bounded probe margin."""
    try:
        grace = float(load_config(_config_arg()).get("headless", {}).get("startup_grace_seconds", 120.0))
    except Exception:
        grace = 120.0
    return min(180.0, max(12.0, grace + 5.0))


def stop() -> bool:
    # Stop the supervisor/service first; killing only the hub would make the supervisor restart it.
    _service("stop")
    data = status()
    if not data.get("running"):
        return True
    pid = int(data.get("hub_pid", 0) or 0)
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        terminate_tree(pid, grace_seconds=5.0)
    except Exception:
        return False
    deadline = time.time() + 8
    c = client()
    while time.time() < deadline:
        if not c._online():
            return True
        time.sleep(0.15)
    return not c._online()


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the Local AI Hub singleton")
    parser.add_argument("action", choices=["status", "start", "stop", "restart", "watch", "dashboard", "service-status", "agent-state", "cleanup", "clean", "generate", "tasks", "memory", "doctor", "logs"])
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml")
    parser.add_argument("--install", action="store_true", help="Also deploy generated skill/instructions to configured agents")
    parser.add_argument("--task-id", type=str, default="", help="Task ID for task lookup")
    parser.add_argument("--status", type=str, default="", help="Task status filter (planned, active, verifying, completed, failed, blocked)")
    parser.add_argument("--complete", action="store_true", help="Mark task as completed")
    parser.add_argument("--fail", action="store_true", help="Mark task as failed")
    parser.add_argument("--reason", type=str, default="", help="Reason for completing or failing task")
    parser.add_argument("--scope", type=str, default="", help="Memory scope filter (task, session, branch, project, user, global)")
    parser.add_argument("--key", type=str, default="", help="Memory key filter")
    parser.add_argument("--query", type=str, default="", help="Memory search query")
    parser.add_argument("--limit", type=int, default=50, help="Maximum items to return")
    parser.add_argument("--compact", action="store_true", help="Compact older memory records into digest summaries")
    parser.add_argument("--vacuum", action="store_true", help="Run SQLite WAL checkpoint and VACUUM during cleanup")
    parser.add_argument("--ports", action="store_true", help="Also terminate orphaned background processes on ports 11436, 11437, 11439")
    parser.add_argument("-f", "--follow", action="store_true", help="Stream log output continuously (like tail -f)")
    parser.add_argument("--json", dest="raw_json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()
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
            setup_mod.configure_agents(install_dir, python_bin, None, None, cfg)
        print(json.dumps({"success": True, "generated": res}, indent=2, ensure_ascii=False))
        return 0
    if args.action == "watch":
        return subprocess.call([sys.executable, str(ROOT / "tools" / "monitor.py")])
    if args.action == "dashboard":
        c = client(); print(c.base_url + "/dashboard"); return 0
    if args.action == "service-status":
        path = Path(load_config(_config_arg())["server"]["state_dir"]) / "supervisor.status.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"running": False}, indent=2)); return 0
    if args.action == "agent-state":
        c = client()
        print(json.dumps(c.status(detail="agent_state"), indent=2, ensure_ascii=False))
        return 0
    if args.action == "cleanup":
        cleaned_ports: list[dict[str, Any]] = []
        if args.ports:
            from local_ai_hub.process_utils import find_listening_pid, terminate_tree
            for port in [11436, 11437, 11439]:
                pid = find_listening_pid(port)
                if pid and pid > 0 and pid != os.getpid():
                    terminate_tree(pid, grace_seconds=2.0)
                    cleaned_ports.append({"port": port, "pid": pid})
        c = client()
        try:
            try:
                res = c.post("/api/agent-state/cleanup", {}, timeout=3.0)
            except TypeError:
                res = c.post("/api/agent-state/cleanup", {})
        except Exception as e:
            res = {"success": bool(cleaned_ports), "server_status": "offline", "detail": str(e)}
        if cleaned_ports:
            res["cleaned_ports"] = cleaned_ports

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
    if args.action == "tasks":
        c = client()
        if args.complete or args.fail:
            if not args.task_id:
                print("Error: --task-id is required when completing or failing a task.", file=sys.stderr)
                return 1
            reason = args.reason or ("completed via hubctl" if args.complete else "failed via hubctl")
            res = c.complete_task(args.task_id, reason=reason) if args.complete else c.fail_task(args.task_id, reason=reason)
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
            res = c.get_task(args.task_id)
        else:
            res = c.list_tasks(status=args.status or None, limit=args.limit)
        if args.raw_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("success", True) else 1
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
        if args.compact:
            res = c.coord("memory_compact", scope=args.scope or None, limit=args.limit)
            if args.raw_json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print(f"Compacted {res.get('compacted_records', 0)} records into {res.get('compacted_groups', 0)} digest group(s).")
            return 0 if res.get("success", True) else 1
        res = c.find_memory(scope=args.scope or None, key=args.key or None, query=args.query or None, limit=args.limit)
        if args.raw_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0 if res.get("success", True) else 1
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
                status_symbol = "[✓]" if c_item.get("status") == "OK" else f"[{c_item.get('status', 'WARN')}]"
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
        st = status()
        if args.raw_json:
            print(json.dumps(st, indent=2, ensure_ascii=False))
            return 0
        if not st.get("running"):
            print("Local AI Hub: Offline (stopped)")
            return 0

        pid = st.get("hub_pid", "N/A")
        ver = st.get("version", "unknown")
        ollama_ok = st.get("ollama_online", False)
        active_model = (st.get("scheduler") or {}).get("active_model") or "None"
        installed_models = st.get("installed_models", [])
        hardware = st.get("hardware") or {}
        gpus = hardware.get("gpus") or []
        gpu_name = gpus[0].get("name", "N/A") if (gpus and isinstance(gpus[0], dict)) else "N/A"
        vram_mb = gpus[0].get("vram_mb", 0) if (gpus and isinstance(gpus[0], dict)) else 0

        gen_cache = st.get("generation_cache") or {}
        cache_hits = gen_cache.get("hits", 0) or 0
        cache_misses = gen_cache.get("misses", 0) or 0

        agent_st = st.get("agent_state") or {}
        tasks_cnt = len(agent_st.get("tasks", [])) if isinstance(agent_st.get("tasks"), list) else 0
        leases_cnt = len(agent_st.get("leases", [])) if isinstance(agent_st.get("leases"), list) else 0

        print(f"Local AI Hub v{ver} — Online (PID: {pid})")
        print("=" * 55)
        print(f"Ollama:       {'Online' if ollama_ok else 'Offline'} (Active: {active_model})")
        model_sample = f" ({', '.join(installed_models[:3])}{'...' if len(installed_models) > 3 else ''})" if installed_models else ""
        print(f"Models:       {len(installed_models)} installed{model_sample}")
        if gpu_name != "N/A":
            vram_str = f" ({vram_mb // 1024} GB)" if vram_mb else ""
            print(f"GPU:          {gpu_name}{vram_str}")
        print(f"Cache:        {cache_hits} hits, {cache_misses} misses")
        print(f"Agent OS:     {tasks_cnt} tasks, {leases_cnt} leases active")
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
