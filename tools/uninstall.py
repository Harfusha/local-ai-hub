from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.process_utils import hidden_run_kwargs

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
MCP_NAMES = {"local-ai", "serena-local", "codegraph-local"}
POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
TOKEN_ECONOMY_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMY POLICY -->"
TOKEN_ECONOMY_POLICY_END = "<!-- END TOKEN ECONOMY POLICY -->"


def expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def configured_install_dir() -> Path:
    config = ROOT / "config.toml"
    if config.exists():
        try:
            with config.open("rb") as fh:
                cfg = tomllib.load(fh)
            return expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
        except Exception:
            pass
    return expand("~/.local-ai-hub")


def clean_json(path: Path) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"skip unparsable JSON: {path}")
        return
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        for name in MCP_NAMES:
            servers.pop(name, None)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"cleaned {path}")


def clean_codex(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(rf"\n?{re.escape(MARKER_BEGIN)}.*?{re.escape(MARKER_END)}\n?", "\n", text, flags=re.DOTALL)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"cleaned {path}")



def clean_policy(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    cleaned = re.sub(re.escape(POLICY_BEGIN) + r".*?" + re.escape(POLICY_END), "", text, flags=re.DOTALL)
    cleaned = re.sub(re.escape(TOKEN_ECONOMY_POLICY_BEGIN) + r".*?" + re.escape(TOKEN_ECONOMY_POLICY_END), "", cleaned, flags=re.DOTALL).strip() + "\n"
    if cleaned != text:
        path.write_text(cleaned, encoding="utf-8")
        print(f"cleaned policy {path}")


def stop_hub(install: Path) -> None:
    hubctl = install / "tools" / "hubctl.py"
    if not hubctl.exists():
        return
    try:
        subprocess.run([sys.executable, str(hubctl), "stop"], check=False, timeout=10, **hidden_run_kwargs())
    except Exception as exc:
        print(f"warning: could not stop hub: {exc}")


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required.")
    parser = argparse.ArgumentParser(description="Remove Local AI Hub integrations")
    parser.add_argument("--keep-install", action="store_true", help="Keep the installed Local AI Hub files")
    args = parser.parse_args()

    install = configured_install_dir()
    try:
        service = install / "tools" / "service.py"
        if service.exists():
            subprocess.run([sys.executable, str(service), "uninstall"], check=False, timeout=15, **hidden_run_kwargs())
    except Exception:
        pass
    stop_hub(install)

    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    clean_codex(codex_home / "config.toml")
    clean_json(home / ".claude.json")
    clean_json(home / ".gemini" / "settings.json")

    clean_policy(codex_home / "AGENTS.md")
    clean_policy(codex_home / "AGENTS.override.md")
    clean_policy(home / ".claude" / "CLAUDE.md")
    clean_policy(home / ".gemini" / "GEMINI.md")

    skills_to_clean = [
        "local-ai-orchestrator",
        "token-economizer",
        "caveman",
        "tool-orchestration",
        "ollama-quality-routing",
    ]
    for skill in skills_to_clean:
        for base in [
            home / ".agents" / "skills",
            codex_home / "skills",
            home / ".claude" / "skills",
            home / ".gemini" / "skills",
            home / ".gemini" / "config" / "skills",
        ]:
            path = base / skill
            if path.exists():
                shutil.rmtree(path)
                print(f"removed {path}")

    if install.exists() and not args.keep_install:
        try:
            shutil.rmtree(install)
            print(f"removed {install}")
        except OSError as exc:
            print(
                f"could not remove {install}: {exc}\n"
                "Run this script from the original unpacked bundle using a Python executable outside the install directory, or remove the directory manually."
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
