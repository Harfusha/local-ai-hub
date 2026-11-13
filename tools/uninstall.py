from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_skill_ownership_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_skill_ownership", Path(__file__).with_name("skill_ownership.py")
)
if _skill_ownership_spec is None or _skill_ownership_spec.loader is None:
    raise ImportError("could not load sibling skill_ownership.py")
_skill_ownership_module = importlib.util.module_from_spec(_skill_ownership_spec)
_skill_ownership_spec.loader.exec_module(_skill_ownership_module)
remove_owned_skill = _skill_ownership_module.remove_skill

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.process_utils import hidden_run_kwargs

_install_ownership_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_install_ownership", Path(__file__).with_name("install_ownership.py")
)
if _install_ownership_spec is None or _install_ownership_spec.loader is None:
    raise ImportError("could not load sibling install_ownership.py")
_install_ownership_module = importlib.util.module_from_spec(_install_ownership_spec)
_install_ownership_spec.loader.exec_module(_install_ownership_module)
MANIFEST_NAME = _install_ownership_module.MANIFEST_NAME
read_install_manifest = _install_ownership_module.read_install_manifest
_json_digest = _install_ownership_module._json_digest

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
MCP_NAMES = {"local-ai", "serena-local"}
POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
TOKEN_ECONOMY_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMY POLICY -->"
TOKEN_ECONOMY_POLICY_END = "<!-- END TOKEN ECONOMY POLICY -->"


def is_managed_mcp_server(name: Any) -> bool:
    """Return True if server name is a Local AI Hub managed MCP server."""
    if not isinstance(name, str):
        return False
    return name in MCP_NAMES


def expand(value: str) -> Path:
    if not isinstance(value, str) or "\x00" in value:
        return Path.home() / ".local-ai-hub"
    try:
        return Path(os.path.expandvars(os.path.expanduser(value))).resolve()
    except (ValueError, OSError):
        return Path.home() / ".local-ai-hub"


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


def _has_reparse_component(path: Path) -> bool:
    reparse_flag = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        if component.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse_flag):
            return True
        if getattr(component, "is_junction", lambda: False)():
            return True
    return False


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _is_within(path: Path, root: Path) -> bool:
    try:
        normalized_path = os.path.normcase(os.path.abspath(os.fspath(path)))
        normalized_root = os.path.normcase(os.path.abspath(os.fspath(root)))
        return os.path.commonpath((normalized_path, normalized_root)) == normalized_root
    except (OSError, TypeError, ValueError):
        return False


def build_uninstall_plan(
    install_dir: Path,
    *,
    source_root: Path = ROOT,
    home: Path | None = None,
) -> dict[str, Any]:
    """Validate target and return owned paths without performing side effects."""
    raw_install = Path(install_dir)
    if not raw_install.is_absolute():
        raise ValueError("unsafe uninstall path: path must be absolute")
    install = Path(os.path.abspath(os.fspath(raw_install)))
    source = Path(os.path.abspath(os.fspath(Path(source_root))))
    home_dir = Path(os.path.abspath(os.fspath(home or Path.home())))
    if install == Path(install.anchor) or install == home_dir or _overlaps(install, source):
        raise ValueError(f"unsafe uninstall path: {install}")
    if install in home_dir.parents:
        raise ValueError(f"unsafe uninstall path: install path contains user home: {install}")
    if _has_reparse_component(install):
        raise ValueError(f"unsafe uninstall path: symlink or junction in target path: {install}")
    if not install.exists():
        return {"install_dir": str(install), "owned_paths": [], "managed_paths": [], "already_absent": True}
    if not install.is_dir():
        raise ValueError(f"unsafe uninstall path: install target is not a directory: {install}")
    manifest = read_install_manifest(install)
    owned_paths = [str(install), *(str(install / relative) for relative in manifest["managed_paths"])]
    return {
        "install_dir": str(install),
        "install_id": manifest["install_id"],
        "owned_paths": owned_paths,
        "managed_paths": manifest["managed_paths"],
        "external_ownership": manifest.get("external_ownership", []),
        "already_absent": False,
    }


@dataclass(frozen=True)
class StopResult:
    status: str
    detail: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status in {"stopped", "already_stopped"}


def _entry_references_install(entry: Any, install_dir: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    root = os.path.normcase(os.path.abspath(os.fspath(install_dir)))
    values: list[str] = []
    for field in ("command", "cwd", "args", "env"):
        value = entry.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            values.extend(item for item in value.values() if isinstance(item, str))
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    for value in values:
        if not os.path.isabs(value):
            continue
        normalized = os.path.normcase(os.path.abspath(value))
        if normalized == root or normalized.startswith(root + os.sep):
            return True
    return False


def clean_json(path: Path, install_dir: Path | None = None) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"skip unparsable JSON: {path}")
        return
    if not isinstance(data, dict):
        return
    if install_dir is None or _has_reparse_component(path):
        return
    try:
        manifest = read_install_manifest(install_dir)
    except (OSError, ValueError):
        return
    normalized_path = os.path.normcase(os.path.abspath(os.fspath(path)))
    changed = False
    for entry in manifest.get("external_ownership", []):
        if (entry.get("kind") not in {"json_key", "json_list_item"}
                or os.path.normcase(os.path.abspath(entry.get("path", ""))) != normalized_path):
            continue
        marker = entry["owner_marker"]
        container: Any = data
        container_path = marker["container"]
        for segment in container_path.split(".") if container_path else []:
            container = container.get(segment) if isinstance(container, dict) else None
        if entry["kind"] == "json_list_item":
            item = marker["item"]
            if not isinstance(container, list) or item not in container:
                continue
            current = item
        else:
            if not isinstance(container, dict) or marker["key"] not in container:
                continue
            current = container[marker["key"]]
        if _json_digest(current) != entry["last_hub_written_digest"]:
            print(f"preserving edited owned JSON value in {path}")
            continue
        if entry["created_by_hub"]:
            if entry["kind"] == "json_list_item":
                container.remove(item)
            else:
                del container[marker["key"]]
            changed = True
            continue
        reference = entry.get("rollback_reference")
        if not isinstance(reference, str):
            print(f"preserving MCP entry without rollback reference in {path}")
            continue
        root = Path(install_dir)
        rollback_path = root.joinpath(*reference.replace("\\", "/").split("/"))
        if _has_reparse_component(rollback_path) or not _is_within(rollback_path, root):
            print(f"preserving MCP entry with unsafe rollback reference in {path}")
            continue
        try:
            previous = json.loads(rollback_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            print(f"preserving MCP entry with unavailable rollback in {path}")
            continue
        if _json_digest(previous) != entry.get("preimage_digest"):
            print(f"preserving MCP entry with invalid rollback in {path}")
            continue
        container[marker["key"]] = previous
        changed = True
    container_entries = sorted(
        (entry for entry in manifest.get("external_ownership", [])
         if entry.get("kind") == "json_container"
         and os.path.normcase(os.path.abspath(entry.get("path", ""))) == normalized_path),
        key=lambda entry: len(entry["owner_marker"]["path"].split(".")),
        reverse=True,
    )
    for entry in container_entries:
        marker = entry["owner_marker"]
        segments = marker["path"].split(".")
        parent: Any = data
        for segment in segments[:-1]:
            parent = parent.get(segment) if isinstance(parent, dict) else None
        if not isinstance(parent, dict):
            continue
        key = segments[-1]
        value = parent.get(key)
        empty = isinstance(value, dict) and not value if marker["container_type"] == "object" else isinstance(value, list) and not value
        if entry["created_by_hub"] and empty:
            del parent[key]
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"cleaned owned MCP entries from {path}")


def clean_codex(path: Path, install_dir: Path | None = None) -> None:
    clean_policy(path, install_dir)


def clean_policy(path: Path, install_dir: Path | None = None) -> None:
    if _has_reparse_component(path):
        print(f"preserving policy through symlink or junction: {path}")
        return
    if not path.is_file():
        return
    if install_dir is None:
        print(f"preserving unverified policy ownership: {path}")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        manifest = read_install_manifest(install_dir)
    except (OSError, ValueError):
        print(f"preserving policy without valid ownership manifest: {path}")
        return
    normalized_path = os.path.normcase(os.path.abspath(os.fspath(path)))
    cleaned = text
    for entry in manifest.get("external_ownership", []):
        if (entry.get("kind") != "text_block"
                or os.path.normcase(os.path.abspath(entry.get("path", ""))) != normalized_path):
            continue
        marker = entry["owner_marker"]
        pattern = re.compile(re.escape(marker["begin"]) + r".*?" + re.escape(marker["end"]), re.DOTALL)
        matches = list(pattern.finditer(cleaned))
        if len(matches) != 1:
            print(f"preserving missing or ambiguous owned policy block: {path}")
            continue
        current_block = matches[0].group(0)
        current_digest = hashlib.sha256(current_block.encode("utf-8")).hexdigest()
        if current_digest != entry["last_hub_written_digest"]:
            print(f"preserving edited owned policy block: {path}")
            continue
        replacement = ""
        if not entry["created_by_hub"]:
            reference = entry.get("rollback_reference")
            if not isinstance(reference, str):
                print(f"preserving policy block without rollback reference: {path}")
                continue
            root = Path(install_dir)
            rollback_path = root.joinpath(*reference.replace("\\", "/").split("/"))
            if _has_reparse_component(rollback_path) or not _is_within(rollback_path, root):
                print(f"preserving policy block with unsafe rollback reference: {path}")
                continue
            try:
                replacement = rollback_path.read_text(encoding="utf-8")
            except OSError:
                print(f"preserving policy block with unavailable rollback: {path}")
                continue
            if hashlib.sha256(replacement.encode("utf-8")).hexdigest() != entry.get("preimage_digest"):
                print(f"preserving policy block with invalid rollback: {path}")
                continue
        cleaned = pattern.sub(lambda _match: replacement, cleaned, count=1)
    if cleaned != text:
        path.write_text(cleaned, encoding="utf-8")
        print(f"cleaned policy {path}")


def clean_owned_file(path: Path, install_dir: Path) -> None:
    if _has_reparse_component(path) or not path.is_file():
        return
    try:
        manifest = read_install_manifest(install_dir)
        entry = next((item for item in manifest.get("external_ownership", [])
                      if item.get("kind") == "whole_file"
                      and os.path.normcase(os.path.abspath(item.get("path", "")))
                      == os.path.normcase(os.path.abspath(os.fspath(path)))), None)
    except (OSError, ValueError):
        return
    if entry is None:
        return
    try:
        content = path.read_bytes()
    except OSError:
        return
    if hashlib.sha256(content).hexdigest() != entry.get("last_hub_written_digest"):
        print(f"preserving edited Hub-owned file: {path}")
        return
    if not entry.get("created_by_hub"):
        print(f"preserving file without a deletion rollback: {path}")
        return
    path.unlink()
    print(f"removed Hub-owned file {path}")


def clean_external_configurations(entries: list[dict[str, Any]], install_dir: Path) -> None:
    """Clean only manifest-owned JSON keys and marked text blocks."""
    by_path: dict[str, tuple[Path, set[str]]] = {}
    for entry in entries:
        kind = entry.get("kind")
        if kind not in {"text_block", "json_key", "json_list_item", "json_container", "whole_file"} or not isinstance(entry.get("path"), str):
            continue
        path = Path(entry["path"])
        identity = os.path.normcase(os.path.abspath(os.fspath(path)))
        if identity not in by_path:
            by_path[identity] = (path, set())
        by_path[identity][1].add(kind)
    for path, kinds in by_path.values():
        if kinds & {"json_key", "json_list_item", "json_container"}:
            clean_json(path, install_dir)
        if "text_block" in kinds:
            clean_policy(path, install_dir)
        if "whole_file" in kinds:
            clean_owned_file(path, install_dir)


def _owned_hub_pids(install: Path) -> list[int] | None:
    resolver = install / "tools" / "resolve_hub_pids.py"
    config = install / "config.toml"
    if not resolver.is_file() or not config.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(resolver), "--config", str(config)],
            check=False,
            timeout=10,
            capture_output=True,
            text=True,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    pids = payload.get("pids") if isinstance(payload, dict) else None
    if not isinstance(pids, list) or any(type(pid) is not int or pid <= 0 for pid in pids):
        return None
    return sorted(set(pids))


def stop_hub(install: Path) -> StopResult:
    before = _owned_hub_pids(install)
    if before is None:
        return StopResult("unconfirmed", "could not verify Hub process ownership before stop")
    if not before:
        return StopResult("already_stopped")
    hubctl = install / "tools" / "hubctl.py"
    if not hubctl.is_file():
        return StopResult("failed", "hubctl.py is missing")
    try:
        result = subprocess.run(
            [sys.executable, str(hubctl), "stop"],
            check=False,
            timeout=10,
            capture_output=True,
            text=True,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return StopResult("failed", f"hubctl stop failed: {exc}")
    after = _owned_hub_pids(install)
    if after is None:
        return StopResult("unconfirmed", "could not verify Hub process state after stop")
    if after:
        return StopResult("unconfirmed", f"Hub still owns process IDs: {', '.join(map(str, after))}")
    if result.returncode != 0:
        return StopResult("failed", f"hubctl stop returned {result.returncode}; owned process state is stopped")
    return StopResult("stopped")


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required.")
    parser = argparse.ArgumentParser(description="Remove Local AI Hub integrations")
    parser.add_argument("--keep-install", action="store_true", help="Keep the installed Local AI Hub files")
    parser.add_argument("--dry-run", action="store_true", help="Show the ownership-checked uninstall plan without changes")
    parser.add_argument("--json", action="store_true", help="Print uninstall plan as JSON")
    args = parser.parse_args()

    install = configured_install_dir()
    try:
        plan = build_uninstall_plan(install)
    except (OSError, ValueError) as exc:
        print(f"uninstall refused: {exc}")
        print("Keep files in place. Reinstall or repair the ownership marker, or remove the install manually after reviewing its exact path.")
        return 1
    if args.json or args.dry_run:
        print(json.dumps({"success": True, "plan": plan}, indent=2, ensure_ascii=False))
    else:
        print(f"Uninstall plan: {json.dumps(plan, ensure_ascii=False)}")
    if args.dry_run or plan.get("already_absent"):
        return 0

    stop_result = stop_hub(install)
    if isinstance(stop_result, str):
        stop_result = StopResult(stop_result)
    if not isinstance(stop_result, StopResult) or not stop_result.confirmed:
        detail = stop_result.detail if isinstance(stop_result, StopResult) else "invalid stop result"
        print(f"uninstall refused: Hub stop is unconfirmed ({detail})")
        print("No files were removed. Check the active Hub process and retry after its stopped state is confirmed.")
        return 1

    try:
        service = install / "tools" / "service.py"
        if service.exists():
            service_result = subprocess.run(
                [sys.executable, str(service), "uninstall"],
                check=False,
                timeout=15,
                capture_output=True,
                text=True,
                **hidden_run_kwargs(),
            )
            if service_result.returncode != 0:
                print(f"uninstall refused: service uninstall returned {service_result.returncode}; no install files removed")
                return 1
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"uninstall refused: service uninstall could not be confirmed ({exc}); no install files removed")
        return 1
    post_service_stop = stop_hub(install)
    if not post_service_stop.confirmed:
        print(f"uninstall refused: Hub stop could not be reconfirmed ({post_service_stop.detail}); no install files removed")
        return 1

    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    clean_external_configurations(plan.get("external_ownership", []), install)

    skills_to_clean = [
        "local-ai-orchestrator",
        "token-economizer",
        "caveman",
        "tool-orchestration",
        "ollama-quality-routing",
    ]
    ownership_manifest = install / ".local-ai-hub-skill-ownership.json"
    for skill in skills_to_clean:
        for base in [
            home / ".agents" / "skills",
            codex_home / "skills",
            home / ".claude" / "skills",
            home / ".gemini" / "skills",
            home / ".gemini" / "config" / "skills",
        ]:
            path = base / skill
            if path.exists() or path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                try:
                    print(remove_owned_skill(path, base, ownership_manifest, skill))
                except ValueError as exc:
                    print(f"preserved conflicting skill tree: {path} ({exc})")

    if install.exists() and not args.keep_install:
        try:
            refreshed_plan = build_uninstall_plan(install)
            if refreshed_plan.get("install_id") != plan.get("install_id"):
                print("uninstall refused: ownership marker changed after preflight")
                return 1
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
