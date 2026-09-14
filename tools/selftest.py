from __future__ import annotations

import json
import os
import socket
import subprocess
import symtable
import builtins
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.config import load_config
from local_ai_hub.http_server import validate_network_security
from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub import __version__


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str, timeout: float = 1.5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))



def _undefined_globals() -> list[str]:
    """Catch runtime NameErrors that bytecode compilation alone cannot detect."""
    failures: list[str] = []
    builtin_names = set(dir(builtins)) | {"__file__", "__name__", "__package__", "__spec__", "__loader__", "__builtins__"}
    for base in (ROOT / "src", ROOT / "mcp", ROOT / "tools"):
        for path in sorted(base.rglob("*.py")):
            try:
                table = symtable.symtable(path.read_text("utf-8"), str(path), "exec")
            except (SyntaxError, UnicodeDecodeError) as exc:
                failures.append(f"{path.relative_to(ROOT)}: parse error: {exc}")
                continue
            module_defined = {
                symbol.get_name()
                for symbol in table.get_symbols()
                if symbol.is_assigned() or symbol.is_imported() or symbol.is_parameter()
            }
            def walk(scope: symtable.SymbolTable) -> None:
                for symbol in scope.get_symbols():
                    name = symbol.get_name()
                    if (
                        symbol.is_referenced()
                        and symbol.is_global()
                        and name not in module_defined
                        and name not in builtin_names
                    ):
                        failures.append(f"{path.relative_to(ROOT)}: undefined global {name}")
                for child in scope.get_children():
                    walk(child)
            walk(table)
    return sorted(set(failures))

def main() -> int:
    checks: list[dict[str, object]] = []
    undefined = _undefined_globals()
    checks.append({"name": "undefined-globals", "ok": not undefined, "errors": undefined})
    with tempfile.TemporaryDirectory(prefix="local-ai-hub-selftest-") as td:
        temp = Path(td)
        state = temp / "state"
        port = _free_port()
        cfg_path = temp / "config.toml"
        cfg_path.write_text(
            f'''[server]\nbind="127.0.0.1"\nport={port}\nstate_dir="{state.as_posix()}"\nauto_start_ollama=false\n\n[hardware]\nprofile="cpu"\nauto_tune=true\n\n[prewarm]\nenabled=false\n\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\n\n[resilience]\nwatchdog_enabled=false\n\n[code_intelligence]\nenabled=false\n\n[observability]\nenabled=false\n''',
            encoding="utf-8",
        )
        cfg = load_config(str(cfg_path))
        validate_network_security(cfg)
        checks.append({"name": "config", "ok": cfg["_hardware"]["profile"] == "cpu"})

        repo = temp / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "main.py").write_text("def main(): return 1\n", encoding="utf-8")
        for hidden in (".serena", ".codegraphcontext", ".local-ai-hub"):
            d = repo / hidden
            d.mkdir()
            (d / "generated.py").write_text("generated=True\n", encoding="utf-8")
        files = RepositoryTools(cfg).iter_files(str(repo))
        rel = {p.relative_to(repo).as_posix() for p in files}
        checks.append({"name": "repository-filtering", "ok": rel == {"src/main.py"}, "files": sorted(rel)})

        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.Popen(
            [sys.executable, "-m", "local_ai_hub", "--config", str(cfg_path)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **hidden_run_kwargs(text=True),
        )
        try:
            deadline = time.monotonic() + 12.0
            health = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    health = _get_json(f"http://127.0.0.1:{port}/health")
                    break
                except Exception:
                    time.sleep(0.1)
            if health is None:
                out, err = proc.communicate(timeout=1)
                raise RuntimeError(f"hub failed to become healthy: rc={proc.returncode} stdout={out[-2000:]} stderr={err[-4000:]}")
            checks.append({"name": "http-health", "ok": health.get("success") is True and health.get("version") == __version__, "health": health})
            capabilities = _get_json(f"http://127.0.0.1:{port}/api/capabilities", timeout=3.0)
            checks.append({"name": "http-capabilities", "ok": capabilities.get("success") is True})
            from local_ai_hub.agent_events import AgentStateStore, AgentEvent
            agent_store = AgentStateStore(state / "agent_state.sqlite3")
            res = agent_store.append(AgentEvent.create("test-stream", "test.ping", {"ok": True}, "selftest-key"))
            checks.append({"name": "agent-state-store", "ok": res.seq == 1})
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=2)

    ok = all(bool(item.get("ok")) for item in checks)
    print(json.dumps({"success": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
