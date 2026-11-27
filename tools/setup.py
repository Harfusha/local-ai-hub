from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable

_skill_ownership_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_skill_ownership", Path(__file__).with_name("skill_ownership.py")
)
if _skill_ownership_spec is None or _skill_ownership_spec.loader is None:
    raise ImportError("could not load sibling skill_ownership.py")
_skill_ownership_module = importlib.util.module_from_spec(_skill_ownership_spec)
_skill_ownership_spec.loader.exec_module(_skill_ownership_module)
install_owned_skill = _skill_ownership_module.install_skill
get_user_homes = _skill_ownership_module.get_user_homes
_install_ownership_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_install_ownership", Path(__file__).with_name("install_ownership.py")
)
if _install_ownership_spec is None or _install_ownership_spec.loader is None:
    raise ImportError("could not load sibling install_ownership.py")
_install_ownership_module = importlib.util.module_from_spec(_install_ownership_spec)
_install_ownership_spec.loader.exec_module(_install_ownership_module)
write_install_manifest = _install_ownership_module.write_install_manifest
record_external_block = _install_ownership_module.record_external_block
adopt_external_block = _install_ownership_module.adopt_external_block
assert_external_block_writable = _install_ownership_module.assert_external_block_writable
record_external_json_key = _install_ownership_module.record_external_json_key
assert_external_json_key_writable = _install_ownership_module.assert_external_json_key_writable
adopt_external_json_key = _install_ownership_module.adopt_external_json_key
record_external_json_list_item = _install_ownership_module.record_external_json_list_item
record_external_json_container = _install_ownership_module.record_external_json_container
record_external_file = _install_ownership_module.record_external_file
assert_external_file_writable = _install_ownership_module.assert_external_file_writable
forget_external_record = _install_ownership_module.forget_external_record
_ACTIVE_INSTALL_ROOT: Path | None = None
_ADOPT_UNOWNED_HUB_BLOCKS = True


def _assert_or_adopt_external_block(path: Path, owner_marker: dict[str, str], current_block: str) -> None:
    if _ACTIVE_INSTALL_ROOT is None:
        return
    try:
        assert_external_block_writable(
            _ACTIVE_INSTALL_ROOT, path, owner_marker=owner_marker, current_block=current_block
        )
    except ValueError as exc:
        if not _ADOPT_UNOWNED_HUB_BLOCKS or "external block has no ownership record" not in str(exc):
            raise
        reason = "Operator requested installation of current Local AI Hub agent instructions and MCP settings."
        if adopt_external_block(
            _ACTIVE_INSTALL_ROOT, path, owner_marker=owner_marker, expected_block=current_block,
            consent=True, audit_reason=reason,
        ):
            log(f"Adopted existing Local AI Hub block with rollback snapshot: {path}")

_update_transaction_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_update_transaction", Path(__file__).with_name("update_transaction.py")
)
if _update_transaction_spec is None or _update_transaction_spec.loader is None:
    raise ImportError("could not load sibling update_transaction.py")
_update_transaction_module = importlib.util.module_from_spec(_update_transaction_spec)
_update_transaction_spec.loader.exec_module(_update_transaction_module)
replace_install_payload = _update_transaction_module.replace_install_payload
stop_existing_runtime = _update_transaction_module.stop_existing_runtime
installation_update_lock = _update_transaction_module.installation_update_lock
_setup_wizard_spec = importlib.util.spec_from_file_location("_local_ai_hub_setup_wizard", Path(__file__).with_name("setup_wizard.py"))
if _setup_wizard_spec is None or _setup_wizard_spec.loader is None:
    raise ImportError("could not load sibling setup_wizard.py")
_setup_wizard_module = importlib.util.module_from_spec(_setup_wizard_spec)
_setup_wizard_spec.loader.exec_module(_setup_wizard_module)
configure_setup_choices = _setup_wizard_module.configure
apply_setup_choices = _setup_wizard_module.apply_choices
_setup_reinstall_spec = importlib.util.spec_from_file_location("_local_ai_hub_setup_reinstall", Path(__file__).with_name("setup_reinstall.py"))
if _setup_reinstall_spec is None or _setup_reinstall_spec.loader is None:
    raise ImportError("could not load sibling setup_reinstall.py")
_setup_reinstall_module = importlib.util.module_from_spec(_setup_reinstall_spec)
_setup_reinstall_spec.loader.exec_module(_setup_reinstall_module)
perform_full_reinstall = _setup_reinstall_module.perform_full_reinstall
_setup_report_spec = importlib.util.spec_from_file_location("_local_ai_hub_setup_report", Path(__file__).with_name("setup_report.py"))
if _setup_report_spec is None or _setup_report_spec.loader is None:
    raise ImportError("could not load sibling setup_report.py")
_setup_report_module = importlib.util.module_from_spec(_setup_report_spec)
_setup_report_spec.loader.exec_module(_setup_report_module)
write_setup_report = _setup_report_module.write_setup_report

SOURCE_ROOT = Path(__file__).resolve().parents[1]
# Keep the lexical path for safety checks; ``resolve()`` would erase evidence of
# a junction or symlink in one of the source checkout's ancestors.
UPDATE_SOURCE_ROOT = Path(__file__).absolute().parents[1]
SRC = SOURCE_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.config import load_config as load_hub_config  # noqa: E402
from tools.config_migrations import run_config_migrations  # noqa: E402
from tools.embedding_reset import (  # noqa: E402
    apply_embedding_reset, clear_embedding_payloads, discard_embedding_reset_backup,
)
from tools.prepare_release import version_parts  # noqa: E402
from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_managed_selected  # noqa: E402
from local_ai_hub.generator import (
    AUTOSETUP_POLICY_BEGIN as AUTOSETUP_BEGIN,
    AUTOSETUP_POLICY_END as AUTOSETUP_END,
    GLOBAL_POLICY_BEGIN,
    GLOBAL_POLICY_END,
    TOKEN_ECONOMY_POLICY_BEGIN,
    TOKEN_ECONOMY_POLICY_END,
    generate_antigravity_skill_policy,
    generate_autosetup_policy,
    generate_global_policy,
    generate_token_economy_policy,
    write_all_generated,
)  # noqa: E402
_state_migrations_spec = importlib.util.spec_from_file_location("_local_ai_hub_state_migrations", Path(__file__).with_name("state_migrations.py"))
if _state_migrations_spec is None or _state_migrations_spec.loader is None:
    raise ImportError("could not load sibling state_migrations.py")
_state_migrations_module = importlib.util.module_from_spec(_state_migrations_spec)
_state_migrations_spec.loader.exec_module(_state_migrations_module)
run_state_migrations = _state_migrations_module.run_state_migrations
inspect_state_migration_path = _state_migrations_module.inspect_state_migration_path
discard_stale_migration_artifacts = _state_migrations_module.discard_stale_migration_artifacts

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
GLOBAL_POLICY = generate_global_policy({})
def log(message: str) -> None:
    print(f"[local-ai-hub] {message}")


def write_migration_failure_report(
    install_dir: Path,
    state_dir: Path,
    *,
    stage: str,
    error: Exception,
    selected: dict[str, Any] | None = None,
) -> None:
    backups = [str(error.backup_path)] if isinstance(error, _state_migrations_module.StateMigrationError) else []
    report = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "requires_manual_migration",
        "install_dir": str(install_dir),
        "state_dir": str(state_dir),
        "selected": selected or {},
        "migration": {"stage": stage, "error": str(error), "backups": backups},
        "manual_actions": [
            "Keep the state directory unchanged and read docs/INSTALLER_RECOVERY.md.",
            "Use only a format-specific converter with verified preservation; do not edit state_version.json manually.",
        ],
        "recovery_guide": str(SOURCE_ROOT / "docs" / "INSTALLER_RECOVERY.md"),
    }
    try:
        report_path = write_setup_report(install_dir, report)
        log(f"Migration recovery report: {report_path}")
    except Exception as report_error:
        log(f"WARNING: could not write migration recovery report: {report_error}")


def write_setup_failure_report(
    install_dir: Path, state_dir: Path, *, stage: str, error: Exception | str
) -> None:
    report = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "failed",
        "install_dir": str(install_dir),
        "state_dir": str(state_dir),
        "failure": {"stage": stage, "error": str(error)},
        "manual_actions": [
            f"Setup stopped during {stage}; inspect the exact error and read docs/INSTALLER_RECOVERY.md.",
            "Preserve the configured state directory until the failed step is understood.",
        ],
        "recovery_guide": str(SOURCE_ROOT / "docs" / "INSTALLER_RECOVERY.md"),
    }
    try:
        report_path = write_setup_report(install_dir, report)
        log(f"Setup failure report: {report_path}")
    except Exception as report_error:
        log(f"WARNING: could not write setup failure report: {report_error}")


def run(
    cmd: list[str], *, check: bool = True, timeout: int | None = 120,
    capture: bool = False, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # Windows CreateProcess does not resolve PATHEXT (notably npm.cmd).
    cmd = [shutil.which(str(cmd[0])) or str(cmd[0]), *cmd[1:]]
    log("$ " + " ".join(f'\"{x}\"' if " " in str(x) else str(x) for x in cmd))
    options: dict[str, Any] = {
        "text": True, "check": check, "timeout": timeout,
        "stdout": subprocess.PIPE if capture else sys.stdout,
        "stderr": subprocess.PIPE if capture else sys.stderr,
        "encoding": "utf-8", "errors": "replace",
    }
    if env is not None:
        options["env"] = env
    return subprocess.run([str(x) for x in cmd], **options)


def verify_source_revision(expected_revision: str, *, source_root: Path = SOURCE_ROOT) -> str:
    """Require an exact, clean source checkout before copying files into the install."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_revision or ""):
        raise ValueError("--expected-revision must be a 40-character commit SHA")
    resolved = run(
        ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
        check=False, timeout=15, capture=True,
    )
    if resolved.returncode != 0:
        raise RuntimeError(f"Could not resolve source checkout revision at {source_root}")
    actual_revision = (resolved.stdout or "").strip().lower()
    if actual_revision != expected_revision.lower():
        raise RuntimeError(
            f"Source checkout {actual_revision or '<unknown>'} does not match expected verified commit {expected_revision}"
        )
    status = run(
        ["git", "-C", str(source_root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False, timeout=15, capture=True,
    )
    if status.returncode != 0:
        raise RuntimeError(f"Could not inspect source checkout status at {source_root}")
    if (status.stdout or "").strip():
        raise RuntimeError(f"source checkout is dirty; refusing install from {source_root}")
    return actual_revision


def install_persistent_service(python: Path, install_dir: Path) -> bool:
    """Install the user service and accept only a successful persistent mode."""
    try:
        result = run(
            [str(python), str(install_dir / "tools" / "service.py"), "install"],
            check=False, timeout=45, capture=True,
        )
    except Exception as exc:
        log(f"ERROR: service registration failed: {exc}")
        return False
    mode = (result.stdout or "").strip().splitlines()[-1].strip() if (result.stdout or "").strip() else ""
    if result.returncode != 0 or not is_valid_persistent_mode(mode):
        detail = f" (mode={mode or 'unknown'}, exit={result.returncode})"
        if result.stderr:
            detail += f": {result.stderr.strip()}"
        log("ERROR: service registration did not establish a persistent user service" + detail)
        return False
    log(f"Persistent user service registered: {mode}")
    return True


PERSISTENT_MODES = {
    "windows-logon-task", "windows-user-startup", "existing-service", "launchd", "systemd-user",
}


def is_valid_persistent_mode(mode: Any) -> bool:
    """Return True if mode is a recognized persistent service installation mode."""
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() in PERSISTENT_MODES


def expand(value: str) -> Path:
    if not isinstance(value, str) or "\x00" in value:
        return SOURCE_ROOT
    try:
        return Path(os.path.expandvars(os.path.expanduser(value))).resolve()
    except (ValueError, OSError):
        return SOURCE_ROOT


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_executable(venv: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return venv / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def ensure_venv(venv: Path) -> Path:
    python = venv_python(venv)
    if not python.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    return python


def install_requirements(python: Path, requirement: Path, *, optional: bool = False) -> bool:
    try:
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip", "wheel"], timeout=300)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirement)], timeout=1800)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if optional:
            log(f"WARNING: optional dependency install failed: {requirement.name}")
            return False
        raise


def _add_runtime_site_packages(python: Path) -> None:
    """Expose managed runtime dependencies to setup-time host integration hooks.

    The installer runs under the system Python, while project helpers such as
    repo_plan.host_hooks are installed in the managed environment. Both use the
    same Python version, so adding that environment's site-packages for this
    deferred import avoids requiring those dependencies globally.
    """
    venv_root = python.parent.parent
    if os.name == "nt":
        site_packages = venv_root / "Lib" / "site-packages"
    else:
        site_packages = venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    resolved = str(site_packages)
    if site_packages.is_dir() and resolved not in sys.path:
        sys.path.insert(0, resolved)


def copy_install_tree(
    install_dir: Path, config_source: Path, *,
    before_commit: Callable[[], tuple[bool, str]] | None = None,
    after_swap: Callable[[], tuple[bool, str]] | None = None,
) -> bool:
    success, detail = replace_install_payload(
        UPDATE_SOURCE_ROOT, install_dir, config_source, _update_transaction_module.PAYLOAD_FILES,
        before_commit=before_commit, after_swap=after_swap,
    )
    log(detail if success else f"ERROR: {detail}")
    return success


def migrate_release_state(state_dir: Path) -> dict[str, Any]:
    """Run ordered state migrations and the v8 vector reset for installer paths."""
    result = run_state_migrations(state_dir, create_backup=False)
    version = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version_parts(version) >= (8, 0, 0):
        reset = apply_embedding_reset(state_dir, create_backup=False)
        result["embedding_reset"] = reset["status"]
        result["embedding_reset_backup"] = reset.get("backup")
        for state_backup in result.get("backups", []):
            clear_embedding_payloads(state_backup)
    removed_artifacts = discard_stale_migration_artifacts(state_dir)
    if removed_artifacts:
        result["discarded_migration_artifacts"] = removed_artifacts
    return result


def backup(path: Path, enabled: bool) -> None:
    if not enabled or not path.exists():
        return
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = path.with_name(path.name + f".local-ai-hub-backup-{stamp}")
    shutil.copy2(path, dest)
    log(f"Backup: {dest}")


def install_skill(source_skill: Path, target: Path) -> None:
    install_root = source_skill.parent.parent
    manifest = install_root / ".local-ai-hub-skill-ownership.json"
    try:
        result = install_owned_skill(source_skill, target, target.parent, manifest, target.name)
    except ValueError as exc:
        result = f"skill not installed; ownership safety check failed: {exc}"
    log(result)


COMPANION_SKILLS: list[str] = [
    "token-economizer",
    "caveman",
    "ponytail",
    "ponytail-audit",
    "ponytail-debt",
    "ponytail-gain",
    "ponytail-help",
    "ponytail-review",
    "plan-led-work",
    "tool-orchestration",
    "ollama-quality-routing",
]

SUPERPOWERS_COMMIT = "cfd50a286baea35041505ed068c878d389ca9f7f"
SUPERPOWERS_ARCHIVE_SHA256 = "ef738adf14198b81739fea16ae37d0ee85bd67ceb47274f2dd691276df3b1656"
ANTIGRAVITY_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB ANTIGRAVITY SKILLS -->"
ANTIGRAVITY_POLICY_END = "<!-- END LOCAL AI HUB ANTIGRAVITY SKILLS -->"


def download_superpowers_archive() -> bytes:
    url = f"https://codeload.github.com/obra/superpowers/zip/{SUPERPOWERS_COMMIT}"
    deadline = monotonic() + 30
    for attempt in range(4):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Superpowers archive download exceeded deadline")
        try:
            payload = bytearray()
            with urllib.request.urlopen(url, timeout=min(10, remaining)) as response:
                while True:
                    if monotonic() >= deadline:
                        raise TimeoutError("Superpowers archive download exceeded deadline")
                    chunk = response.read1(min(65536, 10_000_001 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > 10_000_000:
                        raise ValueError("Superpowers archive exceeds size limit")
            return bytes(payload)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
            try:
                delay = min(8.0, max(0.0, float(exc.headers.get("Retry-After", ""))))
            except (TypeError, ValueError):
                delay = min(8.0, float(2 ** attempt))
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Superpowers archive download exceeded deadline") from exc
            sleep(min(delay, remaining))
    raise TimeoutError("Superpowers archive download exceeded deadline")


def install_superpowers_skills(target: Path, manifest: Path | None = None) -> None:
    """Install pinned Superpowers skills without replacing existing skill folders."""
    payload = download_superpowers_archive()
    if hashlib.sha256(payload).hexdigest() != SUPERPOWERS_ARCHIVE_SHA256:
        raise ValueError("Superpowers archive checksum mismatch")
    if manifest is None:
        manifest = target.parent / ".local-ai-hub-superpowers" / ".local-ai-hub-skill-ownership.json"
    source_root = manifest.parent
    for component in (source_root, *source_root.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError("Superpowers source path contains a link")
    source_root.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive, tempfile.TemporaryDirectory(prefix="hub-superpowers-", dir=source_root.parent) as temp:
        candidate = Path(temp) / "source"
        candidate.mkdir()
        stage = candidate / "skills"
        stage.mkdir()
        skills: set[str] = set()
        total = 0
        entries = archive.infolist()
        if len(entries) > 5000:
            raise ValueError("Superpowers archive has too many entries")
        for entry in entries:
            parts = entry.filename.split("/")
            if len(parts) < 4 or parts[1] != "skills" or entry.is_dir():
                continue
            relative = parts[2:]
            if any(not p or p in {".", ".."} or "\\" in p or ":" in p for p in relative):
                raise ValueError("Unsafe Superpowers archive path")
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Superpowers archive contains a link")
            total += entry.file_size
            if total > 20_000_000:
                raise ValueError("Superpowers skills exceed size limit")
            destination = stage.joinpath(*relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
            skills.add(relative[0])
        if not (stage / "using-superpowers" / "SKILL.md").is_file():
            raise ValueError("Superpowers bootstrap skill missing")
        if source_root.is_symlink() or getattr(source_root, "is_junction", lambda: False)():
            raise ValueError("Superpowers source root is a link")
        if source_root.exists():
            existing = source_root / "skills"
            def inventory(directory: Path) -> dict[str, str]:
                result = {}
                total_bytes = 0
                for count, path in enumerate(directory.rglob("*"), start=1):
                    if count > 5000:
                        raise ValueError("Superpowers source has too many files")
                    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                        raise ValueError("Superpowers source contains a link")
                    if path.is_file():
                        total_bytes += path.stat().st_size
                        if total_bytes > 20_000_000:
                            raise ValueError("Superpowers source exceeds size limit")
                        with path.open("rb") as stream:
                            result[path.relative_to(directory).as_posix()] = hashlib.sha256(stream.read().replace(b"\r\n", b"\n")).hexdigest()
                return result
            if not existing.is_dir() or inventory(existing) != inventory(stage):
                raise ValueError("Existing Superpowers source differs from pinned archive; review required")
        else:
            candidate.rename(source_root)
        stage = source_root / "skills"
        for name in sorted(skills):
            source = stage / name
            if not (source / "SKILL.md").is_file():
                continue
            log(install_owned_skill(source, target / name, target, manifest, name))


def merge_antigravity_skill_policy(path: Path, backup_enabled: bool) -> None:
    policy = generate_antigravity_skill_policy()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(ANTIGRAVITY_POLICY_BEGIN) + r".*?" + re.escape(ANTIGRAVITY_POLICY_END) + r"(?:\r?\n)*", re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        raise RuntimeError(f"multiple Antigravity policy blocks found in {path}")
    preimage = matches[0].group(0).rstrip("\r\n") if matches else None
    marker = {"begin": ANTIGRAVITY_POLICY_BEGIN, "end": ANTIGRAVITY_POLICY_END}
    unmanaged = pattern.sub("", text)
    separator = "" if not unmanaged else "\n" if unmanaged.startswith("\n") else "\n\n"
    updated = policy + separator + unmanaged
    if updated == text or (preimage is not None and preimage.replace("\r\n", "\n") == policy):
        return
    if preimage is not None:
        _assert_or_adopt_external_block(path, marker, preimage)
    backup(path, backup_enabled)
    path.write_bytes(updated.encode("utf-8"))
    if _ACTIVE_INSTALL_ROOT is not None:
        record_external_block(
            _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=marker,
            preimage=preimage, postimage=policy,
        )


def install_agent_skills(install_dir: Path, target_skills_dir: Path, *, include_companion: bool = True) -> None:
    source_skill = install_dir / "skills" / "local-ai-orchestrator"
    install_skill(source_skill, target_skills_dir / "local-ai-orchestrator")
    if include_companion:
        for skill_name in COMPANION_SKILLS:
            source = install_dir / "skills" / skill_name
            if source.exists():
                install_skill(source, target_skills_dir / skill_name)


def json_server_merge(
    path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool, *,
    container_key: str = "mcpServers", require_stdio_type: bool = False,
) -> None:
    """Merge Local AI servers without replacing unrelated client configuration.

    Cursor/Claude/Gemini/Windsurf use ``mcpServers`` while VS Code/Copilot's
    portable MCP format uses ``servers`` and requires an explicit stdio type.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        backup(path, backup_enabled)
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
            if raw_text:
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    raise ValueError("top-level JSON value must be an object")
                data = parsed
        except Exception as exc:
            raise RuntimeError(f"Cannot parse JSON config {path}: {exc}") from exc
    container = data
    created_containers: list[str] = []
    container_path: list[str] = []
    for segment in container_key.split("."):
        if not segment:
            raise ValueError("JSON container path has an empty segment")
        container_path.append(segment)
        child = container.get(segment)
        if child is None and segment not in container:
            child = {}
            container[segment] = child
            created_containers.append(".".join(container_path))
        if not isinstance(child, dict):
            raise RuntimeError(f"{'.'.join(container_path)} is not an object in {path}")
        container = child
    owned_writes: list[tuple[str, Any | None, dict[str, Any]]] = []
    for name, raw_entry in servers.items():
        entry = dict(raw_entry)
        existing = container.get(name)
        entry = preserve_isolated_hub_args(name, existing, entry)
        if require_stdio_type:
            entry.setdefault("type", "stdio")
        if _ACTIVE_INSTALL_ROOT is not None and name in container:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container=container_key, key=name, current_value=existing,
                )
            except ValueError:
                if existing != entry:
                    log(f"MCP entry '{name}' exists without matching ownership; leaving it unchanged in {path}")
                continue
        if existing == entry:
            continue
        container[name] = entry
        owned_writes.append((name, existing, entry))
    if _ACTIVE_INSTALL_ROOT is not None and not owned_writes and not created_containers:
        return
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        for name, preimage, postimage in owned_writes:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container=container_key, key=name,
                preimage=preimage, postimage=postimage,
            )
        for created in created_containers:
            record_external_json_container(
                _ACTIVE_INSTALL_ROOT, path, container_path=created, container_type="object",
            )
    log(f"MCP config updated: {path}")


def json_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool) -> None:
    json_server_merge(path, servers, backup_enabled, container_key="mcpServers")


def opencode_mcp_merge(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    cfg: dict[str, Any],
    backup_enabled: bool,
) -> None:
    """Merge Hub MCP into OpenCode's current `mcp.servers` configuration."""
    configured = build_mcp_entries(install_dir, hub_python, None, "opencode", cfg)
    servers = {
        name: {
            "type": "local",
            "command": [entry["command"], *entry.get("args", [])],
            "cwd": entry["cwd"],
            "environment": dict(entry.get("env", {})),
        }
        for name, entry in configured.items()
    }
    json_server_merge(path, servers, backup_enabled, container_key="mcp.servers")


def _opencode_model_context_limit(
    model_id: str,
    models_cfg: dict[str, Any],
    execution_cfg: dict[str, Any],
) -> int:
    """Return the configured Hub context ceiling for an OpenCode model catalog entry."""
    role_models = {
        role: value.strip() for role, value in models_cfg.items()
        if isinstance(value, str) and value.strip()
    }
    if model_id == role_models.get("opencode"):
        tier = "opencode"
    elif model_id == role_models.get("vision"):
        tier = "vision"
    elif model_id in (role_models.get("heavy_code"), role_models.get("reasoning")):
        tier = "smart"
    elif model_id == role_models.get("background_code"):
        tier = "background"
    elif model_id in (role_models.get("fast_code"), role_models.get("general")):
        tier = "fast"
    else:
        tier = "generic"

    policy = execution_cfg.get(tier, {})
    if not isinstance(policy, dict):
        return 16384
    configured = policy.get(
        "max_context_tokens",
        policy.get("large_context_tokens", policy.get("context_tokens", 16384)),
    )
    if isinstance(configured, bool) or not isinstance(configured, int) or not 4096 <= configured <= 131072:
        return 16384
    return configured


def sync_opencode_plugin_config(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    cfg: dict[str, Any],
    backup_enabled: bool,
) -> bool:
    """Register the Hub tool and receipt-gated goal plugins in OpenCode."""
    plugin_root = (install_dir / "plugins" / "opencode" / "local-ai-hub").resolve()
    goal_root = (install_dir / "tools" / "opencode_goal").resolve()
    if not plugin_root.is_dir() or not (goal_root / "index.js").is_file():
        log(f"OpenCode Hub plugin source is unavailable: {plugin_root} or {goal_root}")
        return False
    mcp_entry = build_mcp_entries(install_dir, hub_python, None, "opencode", cfg).get("local-ai")
    if not isinstance(mcp_entry, dict):
        log("OpenCode Hub plugin server config is unavailable")
        return False
    server_cfg = cfg.get("server", {}) if isinstance(cfg.get("server"), dict) else {}
    hub_port = server_cfg.get("port")
    if (server_cfg.get("bind", "127.0.0.1") != "127.0.0.1" or
            not isinstance(hub_port, int) or isinstance(hub_port, bool) or not 1 <= hub_port <= 65535):
        log("OpenCode goal plugin not configured because the Hub is not bound to a valid IPv4 loopback endpoint")
        return False
    environment = dict(mcp_entry.get("env", {}))
    environment["OPENCODE_SESSION"] = "1"
    environment["LOCAL_AI_HUB_DIR"] = str(install_dir.resolve())
    server = {
        "command": [str(Path(mcp_entry["command"]).resolve()), *mcp_entry.get("args", [])],
        "cwd": str(Path(mcp_entry["cwd"]).resolve()),
        "environment": environment,
        "nativeMcp": True,
    }
    native_mcp_server = {
        "type": "local",
        "command": server["command"],
        "cwd": server["cwd"],
        "environment": environment,
        # OpenCode's code mode exposes one bounded bridge tool instead of
        # injecting the Hub's large MCP catalog into every model prompt.
        "codemode": True,
        "timeout": {"startup": 60000, "catalog": 60000},
    }
    desired = [
        {"package": str(plugin_root), "options": {"server": server}},
        {"package": str(goal_root), "options": {
            "hubURL": f"http://127.0.0.1:{hub_port}", "actor": "opencode-local",
        }},
    ]
    models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models"), dict) else {}
    preferred_model = next((models_cfg.get(role) for role in ("opencode", "general", "heavy_code", "reasoning", "fast_code")
                            if isinstance(models_cfg.get(role), str) and models_cfg[role].strip()), None)
    if not isinstance(preferred_model, str) or not preferred_model.strip() or len(preferred_model) > 256:
        log("OpenCode local provider not configured because no local model role is configured")
        return False
    preferred_model = preferred_model.strip()
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in preferred_model):
        log("OpenCode local provider not configured because models.general is not a safe model ID")
        return False
    provider_models: dict[str, Any] = {}
    execution_cfg = cfg.get("model_execution", {}) if isinstance(cfg.get("model_execution"), dict) else {}
    for role in ("opencode", "general", "fast_code", "heavy_code", "reasoning"):
        model_id = models_cfg.get(role)
        if (not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 256
                or any(ord(char) < 0x21 or ord(char) > 0x7E for char in model_id)):
            continue
        model_id = model_id.strip()
        provider_models[model_id] = {
            "name": f"Local AI Hub / {model_id}",
            "modelID": model_id,
            "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            # Advertise the configured policy ceiling. Hub inference admission
            # still lowers the effective context when live VRAM is unknown/low.
            "limit": {"context": _opencode_model_context_limit(model_id, models_cfg, execution_cfg), "output": 2048},
        }
    desired_provider = {
        "name": "Local AI Hub",
        "package": "@opencode/ai/providers/openai-compatible",
        "settings": {"baseURL": f"http://127.0.0.1:{hub_port}/api"},
        "headers": {"X-LocalAI-Agent": "opencode"},
        "models": provider_models,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot safely merge OpenCode config {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"OpenCode config must be a JSON object: {path}")
        data = parsed

    missing = object()
    current = data.get("plugins", missing)
    if current is not missing and not isinstance(current, list):
        log(f"OpenCode plugins preserved because 'plugins' is not a list: {path}")
        return False
    if current is missing:
        previous: Any = None
        plugins = list(desired)
    else:
        previous = current
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="", key="plugins", current_value=current,
                )
            except ValueError as exc:
                if "has no ownership record" not in str(exc):
                    log(f"OpenCode plugins preserved; merge Hub plugin manually in {path}")
                    return False
                try:
                    adopt_external_json_key(
                        _ACTIVE_INSTALL_ROOT, path, container="", key="plugins", current_value=current,
                        consent=True, audit_reason="Install the requested OpenCode Hub route with exact rollback",
                    )
                except ValueError:
                    log(f"OpenCode plugins preserved; merge Hub plugin manually in {path}")
                    return False
        plugins = list(current)
    for plugin_entry in desired:
        package_path = plugin_entry["package"]
        replace_index = next((i for i, item in enumerate(plugins)
                              if isinstance(item, dict) and item.get("package") == package_path), None)
        if replace_index is None:
            plugins.append(plugin_entry)
        elif plugins[replace_index] != plugin_entry:
            plugins[replace_index] = plugin_entry
    # OpenCode auto-discovers Ollama independently of configured providers. Disable
    # that route so its local inference always passes through Hub policy/admission.
    if "-opencode.provider.ollama" not in plugins:
        plugins.append("-opencode.provider.ollama")
    data["plugins"] = plugins
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        log(f"OpenCode providers preserved because 'providers' is not an object: {path}")
        return False
    providers_container_created = "providers" not in data
    local_provider_present = "local-ai-hub" in providers
    local_provider_preimage = providers.get("local-ai-hub")
    if _ACTIVE_INSTALL_ROOT is not None and local_provider_present:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="providers", key="local-ai-hub",
                current_value=local_provider_preimage,
            )
        except ValueError:
            log(f"OpenCode local-ai-hub provider preserved; merge manually in {path}")
            return False
    providers = dict(providers)
    providers["local-ai-hub"] = desired_provider
    data["providers"] = providers
    mcp = data.get("mcp", {})
    if not isinstance(mcp, dict):
        log(f"OpenCode MCP config preserved because 'mcp' is not an object: {path}")
        return False
    mcp_container_created = "mcp" not in data
    servers = mcp.get("servers", {})
    if not isinstance(servers, dict):
        log(f"OpenCode MCP servers preserved because 'mcp.servers' is not an object: {path}")
        return False
    mcp_servers_container_created = "servers" not in mcp
    managed_mcp_present = "local-ai-hub" in servers
    managed_mcp_preimage = servers.get("local-ai-hub")
    if _ACTIVE_INSTALL_ROOT is not None and managed_mcp_present:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="mcp.servers", key="local-ai-hub",
                current_value=managed_mcp_preimage,
            )
        except ValueError:
            log(f"OpenCode local-ai-hub MCP server preserved; merge manually in {path}")
            return False
    servers = dict(servers)
    servers["local-ai-hub"] = native_mcp_server
    mcp = dict(mcp)
    mcp["servers"] = servers
    data["mcp"] = mcp
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        log(f"OpenCode agents preserved because 'agents' is not an object: {path}")
        return False
    agents_container_created = "agents" not in data
    managed_agent = {
        "mode": "primary",
        # Bound model/tool loops. OpenCode removes tools on the last step.
        "steps": 8,
        "permissions": [
            {"action": action, "resource": "*", "effect": "ask"}
            for action in ("edit", "shell", "external_directory", "webfetch", "websearch")
        ],
        "system": (
            "Use Local AI Hub MCP for repository evidence, task lifecycle, and receipts. "
            "In Code Mode discover tools with the top-level `search` function, then "
            "call `tools[\"local-ai-hub\"].local_ai_repo(...)` directly. Read results from "
            "`result.structuredContent ?? result`; do not guess response fields or stringify "
            "the full result. Follow repository instructions and OpenCode permissions. "
            "Use Hub task/checkpoint/resume/cancel actions for durable work; report missing "
            "receipts or blocked safety gates instead of claiming completion."
        ),
    }
    managed_agent_present = "local-ai-hub" in agents
    managed_agent_preimage = agents.get("local-ai-hub")
    if _ACTIVE_INSTALL_ROOT is not None and managed_agent_present:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="agents", key="local-ai-hub",
                current_value=managed_agent_preimage,
            )
        except ValueError:
            log(f"OpenCode local-ai-hub agent preserved; merge manually in {path}")
            return False
    agents = dict(agents)
    agents["local-ai-hub"] = managed_agent
    data["agents"] = agents
    default_agent_preimage = data.get("default_agent")
    if default_agent_preimage is None:
        data["default_agent"] = "local-ai-hub"
    model_preimage = data.get("model")
    if model_preimage is None:
        data["model"] = f"local-ai-hub/{preferred_model}"
    if (current is not missing and plugins == current and local_provider_preimage == desired_provider
            and managed_mcp_preimage == native_mcp_server and model_preimage is not None
            and managed_agent_preimage == managed_agent and default_agent_preimage is not None):
        return True
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if not path_existed:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
        if providers_container_created:
            record_external_json_container(
                _ACTIVE_INSTALL_ROOT, path, container_path="providers", container_type="object",
            )
        if mcp_container_created:
            record_external_json_container(
                _ACTIVE_INSTALL_ROOT, path, container_path="mcp", container_type="object",
            )
        if mcp_servers_container_created:
            record_external_json_container(
                _ACTIVE_INSTALL_ROOT, path, container_path="mcp.servers", container_type="object",
            )
        if agents_container_created:
            record_external_json_container(
                _ACTIVE_INSTALL_ROOT, path, container_path="agents", container_type="object",
            )
        record_external_json_key(
            _ACTIVE_INSTALL_ROOT, path, container="", key="plugins",
            preimage=previous, postimage=plugins,
        )
        record_external_json_key(
            _ACTIVE_INSTALL_ROOT, path, container="providers", key="local-ai-hub",
            preimage=local_provider_preimage, postimage=desired_provider,
        )
        record_external_json_key(
            _ACTIVE_INSTALL_ROOT, path, container="mcp.servers", key="local-ai-hub",
            preimage=managed_mcp_preimage, postimage=native_mcp_server,
        )
        record_external_json_key(
            _ACTIVE_INSTALL_ROOT, path, container="agents", key="local-ai-hub",
            preimage=managed_agent_preimage, postimage=managed_agent,
        )
        if default_agent_preimage is None:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="", key="default_agent",
                preimage=None, postimage="local-ai-hub",
            )
        if model_preimage is None:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="", key="model",
                preimage=None, postimage=data["model"],
            )
    log(f"OpenCode Hub plugin configured: {path}")
    return True


def _load_opencode_config(path: Path) -> dict[str, Any]:
    """Read OpenCode JSON/JSONC config without changing its source text."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.casefold() == ".jsonc":
        cleaned: list[str] = []
        index = 0
        in_string = False
        escaped = False
        while index < len(text):
            char = text[index]
            if in_string:
                cleaned.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                cleaned.append(char)
                index += 1
                continue
            if text.startswith("//", index):
                index += 2
                while index < len(text) and text[index] not in "\r\n":
                    index += 1
                continue
            if text.startswith("/*", index):
                end = text.find("*/", index + 2)
                if end < 0:
                    raise ValueError("unterminated JSONC block comment")
                cleaned.extend(char for char in text[index:end + 2] if char in "\r\n")
                index = end + 2
                continue
            if char == ",":
                lookahead = index + 1
                while lookahead < len(text) and text[lookahead].isspace():
                    lookahead += 1
                if lookahead < len(text) and text[lookahead] in "}]":
                    index += 1
                    continue
            cleaned.append(char)
            index += 1
        text = "".join(cleaned)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError(f"OpenCode config must be a JSON object: {path}")
    return data


def _opencode_direct_hub_mcp_server_name(path: Path) -> str | None:
    """Return a recognized Hub MCP server name from an OpenCode config."""
    if not path.is_file():
        return None
    try:
        data = _load_opencode_config(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect OpenCode config {path}: {exc}") from exc
    mcp = data.get("mcp")
    servers = mcp.get("servers") if isinstance(mcp, dict) else None
    if not isinstance(servers, dict):
        return None
    return next((name for name in ("local-ai-hub", "local-ai") if name in servers), None)


def opencode_direct_hub_mcp_configured(path: Path) -> bool:
    """Detect either managed Hub MCP route name in an OpenCode config."""
    return _opencode_direct_hub_mcp_server_name(path) is not None


def opencode_hub_mcp_paths(config_dir: Path) -> list[Path]:
    """Return configured global OpenCode files that already contain the Hub MCP route."""
    return [
        path for path in (config_dir / "opencode.json", config_dir / "opencode.jsonc")
        if opencode_direct_hub_mcp_configured(path)
    ]


def opencode_hub_plugin_paths(config_dir: Path) -> list[Path]:
    """Return global OpenCode config files already registering the Hub plugin."""
    configured: list[Path] = []
    for path in (config_dir / "opencode.json", config_dir / "opencode.jsonc"):
        if not path.is_file():
            continue
        try:
            data = _load_opencode_config(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot safely inspect OpenCode config {path}: {exc}") from exc
        entries = []
        for key in ("plugins", "plugin"):
            value = data.get(key)
            if isinstance(value, list):
                entries.extend(value)
            elif isinstance(value, str):
                entries.append(value)
        if any(
            "local-ai-hub" in str(entry.get("package", "") if isinstance(entry, dict) else entry).casefold()
            for entry in entries
        ):
            configured.append(path)
    return configured


def prune_direct_code_intelligence(
    path: Path, serena: Path | None, backup_enabled: bool,
) -> None:
    """Remove only stale Hub-generated direct backend entries from a JSON MCP manifest."""
    if not path.exists() or _ACTIVE_INSTALL_ROOT is None:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
            return
    except Exception as exc:
        raise RuntimeError(f"Cannot parse JSON config {path}: {exc}") from exc

    container = data["mcpServers"]
    expected = {"serena": serena}
    removed = False
    for name, executable in expected.items():
        entry = container.get(name)
        command = entry.get("command") if isinstance(entry, dict) else None
        if executable is None or not isinstance(command, str):
            continue
        if os.path.normcase(os.path.abspath(command)) == os.path.normcase(os.path.abspath(str(executable))):
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="mcpServers", key=name, current_value=entry,
                )
            except ValueError:
                log(f"Unowned direct code-intelligence entry preserved: {path}#{name}")
                continue
            del container[name]
            removed = True
    if removed:
        backup(path, backup_enabled)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for name in expected:
            forget_external_record(
                _ACTIVE_INSTALL_ROOT, path, kind="json_key",
                owner_marker={"container": "mcpServers", "key": name},
            )
        log(f"Stale direct code-intelligence MCP entries removed: {path}")


def sync_antigravity_mcp_config(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    backup_enabled: bool,
) -> None:
    """Keep Antigravity's global MCP manifest aligned with the Hub-only default."""
    json_mcp_merge(path, build_mcp_entries(install_dir, hub_python, serena, "antigravity", cfg), backup_enabled)
    if not bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        prune_direct_code_intelligence(path, serena, backup_enabled)


def sync_antigravity_config_json(path: Path, backup_enabled: bool) -> None:
    """Leave Antigravity permission and sandbox settings entirely user-controlled."""
    log(f"Antigravity permissions preserved; Hub adds no global grants: {path}")


def sync_antigravity_hooks_json(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> None:
    """Ensure Antigravity lifecycle hooks configure Local AI Hub enforcement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        backup(path, backup_enabled)
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
            if raw_text:
                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    raise RuntimeError(f"Antigravity hooks must be a JSON object: {path}")
                data = parsed
        except Exception as exc:
            raise RuntimeError(f"Cannot safely merge Antigravity hooks at {path}: {exc}") from exc

    python_exe = str(hub_python.resolve())
    if os.name == "nt":
        hook_script = path.parent / "local-ai-hook.cmd"
        batch_content = (
            "@echo off\r\n"
            f'"{python_exe}" -m local_ai_hub.antigravity_hook %*\r\n'
            "if %ERRORLEVEL% NEQ 0 (\r\n"
            '    echo {"decision": "allow"}\r\n'
            "    exit /b 0\r\n"
            ")\r\n"
        )
        script_content = batch_content
    else:
        hook_script = path.parent / "local-ai-hook.sh"
        sh_content = (
            "#!/bin/sh\n"
            f'"{python_exe}" -m local_ai_hub.antigravity_hook "$@" || echo \'{{"decision": "allow"}}\'\n'
            "exit 0\n"
        )
        script_content = sh_content
    current_script = None
    record_script = _ACTIVE_INSTALL_ROOT is None or not hook_script.exists()
    if _ACTIVE_INSTALL_ROOT is not None and hook_script.exists():
        try:
            current_script = hook_script.read_bytes()
        except (OSError, UnicodeDecodeError):
            log(f"WARNING: preserving unreadable hook script: {hook_script}")
            return
        try:
            assert_external_file_writable(_ACTIVE_INSTALL_ROOT, hook_script, current_script)
            record_script = True
        except ValueError:
            if current_script != script_content:
                log(f"WARNING: preserving hook script without matching ownership: {hook_script}")
                return
    hook_config: dict[str, Any] = {
        "enabled": True,
        "SessionStart": [
            {
                "type": "command",
                "command": "local-ai-hook.cmd SessionStart" if os.name == "nt" else "./local-ai-hook.sh SessionStart",
                "timeout": 10,
            }
        ],
        "PreToolUse": [
            {
                "matcher": "read_file|run_command",
                "hooks": [
                    {
                        "type": "command",
                        "command": "local-ai-hook.cmd PreToolUse" if os.name == "nt" else "./local-ai-hook.sh PreToolUse",
                        "timeout": 15,
                    }
                ],
            }
        ],
    }

    previous_hook = data.get("local-ai-hub")
    if _ACTIVE_INSTALL_ROOT is not None and "local-ai-hub" in data:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="", key="local-ai-hub", current_value=previous_hook,
            )
        except ValueError:
            if previous_hook != hook_config:
                log(f"WARNING: preserving unowned local-ai-hub hook configuration in {path}")
                return
            return
    data["local-ai-hub"] = hook_config
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if record_script:
            hook_script.write_bytes(script_content.encode("utf-8"))
            if os.name != "nt":
                try:
                    hook_script.chmod(0o755)
                except OSError:
                    pass
        record_external_json_key(
            _ACTIVE_INSTALL_ROOT, path, container="", key="local-ai-hub",
            preimage=previous_hook, postimage=hook_config,
        )
        if record_script:
            record_external_file(_ACTIVE_INSTALL_ROOT, hook_script, script_content)
    else:
        hook_script.write_bytes(script_content.encode("utf-8"))
        if os.name != "nt":
            try:
                hook_script.chmod(0o755)
            except OSError:
                pass
    log(f"Antigravity hooks configured: {path}")


def sync_claude_session_start_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install a reversible Claude SessionStart hook without replacing user hooks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Claude settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude settings must be a JSON object: {path}")
        data = parsed

    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Claude hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Claude SessionStart hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host claude'
    entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
    current = hooks.get("SessionStart")
    if isinstance(current, list) and entry in current:
        return True
    preimage: list[Any] | None = None
    if current is not None:
        if not isinstance(current, list):
            log(f"Claude SessionStart hooks preserved because the value is not a list: {path}")
            return False
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key="SessionStart",
                    current_value=current,
                )
            except ValueError:
                log(f"Claude SessionStart hooks preserved because the existing list is not Hub-owned: {path}")
                return False
        preimage = json.loads(json.dumps(current))
        hooks["SessionStart"] = [*current, entry]
    else:
        hooks["SessionStart"] = [entry]
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="SessionStart",
                preimage=preimage, postimage=hooks["SessionStart"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Claude SessionStart hook configured: {path}")
    return True


def sync_claude_subagent_start_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Claude subagent Laya context without replacing user hooks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Claude settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude settings must be a JSON object: {path}")
        data = parsed

    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Claude hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Claude SubagentStart hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host claude'
    entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
    event = "SubagentStart"
    current = hooks.get(event)
    if isinstance(current, list) and entry in current:
        return True
    preimage: list[Any] | None = None
    if current is not None:
        if not isinstance(current, list):
            log(f"Claude {event} hooks preserved because the value is not a list: {path}")
            return False
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event,
                    current_value=current,
                )
            except ValueError:
                log(f"Claude {event} hooks preserved because the existing list is not Hub-owned: {path}")
                return False
        preimage = json.loads(json.dumps(current))
    hooks[event] = [*(current or []), entry]
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event,
                preimage=preimage, postimage=hooks[event],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Claude {event} hook configured: {path}")
    return True


def claude_hub_plugin_enabled(settings_path: Path) -> bool:
    """Return whether Claude Code selects the bundled Hub plugin route."""
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect Claude settings {settings_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Claude settings must be an object: {settings_path}")
    enabled = data.get("enabledPlugins")
    return isinstance(enabled, dict) and enabled.get("local-ai-hub@local-ai-hub") is True


def global_hub_mcp_configured(mcp_path: Path) -> bool:
    """Detect a standalone Hub MCP entry in a provider JSON configuration."""
    if not mcp_path.is_file():
        return False
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect provider MCP config {mcp_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Provider MCP config must be an object: {mcp_path}")
    servers = data.get("mcpServers")
    return isinstance(servers, dict) and "local-ai" in servers


def claude_global_hub_mcp_configured(mcp_path: Path) -> bool:
    """Detect a standalone Claude Hub MCP entry that duplicates the plugin."""
    return global_hub_mcp_configured(mcp_path)


def global_hub_hooks_configured(settings_path: Path, host: str) -> bool:
    """Detect global host hooks that duplicate a provider plugin's hooks."""
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect provider settings {settings_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Provider settings must be an object: {settings_path}")
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list):
                continue
            for entry in entries:
                command = entry.get("command") if isinstance(entry, dict) else None
                if isinstance(command, str) and f"--host {host}" in command and (
                    "host_hooks.py" in command or "host_hooks" in command
                ):
                    return True
    return False


def cursor_global_hub_hooks_configured(hooks_path: Path) -> bool:
    """Detect Hub hooks in Cursor's event-to-command hook schema."""
    if not hooks_path.is_file():
        return False
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect Cursor hooks {hooks_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Cursor hooks must be an object: {hooks_path}")
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            command = entry.get("command") if isinstance(entry, dict) else None
            if isinstance(command, str) and "--host cursor" in command and "host_hooks" in command:
                return True
    return False


def claude_global_hub_hooks_configured(settings_path: Path) -> bool:
    """Detect global Claude hooks that duplicate the Claude plugin hooks."""
    return global_hub_hooks_configured(settings_path, "claude")


def gemini_cli_extension_installed(gemini_dir: Path) -> bool:
    """Detect the native Gemini CLI extension copied to its documented extension root."""
    manifest_path = gemini_dir / "extensions" / "local-ai-hub" / "gemini-extension.json"
    return _provider_manifest_named(manifest_path, "local-ai-hub")


def cursor_hub_plugin_installed(cursor_dir: Path) -> bool:
    """Detect Cursor's documented local plugin import path for Local AI Hub."""
    manifest_path = (
        cursor_dir / "plugins" / "local" / "local-ai-hub"
        / ".cursor-plugin" / "plugin.json"
    )
    return _provider_manifest_named(manifest_path, "local-ai-hub")


def copilot_hub_plugin_enabled(copilot_dir: Path, project_root: Path | None = None) -> bool:
    """Read Copilot CLI enabledPlugins across user and repository settings scopes."""
    paths = [copilot_dir / "settings.json"]
    if project_root is not None:
        paths.extend([
            project_root / ".github" / "copilot" / "settings.json",
            project_root / ".github" / "copilot" / "settings.local.json",
            project_root / ".claude" / "settings.json",
            project_root / ".claude" / "settings.local.json",
        ])
    merged: dict[str, Any] = {}
    for settings_path in paths:
        if not settings_path.is_file():
            continue
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot safely inspect Copilot settings {settings_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Copilot settings must be an object: {settings_path}")
        enabled = data.get("enabledPlugins")
        if enabled is None:
            continue
        if not isinstance(enabled, dict):
            raise RuntimeError(f"Copilot enabledPlugins must be an object: {settings_path}")
        for spec, state in enabled.items():
            if not isinstance(spec, str) or not isinstance(state, bool):
                continue
            if spec == "local-ai-hub" or spec.split("@", 1)[0] == "local-ai-hub":
                merged[spec] = state
    return any(merged.values())


def copilot_global_hub_hook_events(
    copilot_dir: Path, project_root: Path, *, exclude_paths: set[Path] | None = None,
) -> set[str]:
    """Return hook events that already call the Hub across Copilot CLI scopes."""
    paths = sorted((copilot_dir / "hooks").glob("*.json"))
    paths.extend([
        copilot_dir / "settings.json",
        project_root / ".github" / "copilot" / "settings.json",
        project_root / ".github" / "copilot" / "settings.local.json",
        project_root / ".claude" / "settings.json",
        project_root / ".claude" / "settings.local.json",
    ])
    paths.extend(sorted((project_root / ".github" / "hooks").glob("*.json")))

    def contains_hub_command(value: Any) -> bool:
        if isinstance(value, dict):
            for field in ("command", "bash", "powershell", "exec"):
                command = value.get(field)
                if isinstance(command, str) and "--host copilot" in command and "host_hooks" in command:
                    return True
            exec_value = value.get("exec")
            args = value.get("args")
            if isinstance(exec_value, str) and isinstance(args, list):
                command_line = " ".join([exec_value, *(item for item in args if isinstance(item, str))])
                if "--host copilot" in command_line and "host_hooks" in command_line:
                    return True
            return any(contains_hub_command(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_hub_command(item) for item in value)
        return False

    events: set[str] = set()
    seen_paths: set[str] = set()
    excluded = {
        os.path.normcase(os.path.abspath(os.fspath(path))) for path in (exclude_paths or set())
    }
    for path in paths:
        path_key = os.path.normcase(os.path.abspath(os.fspath(path)))
        if path_key in excluded or path_key in seen_paths or not path.is_file():
            continue
        seen_paths.add(path_key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot safely inspect Copilot hooks {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Copilot hooks must be an object: {path}")
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            continue
        events.update(
            event.casefold() for event, handlers in hooks.items()
            if isinstance(event, str) and contains_hub_command(handlers)
        )
    return events


def gemini_cli_extension_active(gemini_dir: Path, project_root: Path | None = None) -> bool:
    """Check extension presence and Gemini CLI's user/workspace disabled list."""
    if not gemini_cli_extension_installed(gemini_dir):
        return False
    settings_paths = [gemini_dir / "settings.json"]
    if project_root is not None:
        project_settings = project_root / ".gemini" / "settings.json"
        if project_settings.is_file():
            settings_paths = [project_settings]
    for settings_path in settings_paths:
        if not settings_path.is_file():
            continue
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot safely inspect Gemini CLI settings {settings_path}: {exc}") from exc
        if not isinstance(settings, dict):
            raise RuntimeError(f"Gemini CLI settings must be an object: {settings_path}")
        extensions = settings.get("extensions")
        disabled = extensions.get("disabled") if isinstance(extensions, dict) else None
        if isinstance(disabled, list) and "local-ai-hub" in disabled:
            return False
    return True


def antigravity_plugin_installed(gemini_dir: Path) -> bool:
    """Detect the native Antigravity plugin in its documented global plugin directory."""
    manifest_path = gemini_dir / "config" / "plugins" / "local-ai-hub" / "plugin.json"
    return _provider_manifest_named(manifest_path, "local-ai-hub")


def _provider_manifest_named(manifest_path: Path, expected_name: str) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect provider manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Provider manifest must be an object: {manifest_path}")
    return data.get("name") == expected_name


def sync_claude_pre_tool_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Claude's token-policy hook without deciding ordinary tool permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Claude settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude settings must be a JSON object: {path}")
        data = parsed
    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Claude hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Claude PreToolUse hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host claude'
    entry = {"matcher": "Bash|PowerShell|Read", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
    current = hooks.get("PreToolUse")
    if isinstance(current, list) and entry in current:
        return True
    if current is not None and not isinstance(current, list):
        log(f"Claude PreToolUse hooks preserved because the value is not a list: {path}")
        return False
    if isinstance(current, list) and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PreToolUse", current_value=current,
            )
        except ValueError:
            log(f"Claude PreToolUse hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if isinstance(current, list) else None
    hooks["PreToolUse"] = [*(current or []), entry]
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PreToolUse",
                preimage=preimage, postimage=hooks["PreToolUse"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Claude PreToolUse hook configured: {path}")
    return True


def sync_claude_permission_request_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Claude's deny-only permission guard; never grant a request."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Claude settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude settings must be a JSON object: {path}")
        data = parsed
    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Claude hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Claude PermissionRequest hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host claude'
    entry = {"matcher": "Bash|PowerShell|Read", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
    current = hooks.get("PermissionRequest")
    if isinstance(current, list) and entry in current:
        return True
    if current is not None and not isinstance(current, list):
        log(f"Claude PermissionRequest hooks preserved because the value is not a list: {path}")
        return False
    if isinstance(current, list) and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PermissionRequest", current_value=current,
            )
        except ValueError:
            log(f"Claude PermissionRequest hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if isinstance(current, list) else None
    hooks["PermissionRequest"] = [*(current or []), entry]
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PermissionRequest",
                preimage=preimage, postimage=hooks["PermissionRequest"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Claude PermissionRequest hook configured: {path}")
    return True


def sync_claude_post_tool_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Claude's post-edit static-check hook without changing permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Claude settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Claude settings must be a JSON object: {path}")
        data = parsed
    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Claude hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Claude PostToolUse hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host claude'
    entry = {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
    current = hooks.get("PostToolUse")
    if isinstance(current, list) and entry in current:
        return True
    if current is not None and not isinstance(current, list):
        log(f"Claude PostToolUse hooks preserved because the value is not a list: {path}")
        return False
    if isinstance(current, list) and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PostToolUse", current_value=current,
            )
        except ValueError:
            log(f"Claude PostToolUse hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if isinstance(current, list) else None
    hooks["PostToolUse"] = [*(current or []), entry]
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="PostToolUse",
                preimage=preimage, postimage=hooks["PostToolUse"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Claude PostToolUse hook configured: {path}")
    return True


def sync_gemini_cli_hooks(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install bounded Gemini CLI lifecycle/tool hooks without replacing user hooks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path_existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Gemini CLI settings {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Gemini CLI settings must be a JSON object: {path}")
        data = parsed

    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Gemini CLI hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Gemini CLI hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host gemini_cli'
    specs = {
        "SessionStart": {"hooks": [{"name": "local-ai-hub-session-start", "type": "command", "command": command, "timeout": 5000}]},
        "BeforeTool": {"matcher": "read_file|run_shell_command", "hooks": [{"name": "local-ai-hub-before-tool", "type": "command", "command": command, "timeout": 5000}]},
        "AfterTool": {"matcher": "write_file|replace", "hooks": [{"name": "local-ai-hub-after-tool", "type": "command", "command": command, "timeout": 5000}]},
    }
    changes: dict[str, tuple[list[Any] | None, list[Any]]] = {}
    for event, entry in specs.items():
        current = hooks.get(event)
        if isinstance(current, list) and entry in current:
            continue
        if current is not None and not isinstance(current, list):
            log(f"Gemini CLI {event} hooks preserved because the value is not a list: {path}")
            return False
        if isinstance(current, list) and _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event, current_value=current,
                )
            except ValueError:
                log(f"Gemini CLI {event} hooks preserved because the existing list is not Hub-owned: {path}")
                return False
        preimage = json.loads(json.dumps(current)) if isinstance(current, list) else None
        changes[event] = (preimage, [*(current or []), entry])
    if not changes:
        return True

    for event, (_preimage, postimage) in changes.items():
        hooks[event] = postimage
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            for event, (preimage, postimage) in changes.items():
                record_external_json_key(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event,
                    preimage=preimage, postimage=postimage,
                )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Gemini CLI hooks configured: {path}")
    return True


def sync_cursor_session_start_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install a reversible Cursor sessionStart hook when its target list is Hub-owned or absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path_existed = path.exists()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot parse Cursor hooks {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Cursor hooks must be a JSON object: {path}")
        data = parsed
    if data.get("version", 1) != 1:
        log(f"Cursor hooks preserved because the version is unsupported: {path}")
        return False
    hooks_existed = "hooks" in data
    version_existed = "version" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Cursor hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Cursor sessionStart hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host cursor'
    entry = {"command": command}
    current = hooks.get("sessionStart")
    if isinstance(current, list) and entry in current:
        return True
    preimage: list[Any] | None = None
    if current is not None:
        if not isinstance(current, list):
            log(f"Cursor sessionStart hooks preserved because the value is not a list: {path}")
            return False
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key="sessionStart",
                    current_value=current,
                )
            except ValueError:
                log(f"Cursor sessionStart hooks preserved because the existing list is not Hub-owned: {path}")
                return False
        preimage = json.loads(json.dumps(current))
        hooks["sessionStart"] = [*current, entry]
    else:
        hooks["sessionStart"] = [entry]
    backup(path, backup_enabled)
    data["version"] = 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if path_existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="sessionStart",
                preimage=preimage, postimage=hooks["sessionStart"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
            if not version_existed:
                record_external_json_key(
                    _ACTIVE_INSTALL_ROOT, path, container="", key="version",
                    preimage=None, postimage=1,
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Cursor sessionStart hook configured: {path}")
    return True


def sync_cursor_before_shell_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Add a managed Cursor shell policy hook; safe calls still require host approval."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if existed else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot parse Cursor hooks {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version", 1) != 1:
        log(f"Cursor hooks preserved because the version or root is unsupported: {path}")
        return False
    hooks_existed = "hooks" in data
    version_existed = "version" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Cursor hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Cursor shell hook source is unavailable: {hook_script}")
        return False
    entry = {
        "command": f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host cursor --event beforeShellExecution',
        "failClosed": True,
    }
    current = hooks.get("beforeShellExecution")
    if isinstance(current, list) and entry in current:
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key="beforeShellExecution",
                    current_value=current,
                )
            except ValueError:
                log(f"Cursor beforeShellExecution hook preserved because its ownership cannot be verified: {path}")
                return False
        return True
    if current is not None and not isinstance(current, list):
        log(f"Cursor beforeShellExecution hooks preserved because the value is not a list: {path}")
        return False
    if current is not None and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="beforeShellExecution",
                current_value=current,
            )
        except ValueError:
            log(f"Cursor beforeShellExecution hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if current is not None else None
    hooks["beforeShellExecution"] = [*(current or []), entry]
    data["version"] = 1
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="beforeShellExecution",
                preimage=preimage, postimage=hooks["beforeShellExecution"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
            if not version_existed:
                record_external_json_key(
                    _ACTIVE_INSTALL_ROOT, path, container="", key="version",
                    preimage=None, postimage=1,
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Cursor beforeShellExecution hook configured: {path}")
    return True


def sync_cursor_after_file_edit_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Add a non-blocking Cursor post-edit static-check hook."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if existed else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot parse Cursor hooks {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version", 1) != 1:
        log(f"Cursor hooks preserved because the version or root is unsupported: {path}")
        return False
    hooks_existed = "hooks" in data
    version_existed = "version" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Cursor hooks preserved because 'hooks' is not an object: {path}")
        return False
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Cursor afterFileEdit hook source is unavailable: {hook_script}")
        return False
    entry = {
        "command": f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host cursor --event afterFileEdit',
        "timeout": 5,
    }
    current = hooks.get("afterFileEdit")
    if isinstance(current, list) and entry in current:
        if _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key="afterFileEdit", current_value=current,
                )
            except ValueError:
                log(f"Cursor afterFileEdit hook preserved because its ownership cannot be verified: {path}")
                return False
        return True
    if current is not None and not isinstance(current, list):
        log(f"Cursor afterFileEdit hooks preserved because the value is not a list: {path}")
        return False
    if current is not None and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="afterFileEdit", current_value=current,
            )
        except ValueError:
            log(f"Cursor afterFileEdit hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if current is not None else None
    hooks["afterFileEdit"] = [*(current or []), entry]
    data["version"] = 1
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key="afterFileEdit",
                preimage=preimage, postimage=hooks["afterFileEdit"],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
            if not version_existed:
                record_external_json_key(
                    _ACTIVE_INSTALL_ROOT, path, container="", key="version", preimage=None, postimage=1,
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Cursor afterFileEdit hook configured: {path}")
    return True


def sync_windsurf_policy_hooks(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install reversible Windsurf policy pre-hooks and post-write checks."""
    hook_script = install_dir / "src" / "local_ai_hub" / "windsurf_hook.py"
    if not hook_script.is_file():
        log(f"Windsurf hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}"'
    specs = {
        "pre_run_command": {"command": command, "show_output": True},
        "pre_read_code": {"command": command, "show_output": True},
        "pre_mcp_tool_use": {"command": command, "show_output": True},
        "post_write_code": {"command": command, "show_output": True},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    data: dict[str, Any] = {}
    if existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            log(f"Windsurf hooks preserved because the file is invalid: {path} ({exc})")
            return False
        if not isinstance(parsed, dict):
            log(f"Windsurf hooks preserved because the root is not an object: {path}")
            return False
        data = parsed
    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Windsurf hooks preserved because 'hooks' is not an object: {path}")
        return False

    changes: dict[str, tuple[list[Any] | None, list[Any]]] = {}
    for event, entry in specs.items():
        current = hooks.get(event)
        if isinstance(current, list) and entry in current:
            continue
        if current is not None and not isinstance(current, list):
            log(f"Windsurf {event} hooks preserved because the value is not a list: {path}")
            return False
        if isinstance(current, list) and _ACTIVE_INSTALL_ROOT is not None:
            try:
                assert_external_json_key_writable(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event, current_value=current,
                )
            except ValueError:
                log(f"Windsurf {event} hooks preserved because the existing list is not Hub-owned: {path}")
                return False
        preimage = json.loads(json.dumps(current)) if isinstance(current, list) else None
        changes[event] = (preimage, [*(current or []), entry])
    if not changes:
        return True

    for event, (_preimage, postimage) in changes.items():
        hooks[event] = postimage
    backup(path, backup_enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if existed:
            for event, (preimage, postimage) in changes.items():
                record_external_json_key(
                    _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event,
                    preimage=preimage, postimage=postimage,
                )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Windsurf policy hooks configured: {path}")
    return True


def sync_copilot_tool_hooks(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
    *,
    skip_events: set[str] | None = None,
) -> bool:
    """Install reversible Copilot CLI tool hooks in its documented user hook directory."""
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Copilot hook source is unavailable: {hook_script}")
        return False
    command = f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host copilot'
    configured_hooks = {
        "preToolUse": [{
            "type": "command", "command": command + " --event preToolUse", "timeoutSec": 5,
        }],
        "postToolUse": [{
            "type": "command", "command": command + " --event postToolUse",
            "matcher": "^(create|edit)$", "timeoutSec": 5,
        }],
    }
    skipped = {event.casefold() for event in (skip_events or set())}
    configured_hooks = {
        event: handlers for event, handlers in configured_hooks.items()
        if event.casefold() not in skipped
    }
    if not configured_hooks:
        return True
    postimage = {"version": 1, "hooks": configured_hooks}
    serialized = json.dumps(postimage, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            current = path.read_bytes()
        except OSError as exc:
            log(f"Copilot hook preserved because it cannot be read: {path} ({exc})")
            return False
        try:
            assert_external_file_writable(install_dir, path, current)
        except ValueError:
            if current.decode("utf-8", errors="replace") == serialized:
                return True
            log(f"Copilot hook preserved because it is not Hub-owned: {path}")
            return False
    backup(path, backup_enabled)
    path.write_text(serialized, encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        # Text-mode newline translation differs by platform; ownership must hash
        # the exact bytes that uninstall will compare against.
        record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Copilot {' and '.join(configured_hooks)} hooks configured: {path}")
    return True


sync_copilot_pre_tool_hook = sync_copilot_tool_hooks


def devin_config_dir() -> Path:
    """Return Devin's documented user configuration directory."""
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "devin"
    return Path.home() / ".config" / "devin"


def devin_mcp_config_path() -> Path:
    return devin_config_dir() / "mcp_config.json"


def _sync_devin_tool_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
    *,
    event: str,
    matcher: str,
) -> bool:
    """Merge a managed Devin tool hook without replacing user configuration."""
    hook_script = install_dir / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    if not hook_script.is_file():
        log(f"Devin hook source is unavailable: {hook_script}")
        return False
    entry = {
        "matcher": matcher,
        "hooks": [{
            "type": "command",
            "command": f'"{hub_python.resolve()}" "{hook_script.resolve()}" --host devin --event {event}',
            "timeout": 5,
        }],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    data: dict[str, Any] = {}
    if existed:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            log(f"Devin hooks preserved because the config is invalid: {path} ({exc})")
            return False
        if not isinstance(parsed, dict):
            log(f"Devin hooks preserved because the config root is not an object: {path}")
            return False
        data = parsed
    hooks_existed = "hooks" in data
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        log(f"Devin hooks preserved because 'hooks' is not an object: {path}")
        return False
    current = hooks.get(event)
    if isinstance(current, list) and entry in current:
        return True
    if current is not None and not isinstance(current, list):
        log(f"Devin {event} hooks preserved because the value is not a list: {path}")
        return False
    if current is not None and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_json_key_writable(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event, current_value=current,
            )
        except ValueError:
            log(f"Devin {event} hooks preserved because the existing list is not Hub-owned: {path}")
            return False
    preimage = json.loads(json.dumps(current)) if current is not None else None
    hooks[event] = [*(current or []), entry]
    backup(path, backup_enabled)
    serialized = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(serialized, encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if existed:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container="hooks", key=event,
                preimage=preimage, postimage=hooks[event],
            )
            if not hooks_existed:
                record_external_json_container(
                    _ACTIVE_INSTALL_ROOT, path, container_path="hooks", container_type="object",
                )
        else:
            record_external_file(_ACTIVE_INSTALL_ROOT, path, path.read_bytes())
    log(f"Devin {event} hook configured: {path}")
    return True


def sync_devin_pre_tool_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Devin's native PreToolUse hook without changing host approvals."""
    return _sync_devin_tool_hook(
        path, install_dir, hub_python, backup_enabled, event="PreToolUse", matcher="exec",
    )


def sync_devin_post_tool_hook(
    path: Path,
    install_dir: Path,
    hub_python: Path,
    backup_enabled: bool,
) -> bool:
    """Install Devin's non-blocking static check after file editing tools."""
    return _sync_devin_tool_hook(
        path, install_dir, hub_python, backup_enabled,
        event="PostToolUse", matcher="^(edit|write|apply_patch)$",
    )


def _configure_gemini_instance_impl(
    gemini_dir: Path,
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    backup_enabled: bool,
    include_companion: bool,
    *,
    project_root: Path | None = None,
    agent_components: dict[str, Any] | None = None,
    manual_actions: list[str] | None = None,
) -> None:
    """Configure a single .gemini root (skills, instructions, MCP configs, permissions, schemas)."""
    gemini_dir.mkdir(parents=True, exist_ok=True)
    gemini_extension_enabled = gemini_cli_extension_active(gemini_dir, project_root)
    antigravity_plugin_present = antigravity_plugin_installed(gemini_dir)
    if (
        _agent_component_enabled(agent_components, "gemini", "skills")
        or _agent_component_enabled(agent_components, "antigravity", "skills", default=False)
    ):
        install_agent_skills(install_dir, gemini_dir / "skills", include_companion=include_companion)
        install_agent_skills(install_dir, gemini_dir / "config" / "skills", include_companion=include_companion)

    if include_companion and (
        _agent_component_enabled(agent_components, "gemini", "skills")
        or _agent_component_enabled(agent_components, "antigravity", "skills", default=False)
    ):
        try:
            install_superpowers_skills(gemini_dir / "skills", install_dir / ".local-ai-hub-superpowers" / ".local-ai-hub-skill-ownership.json")
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            log(f"ERROR: Antigravity Superpowers installation failed: {exc}")
            raise RuntimeError(f"Antigravity Superpowers installation failed: {exc}") from exc

    if (
        cfg.get("tool_policy", {}).get("install_global_instructions", True)
        and (
            _agent_component_enabled(agent_components, "gemini", "instructions")
            or _agent_component_enabled(agent_components, "antigravity", "instructions", default=False)
        )
    ):
        doc = gemini_dir / "GEMINI.md"
        try:
            merge_global_policy(doc, backup_enabled, cfg=cfg)
            merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        except ValueError as exc:
            if "external block has no ownership record" not in str(exc):
                raise
            owners = [
                label for provider, label in (("gemini", "Gemini"), ("antigravity", "Antigravity"))
                if _agent_component_enabled(agent_components, provider, "instructions", default=False)
            ]
            owner_label = " and ".join(owners) or "Gemini/Antigravity"
            action = f"{owner_label} instructions preserved: {doc} ({exc})"
            if manual_actions is not None:
                manual_actions.append(action)
            log(f"Manual agent setup required: {action}")
        if bool(cfg.get("setup", {}).get("install_antigravity_style_policy", False)):
            merge_antigravity_skill_policy(gemini_dir / "AGENTS.md", backup_enabled)
            merge_antigravity_skill_policy((project_root or Path.cwd()) / "AGENTS.md", backup_enabled)

    if _agent_component_enabled(agent_components, "gemini", "mcp"):
        gemini_settings = gemini_dir / "settings.json"
        if gemini_extension_enabled:
            if global_hub_mcp_configured(gemini_settings):
                action = f"Gemini CLI extension and standalone MCP both configured in {gemini_settings}; remove one route"
                if manual_actions is not None:
                    manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            json_mcp_merge(
                gemini_settings,
                build_mcp_entries(install_dir, hub_python, serena, "gemini", cfg),
                backup_enabled,
            )
    if _agent_component_enabled(agent_components, "antigravity", "mcp", default=False):
        antigravity_mcp = gemini_dir / "config" / "mcp_config.json"
        if antigravity_plugin_present:
            if global_hub_mcp_configured(antigravity_mcp):
                action = f"Antigravity plugin and standalone MCP both configured in {antigravity_mcp}; remove one route"
                if manual_actions is not None:
                    manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            sync_antigravity_mcp_config(
                antigravity_mcp, install_dir, hub_python, serena, cfg, backup_enabled,
            )
        sync_antigravity_config_json(
            gemini_dir / "config" / "config.json",
            backup_enabled,
        )

    if _agent_hooks_enabled(agent_components, "gemini"):
        gemini_settings = gemini_dir / "settings.json"
        if gemini_extension_enabled:
            if global_hub_hooks_configured(gemini_settings, "gemini_cli"):
                action = f"Gemini CLI extension and standalone hooks both configured in {gemini_settings}; remove one route"
                if manual_actions is not None:
                    manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        elif not sync_gemini_cli_hooks(gemini_settings, install_dir, hub_python, backup_enabled):
            action = f"Merge Gemini CLI lifecycle hooks manually in {gemini_settings}"
            if manual_actions is not None:
                manual_actions.append(action)
            log(f"Manual agent setup required: {action}")


def configure_gemini_instance(
    gemini_dir: Path,
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    backup_enabled: bool,
    include_companion: bool,
    *,
    project_root: Path | None = None,
    agent_components: dict[str, Any] | None = None,
    manual_actions: list[str] | None = None,
) -> None:
    global _ACTIVE_INSTALL_ROOT
    previous_root = _ACTIVE_INSTALL_ROOT
    candidate_root = Path(install_dir)
    if previous_root is None and candidate_root.is_dir():
        _ACTIVE_INSTALL_ROOT = candidate_root
        write_install_manifest(candidate_root)
    try:
        _configure_gemini_instance_impl(
            gemini_dir, install_dir, hub_python, serena, cfg, backup_enabled, include_companion,
            project_root=project_root, agent_components=agent_components,
            manual_actions=manual_actions,
        )
    finally:
        _ACTIVE_INSTALL_ROOT = previous_root
    antigravity_hooks = gemini_dir / "config" / "hooks.json"
    if _agent_hooks_enabled(agent_components, "antigravity", default=False):
        if antigravity_plugin_installed(gemini_dir):
            try:
                hook_data = json.loads(antigravity_hooks.read_text(encoding="utf-8")) if antigravity_hooks.is_file() else {}
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Cannot safely inspect Antigravity hooks {antigravity_hooks}: {exc}") from exc
            if isinstance(hook_data, dict) and "local-ai-hub" in hook_data:
                action = f"Antigravity plugin and global Hub hooks both configured in {antigravity_hooks}; remove one route"
                if manual_actions is not None:
                    manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            sync_antigravity_hooks_json(antigravity_hooks, install_dir, hub_python, backup_enabled)

    antigravity_mcp = gemini_dir / "antigravity" / "mcp" / "local-ai"
    if _agent_component_enabled(agent_components, "antigravity", "mcp", default=False) and not antigravity_plugin_installed(gemini_dir) and (
        antigravity_mcp.exists() or (gemini_dir / "antigravity").exists()
    ):
        antigravity_mcp.mkdir(parents=True, exist_ok=True)
        schemas_dir = install_dir / "generated" / "schemas"
        if schemas_dir.exists():
            for sfile in schemas_dir.glob("*.json"):
                shutil.copy2(sfile, antigravity_mcp / sfile.name)
        instructions_src = install_dir / "generated" / "instructions.md"
        if instructions_src.exists():
            shutil.copy2(instructions_src, antigravity_mcp / "instructions.md")


def vscode_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool) -> None:
    json_server_merge(path, servers, backup_enabled, container_key="servers", require_stdio_type=True)


def copilot_home() -> Path:
    """Return Copilot's configured home, respecting its documented override."""
    configured = os.environ.get("COPILOT_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".copilot"


def copilot_hook_path() -> Path:
    return copilot_home() / "hooks" / "local-ai-hub.json"


def opencode_config_dirs() -> list[Path]:
    """Return OpenCode's canonical user config root or its explicit override."""
    configured = os.environ.get("OPENCODE_HOME", "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [Path.home() / ".config" / "opencode"]

def toml_quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def preserve_isolated_hub_args(name: str, existing: Any, entry: dict[str, Any]) -> dict[str, Any]:
    """Retain an existing isolated Python launch without carrying stale arguments."""
    if (
        name == "local-ai"
        and isinstance(existing, dict)
        and existing.get("args") == ["-I", "-m", "local_ai_hub.mcp_server"]
        and entry.get("args") == ["-m", "local_ai_hub.mcp_server"]
    ):
        return {**entry, "args": ["-I", "-m", "local_ai_hub.mcp_server"]}
    return entry


def codex_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool, *, startup_timeout: int = 60, tool_timeout: int = 900) -> None:
    for entry in servers.values():
        if "url" in entry:
            if "command" in entry or "args" in entry or "env" in entry:
                raise ValueError("HTTP MCP entries cannot include stdio options")
            if not isinstance(entry["url"], str) or not entry["url"]:
                raise ValueError("HTTP MCP URL must be a non-empty string")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    marker_pattern = re.compile(rf"{re.escape(MARKER_BEGIN)}.*?{re.escape(MARKER_END)}", re.DOTALL)
    managed_matches = list(marker_pattern.finditer(text))
    if len(managed_matches) > 1:
        raise RuntimeError(f"multiple Codex Local AI Hub blocks found in {path}")
    managed = managed_matches[0] if managed_matches else None
    preimage = managed.group(0) if managed else None
    owner_marker = {"begin": MARKER_BEGIN, "end": MARKER_END}
    if preimage is not None:
        _assert_or_adopt_external_block(path, owner_marker, preimage)
    backup(path, backup_enabled)
    existing_servers: dict[str, Any] = {}
    if managed:
        try:
            parsed_servers = tomllib.loads(managed.group()).get("mcp_servers", {})
            if isinstance(parsed_servers, dict):
                existing_servers = parsed_servers
        except tomllib.TOMLDecodeError:
            pass
    text = re.sub(rf"\n?{re.escape(MARKER_BEGIN)}.*?{re.escape(MARKER_END)}\n?", "\n", text, flags=re.DOTALL).rstrip() + "\n"
    blocks: list[str] = [MARKER_BEGIN]
    for name, entry in servers.items():
        entry = preserve_isolated_hub_args(name, existing_servers.get(name), entry)
        # Never overwrite an explicitly user-managed block.
        if re.search(rf"(?m)^\[mcp_servers\.{re.escape(name)}\]\s*$", text):
            log(f"Codex MCP '{name}' exists outside the managed block; leaving it unchanged")
            continue
        blocks.append(f"[mcp_servers.{name}]")
        if "url" in entry:
            blocks.append(f"url = {toml_quote(entry['url'])}")
        else:
            blocks.extend([f"command = {toml_quote(entry['command'])}",
                           "args = [" + ", ".join(toml_quote(x) for x in entry.get("args", [])) + "]"])
        settings: dict[str, Any] = {
            "enabled": True, "required": False,
            "startup_timeout_sec": max(10, int(startup_timeout)),
            "tool_timeout_sec": max(60, int(tool_timeout)),
            "default_tools_approval_mode": "prompt",
        }
        previous = existing_servers.get(name)
        if "url" in entry and isinstance(previous, dict):
            for key, expected in (("enabled", bool), ("required", bool),
                                  ("startup_timeout_sec", int), ("tool_timeout_sec", int),
                                  ("default_tools_approval_mode", str)):
                value = previous.get(key)
                if type(value) is expected and (expected is not int or value > 0):
                    settings[key] = value
        for key, value in settings.items():
            literal = str(value).lower() if type(value) is bool else toml_quote(value) if isinstance(value, str) else str(value)
            blocks.append(f"{key} = {literal}")
        if entry.get("cwd"):
            blocks.append(f"cwd = {toml_quote(entry['cwd'])}")
        env = entry.get("env") or {}
        if env:
            blocks.extend(["", f"[mcp_servers.{name}.env]"])
            blocks.extend(f"{key} = {toml_quote(value)}" for key, value in env.items())
        blocks.append("")
    blocks.append(MARKER_END)
    written_block = "\n".join(blocks)
    path.write_text(text + written_block + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        record_external_block(
            _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=owner_marker,
            preimage=preimage, postimage=written_block,
        )
    log(f"Codex MCP config updated: {path}")


def codex_hub_plugin_enabled(path: Path) -> bool:
    """Return whether Codex config selects the bundled Hub plugin route."""
    if not path.is_file():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Cannot safely inspect Codex config {path}: {exc}") from exc
    plugins = data.get("plugins")
    plugin = plugins.get("local-ai-hub@local-ai-hub") if isinstance(plugins, dict) else None
    return isinstance(plugin, dict) and plugin.get("enabled") is True


def merge_global_policy(path: Path, backup_enabled: bool, cfg: dict[str, Any] | None = None) -> None:
    policy = generate_global_policy(cfg or {})
    _merge_owned_text_block(path, policy, GLOBAL_POLICY_BEGIN, GLOBAL_POLICY_END, backup_enabled)
    log(f"Tool-first policy installed: {path}")


def merge_token_economy_policy(path: Path, backup_enabled: bool, cfg: dict[str, Any] | None = None) -> None:
    policy = generate_token_economy_policy(cfg or {})
    _merge_owned_text_block(path, policy, TOKEN_ECONOMY_POLICY_BEGIN, TOKEN_ECONOMY_POLICY_END, backup_enabled)
    log(f"Token economy policy installed: {path}")


def _merge_owned_text_block(path: Path, block: str, begin: str, end: str, backup_enabled: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        raise RuntimeError(f"multiple Local AI Hub blocks found in {path}")
    preimage = matches[0].group(0) if matches else None
    marker = {"begin": begin, "end": end}
    if preimage is not None:
        _assert_or_adopt_external_block(path, marker, preimage)
    updated = pattern.sub(lambda _match: block, text) if preimage is not None else (
        text + ("" if not text or text.endswith("\n") else "\n") + "\n" + block + "\n"
    )
    if updated == text:
        return
    backup(path, backup_enabled)
    path.write_bytes(updated.encode("utf-8"))
    if _ACTIVE_INSTALL_ROOT is not None:
        record_external_block(
            _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=marker,
            preimage=preimage, postimage=block,
        )


def ensure_cursor_rule_frontmatter(path: Path, backup_enabled: bool) -> bool:
    """Ensure the Hub's dedicated Cursor rule is always active without losing its body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and GLOBAL_POLICY_BEGIN not in text and TOKEN_ECONOMY_POLICY_BEGIN not in text:
        return False
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    owner_marker = {"begin": "---\n", "end": "\n---"}
    preimage = match.group(0).rstrip("\r\n") if match else None
    if preimage is not None and _ACTIVE_INSTALL_ROOT is not None:
        try:
            assert_external_block_writable(_ACTIVE_INSTALL_ROOT, path, owner_marker=owner_marker, current_block=preimage)
        except ValueError:
            log(f"Cursor frontmatter ownership is unclear; preserving existing metadata: {path}")
            return False
    if match:
        metadata = match.group(1)
        if re.search(r"(?m)^alwaysApply\s*:", metadata):
            metadata = re.sub(r"(?m)^alwaysApply\s*:.*$", "alwaysApply: true", metadata)
        else:
            metadata += "\nalwaysApply: true"
        if not re.search(r"(?m)^description\s*:", metadata):
            metadata += "\ndescription: Local AI Hub tool policy"
        updated = f"---\n{metadata}\n---\n" + text[match.end():]
    else:
        updated = (
            "---\ndescription: Local AI Hub tool policy\nalwaysApply: true\n---\n\n"
            + text
        )
    if updated != text:
        if path.exists():
            backup(path, backup_enabled)
        path.write_text(updated, encoding="utf-8")
        if _ACTIVE_INSTALL_ROOT is not None:
            updated_match = re.match(r"\A---\r?\n.*?\r?\n---", updated, re.DOTALL)
            if updated_match is not None:
                record_external_block(
                    _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=owner_marker,
                    preimage=preimage, postimage=updated_match.group(0),
                )
        log(f"Cursor Local AI Hub rule enabled: {path}")
    return True


def merge_windsurf_global_policy(path: Path, install_dir: Path, backup_enabled: bool) -> str | None:
    """Install concise global guidance within Windsurf's documented rule-size limit."""
    begin = "<!-- BEGIN LOCAL AI HUB WINDSURF POLICY -->"
    end = "<!-- END LOCAL AI HUB WINDSURF POLICY -->"
    policy = (
        f"{begin}\n# Local AI Hub\n"
        "Use the Local AI Hub MCP and `local-ai-orchestrator` skill for repository work. "
        "Use only actions exposed by the active MCP schema; deterministic/indexed evidence "
        "is authoritative for repository facts. Use native commands for builds and tests. "
        f"Read `{(install_dir / 'generated' / 'agent-policy.md').as_posix()}` for the full configured policy.\n{end}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        return f"Multiple Local AI Hub Windsurf blocks found; existing rule file was preserved: {path}"
    preimage = matches[0].group(0) if matches else None
    marker = {"begin": begin, "end": end}
    if preimage is not None:
        _assert_or_adopt_external_block(path, marker, preimage)
    updated = pattern.sub(lambda _match: policy, text) if preimage is not None else (
        text + ("" if not text or text.endswith("\n") else "\n") + "\n" + policy + "\n"
    )
    if len(updated) > 6000:
        return (
            "Windsurf global rules exceed the 6,000-character limit; its existing rule file was preserved. "
            f"Manually add the Local AI Hub policy to {path} or shorten existing rules."
        )
    if updated != text:
        backup(path, backup_enabled)
        path.write_text(updated, encoding="utf-8")
        if _ACTIVE_INSTALL_ROOT is not None:
            record_external_block(
                _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=marker,
                preimage=preimage, postimage=policy,
            )
        log(f"Windsurf Local AI Hub rule installed: {path}")
    return None


def merge_autosetup_policy(path: Path, backup_enabled: bool, skills_dir: Path) -> None:
    policy = generate_autosetup_policy(skills_dir)
    _merge_owned_text_block(path, policy, AUTOSETUP_BEGIN, AUTOSETUP_END, backup_enabled)
    log(f"Autosetup policy installed: {path}")


def install_tool_env(install_dir: Path, name: str, package: str, executables: list[str]) -> Path | None:
    venv = install_dir / "tool-envs" / name
    try:
        python = ensure_venv(venv)
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", package], timeout=1800)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log(f"WARNING: {name} install failed ({type(exc).__name__}); Local AI Hub will continue with built-in code intelligence")
        return None
    for executable in executables:
        candidate = venv_executable(venv, executable)
        if candidate.exists():
            return candidate
    log(f"WARNING: {name} package installed but no supported executable was found")
    return None


def install_token_economy_suite(
    install_dir: Path, hub_python: Path, *, allow_external_tools: bool = True
) -> dict[str, Any]:
    """Install token-economy python dependencies, CLI wrapper scripts, and probe external CLI tools."""
    req_file = install_dir / "requirements-token-economy.txt"
    dependencies_ok = req_file.is_file() and install_requirements(hub_python, req_file, optional=True)

    scripts_dir = install_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    if scripts_dir.is_dir():
        py_exe = str(hub_python)
        if os.name == "nt":
            (scripts_dir / "tokcount.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy tokcount %*\n', encoding="utf-8")
            (scripts_dir / "trim-run.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy trim_run %*\n', encoding="utf-8")
            (scripts_dir / "repo-map.cmd").write_text(f'@echo off\n"{py_exe}" -m local_ai_hub.token_economy repo_map %*\n', encoding="utf-8")
        else:
            for tool_name in ["tokcount", "trim-run", "repo-map"]:
                sh_file = scripts_dir / tool_name
                subcmd = tool_name.replace("-", "_")
                sh_file.write_text(f'#!/bin/sh\nexec "{py_exe}" -m local_ai_hub.token_economy {subcmd} "$@"\n', encoding="utf-8")
                try:
                    sh_file.chmod(0o755)
                except Exception:
                    pass
        persist_token_economy_path(scripts_dir)

    wrapper_names = ["tokcount", "trim-run", "repo-map"]
    if os.name == "nt":
        wrapper_names = [f"{name}.cmd" for name in wrapper_names]
    wrappers_ok = scripts_dir.is_dir() and all((scripts_dir / name).is_file() for name in wrapper_names)
    status: dict[str, Any] = {
        "dependencies": "installed" if dependencies_ok else "failed_or_missing",
        "wrappers": "installed" if wrappers_ok else "failed_or_missing",
        "external_tools": {},
    }

    if not allow_external_tools:
        status["external_tools"] = {"status": "not_requested"}
        return status

    # Probe and attempt install for external CLI tools
    if not shutil.which("rg"):
        log("ripgrep (rg) not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "BurntSushi.ripgrep.MSVC", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "ripgrep"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "ripgrep"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional ripgrep install skipped: {exc}")

    if not shutil.which("fd") and not shutil.which("fdfind"):
        log("fd not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "sharkdp.fd", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "fd"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "fd-find"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional fd install skipped: {exc}")

    if not shutil.which("ast-grep") and not shutil.which("sg"):
        if shutil.which("npm"):
            log("ast-grep not found in PATH; installing via npm...")
            try:
                run(["npm", "install", "-g", "@ast-grep/cli"], check=False, timeout=300)
            except Exception as exc:
                log(f"Optional ast-grep install skipped: {exc}")

    if not shutil.which("repomix"):
        if shutil.which("npm"):
            log("repomix not found in PATH; installing via npm...")
            try:
                run(["npm", "install", "-g", "repomix"], check=False, timeout=300)
            except Exception as exc:
                log(f"Optional repomix install skipped: {exc}")

    if not shutil.which("jq"):
        log("jq not found in PATH; attempting install...")
        try:
            if os.name == "nt" and shutil.which("winget"):
                run(["winget", "install", "--id", "jqlang.jq", "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent"], check=False, timeout=300)
            elif sys.platform == "darwin" and shutil.which("brew"):
                run(["brew", "install", "jq"], check=False, timeout=300)
            elif sys.platform.startswith("linux") and shutil.which("apt-get"):
                run(["sudo", "apt-get", "install", "-y", "jq"], check=False, timeout=300)
        except Exception as exc:
            log(f"Optional jq install skipped: {exc}")

    command_paths = {
        "ripgrep": shutil.which("rg"),
        "fd": shutil.which("fd") or shutil.which("fdfind"),
        "ast_grep": shutil.which("ast-grep") or shutil.which("sg"),
        "repomix": shutil.which("repomix"),
        "jq": shutil.which("jq"),
    }
    status["external_tools"] = {
        name: {"status": "available" if path else "not_detected_after_install", "path": path}
        for name, path in command_paths.items()
    }
    return status


def _merge_path_entry(path_value: str, entry: Path, *, windows: bool) -> str:
    """Append an entry to PATH without duplicates, preserving existing entries."""
    separator = ";" if windows else os.pathsep
    candidate = os.path.normcase(os.path.normpath(str(entry))).casefold() if windows else os.path.normpath(str(entry))
    parts = [part.strip().strip('"') for part in path_value.split(separator) if part.strip()]
    for part in parts:
        current = os.path.normcase(os.path.normpath(os.path.expandvars(part))).casefold() if windows else os.path.normpath(part)
        if current == candidate:
            return path_value
    return separator.join([*parts, str(entry)])


def persist_token_economy_path(
    scripts_dir: Path,
    *,
    home: Path | None = None,
    windows: bool | None = None,
    shell: str | None = None,
) -> Path | None:
    """Expose installed token-economy CLI wrappers to future user shells."""
    scripts_dir = scripts_dir.expanduser().resolve()
    home = (home or Path.home()).expanduser()
    windows = os.name == "nt" if windows is None else windows
    if windows:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, value_type = "", winreg.REG_EXPAND_SZ
            updated = _merge_path_entry(current, scripts_dir, windows=True)
            if updated != current:
                winreg.SetValueEx(key, "Path", 0, value_type, updated)
                try:
                    import ctypes

                    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
                except Exception:
                    pass
        log(f"Token Economy CLI PATH registered for user: {scripts_dir} (open a new terminal)")
        return None

    shell_name = Path(shell or os.environ.get("SHELL", "")).name.lower()
    if shell_name == "fish":
        profile = home / ".config" / "fish" / "conf.d" / "local-ai-hub-token-tools.fish"
        line = f"set -gx PATH {shlex.quote(str(scripts_dir))} $PATH"
    else:
        profile = home / (".zprofile" if shell_name == "zsh" else ".profile")
        line = f"export PATH={shlex.quote(str(scripts_dir))}:$PATH"

    begin = "# BEGIN LOCAL AI HUB TOKEN TOOLS PATH"
    end = "# END LOCAL AI HUB TOKEN TOOLS PATH"
    block = f"{begin}\n{line}\n{end}"
    profile.parent.mkdir(parents=True, exist_ok=True)
    current = profile.read_text(encoding="utf-8") if profile.exists() else ""
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    updated = pattern.sub(lambda _match: block, current) if pattern.search(current) else f"{current.rstrip()}\n\n{block}\n"
    if updated != current:
        profile.write_text(updated, encoding="utf-8")
    log(f"Token Economy CLI PATH registered in {profile} (open a new terminal)")
    return profile


def build_mcp_entries(install_dir: Path, hub_python: Path, serena: Path | None, agent: str, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {
        "local-ai": {
            "command": str(hub_python),
            "args": ["-m", "local_ai_hub.mcp_server"],
            "cwd": str(install_dir),
            "env": {
                "LOCAL_AI_AGENT": agent,
                "LOCAL_AI_AGENT_PROFILE": agent,
                "LOCAL_AI_CONFIG": str(install_dir / "config.toml"),
                "PYTHONPATH": str(install_dir / "src"),
            },
        }
    }
    if agent == "gemini":
        entries["local-ai"]["force_all_tools_eager"] = True
        entries["local-ai"]["skip_tool_name_prefix"] = True
    if not bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        return entries
    # Optional escape hatch. Default installations expose only Local AI Hub to save schemas/tokens.
    if serena is not None and cfg.get("code_intelligence", {}).get("serena_enabled", True):
        context = {"codex": "codex", "claude": "claude-code", "gemini": "gemini"}.get(agent, "ide-assistant")
        entries["serena"] = {"command": str(serena), "args": ["start-mcp-server", "--context", context, "--project-from-cwd", "--open-web-dashboard", "false"]}
    return entries


def find_ollama_executable() -> str | None:
    executable = shutil.which("ollama")
    if executable is None and os.name == "nt":
        candidate = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"))
        if candidate.exists():
            executable = str(candidate)
    return executable


def try_install_ollama() -> str | None:
    existing = find_ollama_executable()
    if existing:
        return existing
    log("Ollama is not installed; attempting a platform package installation...")
    try:
        if os.name == "nt" and shutil.which("winget"):
            run(["winget", "install", "--id", "Ollama.Ollama", "--exact", "--accept-source-agreements", "--accept-package-agreements", "--silent"], check=False, timeout=900)
        elif sys.platform == "darwin" and shutil.which("brew"):
            run(["brew", "install", "ollama"], check=False, timeout=900)
        elif sys.platform.startswith("linux"):
            log("Linux auto-install is disabled: install Ollama from a trusted package source, then rerun setup.")
    except Exception as exc:
        log(f"WARNING: Ollama installation attempt failed: {exc}")
    return find_ollama_executable()


def ollama_setup_required(cfg: dict[str, Any]) -> bool:
    """Return whether setup should install, start, or pull Ollama resources."""
    ollama = cfg.get("ollama", {})
    server = cfg.get("server", {})
    llama_cpp = cfg.get("llama_cpp", {})
    if not isinstance(ollama, dict):
        ollama = {}
    if not isinstance(server, dict):
        server = {}
    if not isinstance(llama_cpp, dict):
        llama_cpp = {}
    # Ollama is explicit opt-in.  A llama.cpp route never implicitly installs
    # Ollama or downloads Ollama models as an incidental setup side effect.
    return (
        bool(ollama.get("enabled", False))
        and bool(server.get("auto_start_ollama", False))
        and bool(llama_cpp.get("fallback_to_ollama", False))
    )


def ensure_ollama_for_setup(cfg: dict[str, Any], install_dir: Path, *, allow_install: bool) -> bool:
    if not ollama_setup_required(cfg):
        log("Skipping Ollama setup: Ollama is disabled or not explicitly opted in; no package/model changes requested.")
        return True
    executable = find_ollama_executable() or (try_install_ollama() if allow_install else None)
    if not executable:
        log("WARNING: Ollama is unavailable. Install it later or set server.auto_start_ollama=false for deterministic-only use.")
        return False
    src = install_dir / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from local_ai_hub.ollama import OllamaRuntime
        runtime = OllamaRuntime(cfg)
        return runtime.ensure_running()
    except Exception as exc:
        log(f"WARNING: Ollama startup check failed: {exc}")
        return False


def ensure_llama_cpp_for_setup(cfg: dict[str, Any]) -> bool:
    """Install and start llama.cpp only when it is the explicit provider."""
    if not llama_cpp_managed_selected(cfg):
        log("Skipping managed llama.cpp setup: Ollama or external/disabled llama.cpp is selected.")
        return True
    runtime = LlamaCppManagedRuntime(cfg)
    try:
        if not runtime.ensure_running():
            detail = str(runtime.status().get("last_error", "") or "llama-server did not become healthy after GPU and CPU startup attempts")
            raise RuntimeError(detail)
        status = runtime.status()
        log(f"Managed llama.cpp is ready at {status['url']} ({status['mode'] or 'device mode unknown'}).")
        return True
    except Exception as exc:
        raise RuntimeError(f"Managed llama.cpp setup failed: {exc}") from exc


def pull_ollama_models(cfg: dict[str, Any]) -> dict[str, Any]:
    models: list[str] = []
    model_cfg = cfg.get("models", {})
    for key in ["background_code", "fast_code", "heavy_code", "reasoning", "general", "opencode"]:
        model = str(model_cfg.get(key, "") or "")
        if model and model not in models:
            models.append(model)
    if bool(cfg.get("features", {}).get("vision", True)):
        model = str(model_cfg.get("vision", "") or "")
        if model and model not in models:
            models.append(model)
    if bool(cfg.get("ollama_subagents", {}).get("enabled", True)):
        profiles = cfg.get("ollama_subagents", {}).get("profiles", {})
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if not isinstance(profile, dict):
                    continue
                model = str(profile.get("model", "") or "")
                if model and model not in models:
                    models.append(model)
    if model_cfg.get("embedding_backend") == "ollama":
        model = str(model_cfg.get("embedding", "") or "")
        if model and model not in models:
            models.append(model)
    prep_model = str(cfg.get("preprocessing", {}).get("model", "") or "")
    if prep_model and prep_model not in models:
        models.append(prep_model)
    if not ollama_setup_required(cfg):
        return {"status": "not_selected", "requested": [], "ready": [], "skipped": [], "unavailable": []}
    if not cfg.get("features", {}).get("pull_models_during_setup", True):
        return {"status": "skipped", "requested": [], "ready": [], "skipped": models, "unavailable": []}
    ollama = find_ollama_executable()
    if not ollama:
        log("WARNING: Ollama model downloads requested but the Ollama executable is unavailable.")
        return {"status": "unavailable", "requested": models, "ready": [], "skipped": [], "unavailable": models}
    ready: list[str] = []
    unavailable: list[str] = []
    for model in models:
        try:
            from local_ai_hub.model_distribution import DISTRIBUTION_REGISTRY, ensure_distribution_model
            if model in DISTRIBUTION_REGISTRY:
                dist_res = ensure_distribution_model(model, root=Path.cwd(), allow_download=True)
                if dist_res.get("status") in {"ready", "registered"}:
                    ready.append(model)
                    continue
                else:
                    log(f"WARNING: distribution model provisioning failed: {model}: {dist_res.get('error')}")
            result = run([ollama, "pull", model], check=False, timeout=1800)
            if result.returncode == 0:
                ready.append(model)
            else:
                unavailable.append(model)
                log(f"WARNING: model pull failed (exit={result.returncode}): {model}")
        except Exception as exc:
            unavailable.append(model)
            log(f"WARNING: model pull did not complete: {model}: {exc}")
    return {
        "status": "unavailable" if unavailable and not ready else "partial" if unavailable else "ready",
        "requested": models,
        "ready": ready,
        "skipped": [],
        "unavailable": unavailable,
    }


def write_generated_agent_manifests(install_dir: Path, hub_python: Path, serena: Path | None, cfg: dict[str, Any]) -> None:
    write_all_generated(cfg, install_dir, hub_python, serena)
    log(f"Dynamic skill, manifests, and schemas generated: {install_dir / 'generated'}")


def build_codex_mcp_entries(install_dir: Path, hub_python: Path, serena: Path | None, cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = build_mcp_entries(install_dir, hub_python, serena, "codex", cfg)
    http_cfg = cfg.get("mcp_http", {})
    if not isinstance(http_cfg, dict) or http_cfg.get("enabled") is not True:
        return entries
    port = http_cfg.get("port", 11436)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("HTTP MCP port must be an integer between 1 and 65535")
    if "local-ai" in entries:
        entries["local-ai"] = {"url": f"http://127.0.0.1:{port}/mcp"}
    return entries


def _http_mcp_ready(url: str) -> bool:
    """Perform a bounded MCP handshake before switching Codex to HTTP."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "local-ai-setup", "version": "1"},
    }}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    session = None
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with opener.open(req, timeout=2) as response:
            session = response.headers.get("Mcp-Session-Id")
            result = json.loads(response.read(65536))
        return (isinstance(result, dict) and result.get("id") == 1
                and isinstance(result.get("result"), dict)
                and isinstance(result["result"].get("protocolVersion"), str)
                and isinstance(result["result"].get("serverInfo"), dict)
                and result["result"]["serverInfo"].get("name") == "Local AI Hub (compact)"
                and bool(session))
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if session:
            try:
                req = urllib.request.Request(url, headers={"Mcp-Session-Id": session}, method="DELETE")
                with opener.open(req, timeout=2):
                    pass
            except OSError:
                pass


def _agent_component_enabled(
    selections: dict[str, Any] | None, agent: str, component: str, *, default: bool = True
) -> bool:
    if selections is None:
        return default
    return bool(selections.get(f"agent_{agent}_{component}", default))


def _agent_hooks_enabled(
    selections: dict[str, Any] | None, agent: str, *, default: bool = True
) -> bool:
    if selections is None:
        return default
    return bool(selections.get(f"agent_{agent}_hooks", default))


def configure_cursor_global_routes(
    cursor_dir: Path,
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    backup_enabled: bool,
    agent_components: dict[str, Any] | None,
    manual_actions: list[str],
) -> None:
    """Use Cursor's native plugin route when present; avoid duplicate global MCP/hooks."""
    plugin_present = cursor_hub_plugin_installed(cursor_dir)
    mcp_path = cursor_dir / "mcp.json"
    hooks_path = cursor_dir / "hooks.json"
    if _agent_component_enabled(agent_components, "cursor", "mcp"):
        if plugin_present:
            if global_hub_mcp_configured(mcp_path):
                action = f"Cursor local Hub plugin is installed; standalone Hub MCP remains in {mcp_path}. Remove one route after reviewing the current file"
                manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            json_mcp_merge(
                mcp_path,
                build_mcp_entries(install_dir, hub_python, serena, "cursor", cfg),
                backup_enabled,
            )
    if _agent_hooks_enabled(agent_components, "cursor"):
        if plugin_present:
            if cursor_global_hub_hooks_configured(hooks_path):
                action = f"Cursor local Hub plugin is installed; global Hub hooks remain in {hooks_path}. Remove duplicate hooks after reviewing the current file"
                manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            session_ok = sync_cursor_session_start_hook(
                hooks_path, install_dir, hub_python, backup_enabled,
            )
            shell_ok = sync_cursor_before_shell_hook(
                hooks_path, install_dir, hub_python, backup_enabled,
            )
            edit_ok = sync_cursor_after_file_edit_hook(
                hooks_path, install_dir, hub_python, backup_enabled,
            )
            if not session_ok or not shell_ok or not edit_ok:
                manual_actions.append(
                    f"Cursor session/shell/post-edit hooks not fully installed; review and merge manually: {hooks_path}"
                )


def configure_copilot_global_routes(
    copilot_dir: Path,
    project_root: Path,
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    backup_enabled: bool,
    agent_components: dict[str, Any] | None,
    manual_actions: list[str],
) -> None:
    """Prefer an enabled Copilot plugin and avoid duplicate user-level MCP/hooks."""
    plugin_enabled = copilot_hub_plugin_enabled(copilot_dir, project_root)
    mcp_path = copilot_dir / "mcp-config.json"
    hooks_path = copilot_dir / "hooks" / "local-ai-hub.json"
    if _agent_component_enabled(agent_components, "copilot", "mcp"):
        if plugin_enabled:
            if global_hub_mcp_configured(mcp_path):
                action = f"Copilot Hub plugin is enabled; standalone Hub MCP remains in {mcp_path}. Remove one route after reviewing the current file"
                manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        else:
            json_mcp_merge(
                mcp_path,
                build_mcp_entries(install_dir, hub_python, serena, "copilot", cfg),
                backup_enabled,
            )
    if _agent_hooks_enabled(agent_components, "copilot"):
        existing_events = copilot_global_hub_hook_events(copilot_dir, project_root)
        external_tool_events = copilot_global_hub_hook_events(
            copilot_dir, project_root, exclude_paths={hooks_path},
        )
        if plugin_enabled and "sessionstart" in existing_events:
            action = (
                "Copilot Hub plugin is enabled; global Hub SessionStart hooks remain in another scope. "
                "Review and remove duplicate hooks manually"
            )
            manual_actions.append(action)
            log(f"Manual agent setup required: {action}")
        duplicate_tool_events = external_tool_events & {"pretooluse", "posttooluse"}
        if duplicate_tool_events:
            events = ", ".join(sorted(duplicate_tool_events))
            action = f"Copilot Hub tool hooks already configured for {events}; setup will not add duplicate events"
            manual_actions.append(action)
            log(f"Manual agent setup required: {action}")
        if not sync_copilot_tool_hooks(
            hooks_path, install_dir, hub_python, backup_enabled, skip_events=duplicate_tool_events,
        ):
            manual_actions.append(
                f"Copilot tool hooks not installed; review and merge manually: {hooks_path}"
            )


def provider_integration_status(
    agent_names: tuple[str, ...],
    selected_agents: dict[str, bool],
    component_installation: dict[str, dict[str, str]],
    hook_installation: dict[str, str],
    plugin_installation: dict[str, str],
    *,
    batch_error: str | None = None,
    manual_actions_by_provider: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Report setup state separately from host trust, connection, and runtime proof."""
    report: dict[str, dict[str, Any]] = {}
    for name in agent_names:
        selected = bool(selected_agents.get(name, False))
        component_states = component_installation.get(name, {})
        configured_states = [
            *component_states.values(),
            hook_installation.get(name, "not_supported_by_hub_setup"),
            plugin_installation.get(name, "not_supported_by_hub_setup"),
        ]
        if not selected:
            configured = "not_selected"
        elif batch_error:
            configured = "outcome_unknown_after_batch_error"
        elif "failed_or_partial" in configured_states:
            configured = "failed_or_partial"
        elif "configured_with_manual_steps" in configured_states:
            configured = "configured_with_manual_steps"
        elif any(state == "configured" for state in configured_states):
            configured = "configured_by_setup"
        elif "selected_for_manual_install" in configured_states:
            configured = "selected_for_manual_install"
        else:
            configured = "no_components_configured"
        report[name] = {
            "selected_for_setup": selected,
            "configured": configured,
            "components": dict(component_states),
            "installed": "not_observed_by_setup",
            "enabled": "not_observed_by_setup",
            "manual_actions": list((manual_actions_by_provider or {}).get(name, [])),
            "hooks": hook_installation.get(name, "not_supported_by_hub_setup"),
            "plugin": plugin_installation.get(name, "not_supported_by_hub_setup"),
            "trust": "host_controlled_not_observed",
            "connection": "not_probed_by_setup",
            "runtime_verification": "not_run",
        }
    return report


def provider_manual_actions(actions: list[str]) -> dict[str, list[str]]:
    """Attribute setup warnings only to provider identities named in the action."""
    aliases = {
        "codex": ("codex",),
        "claude": ("claude",),
        "gemini": ("gemini",),
        "antigravity": ("antigravity",),
        "cursor": ("cursor",),
        "windsurf": ("windsurf", "cascade"),
        "copilot": ("copilot",),
        "opencode": ("opencode",),
        "devin": ("devin",),
    }
    attributed = {provider: [] for provider in aliases}
    attributed["unattributed"] = []
    for action in actions:
        text = str(action).casefold()
        matches = [
            provider for provider, names in aliases.items()
            if any(re.search(rf"\b{re.escape(name)}\b", text) for name in names)
        ]
        if matches:
            for target in matches:
                attributed[target].append(str(action))
        else:
            attributed["unattributed"].append(str(action))
    return attributed


def provider_setup_component_state(
    selected: bool,
    *,
    batch_error: str | None = None,
    manual_actions: list[str] | None = None,
) -> str:
    """Summarize one provider's setup outcome without borrowing sibling state."""
    if not selected:
        return "not_selected"
    if batch_error:
        return "outcome_unknown_after_batch_error"
    if manual_actions:
        return "configured_with_manual_steps"
    return "configured"


def _configure_agents_impl(
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    *,
    include_companion: bool = True,
    agent_components: dict[str, Any] | None = None,
) -> list[str]:
    manual_actions: list[str] = []
    codex_entries = build_codex_mcp_entries(install_dir, hub_python, serena, cfg)
    codex_entry = codex_entries.get("local-ai", {})
    agents_cfg = cfg.get("agents", {})
    codex_homes: list[Path] = []
    if agents_cfg.get("codex", True):
        if os.environ.get("CODEX_HOME"):
            codex_homes.append(Path(os.environ["CODEX_HOME"]))
        for u_home in get_user_homes():
            ch = u_home / ".codex"
            if ch.resolve() not in [p.resolve() for p in codex_homes]:
                codex_homes.append(ch)
    if (
        agents_cfg.get("codex", True)
        and _agent_component_enabled(agent_components, "codex", "mcp")
        and "url" in codex_entry
        and any(
            not codex_hub_plugin_enabled(codex_home / "config.toml")
            for codex_home in codex_homes
        )
        and not _http_mcp_ready(codex_entry["url"])
    ):
        raise RuntimeError("HTTP MCP transport is not ready; Codex configuration was not changed")
    backup_enabled = bool(cfg.get("setup", {}).get("backup_existing_configs", True))
    write_all_generated(cfg, install_dir, hub_python, serena)
    # Cursor and Windsurf discover the shared ~/.agents/skills directory too.
    # Keep that shared tree only when every supported consumer is selected;
    # otherwise install for selected clients in their native skill directory.
    standard_skill_tree_enabled = agents_cfg.get("agent_skills_standard", True) and all(
        agents_cfg.get(name, True)
        and _agent_component_enabled(agent_components, name, "skills")
        for name in ("codex", "cursor", "windsurf", "devin")
    )
    if standard_skill_tree_enabled:
        for u_home in get_user_homes():
            install_agent_skills(install_dir, u_home / ".agents" / "skills", include_companion=include_companion)
    if agents_cfg.get("codex", True):
        for codex_home in codex_homes:
            if _agent_component_enabled(agent_components, "codex", "skills"):
                install_agent_skills(install_dir, codex_home / "skills", include_companion=include_companion)
            if (
                cfg.get("tool_policy", {}).get("install_global_instructions", True)
                and _agent_component_enabled(agent_components, "codex", "instructions")
            ):
                doc = codex_home / ("AGENTS.override.md" if (codex_home / "AGENTS.override.md").exists() else "AGENTS.md")
                try:
                    merge_global_policy(doc, backup_enabled, cfg=cfg)
                    merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
                    merge_autosetup_policy(doc, backup_enabled, codex_home / "skills")
                except ValueError as exc:
                    if "external block has no ownership record" not in str(exc):
                        raise
                    manual_action = f"Codex instructions preserved: {doc} ({exc})"
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
            if _agent_component_enabled(agent_components, "codex", "mcp"):
                codex_config = codex_home / "config.toml"
                if codex_hub_plugin_enabled(codex_config):
                    manual_action = (
                        f"Codex Hub plugin is enabled in {codex_config}; standalone MCP setup skipped "
                        "to avoid duplicate tools"
                    )
                    manual_actions.append(manual_action)
                    log(manual_action)
                else:
                    try:
                        codex_mcp_merge(
                            codex_config, codex_entries, backup_enabled,
                            startup_timeout=int(cfg.get("client", {}).get("startup_wait_seconds", 15)) + 15,
                            tool_timeout=int(cfg.get("mcp", {}).get("host_tool_timeout_seconds", 900)),
                        )
                    except ValueError as exc:
                        if "external block has no ownership record" not in str(exc):
                            raise
                        manual_action = f"Codex MCP config preserved: {codex_config} ({exc})"
                        manual_actions.append(manual_action)
                        log(f"Manual agent setup required: {manual_action}")
    if agents_cfg.get("claude", True):
        claude_settings = Path.home() / ".claude" / "settings.json"
        claude_mcp_config = Path.home() / ".claude.json"
        claude_plugin_enabled = claude_hub_plugin_enabled(claude_settings)
        if _agent_component_enabled(agent_components, "claude", "skills"):
            install_agent_skills(install_dir, Path.home() / ".claude" / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "claude", "instructions")
        ):
            doc = Path.home() / ".claude" / "CLAUDE.md"
            try:
                merge_global_policy(doc, backup_enabled, cfg=cfg)
                merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
            except ValueError as exc:
                if "external block has no ownership record" not in str(exc):
                    raise
                manual_action = f"Claude instructions preserved: {doc} ({exc})"
                manual_actions.append(manual_action)
                log(f"Manual agent setup required: {manual_action}")
        if _agent_component_enabled(agent_components, "claude", "mcp"):
            if claude_plugin_enabled:
                if claude_global_hub_mcp_configured(claude_mcp_config):
                    manual_action = (
                        f"Claude Hub plugin is enabled; standalone MCP remains in {claude_mcp_config}. "
                        "Remove one route to avoid duplicate tools"
                    )
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
            else:
                json_mcp_merge(
                    claude_mcp_config,
                    build_mcp_entries(install_dir, hub_python, serena, "claude", cfg),
                    backup_enabled,
                )
        if _agent_hooks_enabled(agent_components, "claude") and claude_plugin_enabled:
            if claude_global_hub_hooks_configured(claude_settings):
                manual_action = (
                    f"Claude Hub plugin is enabled; global Hub hooks remain in {claude_settings}. "
                    "Remove duplicate hooks after reviewing the current file"
                )
                manual_actions.append(manual_action)
                log(f"Manual agent setup required: {manual_action}")
        elif _agent_hooks_enabled(agent_components, "claude"):
            if not sync_claude_session_start_hook(
                claude_settings, install_dir, hub_python, backup_enabled,
            ):
                manual_actions.append(
                    f"Claude SessionStart hook not installed; review and merge manually: "
                    f"{claude_settings}"
                )
            if not sync_claude_subagent_start_hook(
                claude_settings, install_dir, hub_python, backup_enabled,
            ):
                manual_actions.append(
                    f"Claude SubagentStart hook not installed; review and merge manually: "
                    f"{claude_settings}"
                )
            if not sync_claude_pre_tool_hook(
                claude_settings, install_dir, hub_python, backup_enabled,
            ):
                manual_actions.append(
                    f"Claude PreToolUse hook not installed; review and merge manually: "
                    f"{claude_settings}"
                )
            if not sync_claude_permission_request_hook(
                claude_settings, install_dir, hub_python, backup_enabled,
            ):
                manual_actions.append(
                    f"Claude PermissionRequest hook not installed; review and merge manually: "
                    f"{claude_settings}"
                )
            if not sync_claude_post_tool_hook(
                claude_settings, install_dir, hub_python, backup_enabled,
            ):
                manual_actions.append(
                    f"Claude PostToolUse hook not installed; review and merge manually: "
                    f"{claude_settings}"
                )
    if agents_cfg.get("gemini", True) or agents_cfg.get("antigravity", True):
        for u_home in get_user_homes():
            g_dir = u_home / ".gemini"
            if u_home.resolve() == Path.home().resolve() or g_dir.exists() or u_home.exists():
                configure_gemini_instance(
                    g_dir, install_dir, hub_python, serena, cfg, backup_enabled, include_companion,
                    agent_components=agent_components, manual_actions=manual_actions,
                )
    # Additional MCP hosts with their documented user-level skills and rules.
    if agents_cfg.get("cursor", True):
        cursor_dir = Path.home() / ".cursor"
        if _agent_component_enabled(agent_components, "cursor", "skills") and not standard_skill_tree_enabled:
            install_agent_skills(install_dir, cursor_dir / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "cursor", "instructions")
        ):
            cursor_rule = cursor_dir / "rules" / "local-ai-hub.mdc"
            if ensure_cursor_rule_frontmatter(cursor_rule, backup_enabled):
                merge_global_policy(cursor_rule, backup_enabled, cfg=cfg)
                merge_token_economy_policy(cursor_rule, backup_enabled, cfg=cfg)
            elif _ADOPT_UNOWNED_HUB_BLOCKS:
                # Preserve user-owned frontmatter, but refresh explicitly adopted Hub blocks.
                merge_global_policy(cursor_rule, backup_enabled, cfg=cfg)
                merge_token_economy_policy(cursor_rule, backup_enabled, cfg=cfg)
                manual_actions.append(
                    f"Cursor rule frontmatter ownership is unclear and was preserved; "
                    f"Hub instruction blocks were refreshed: {cursor_rule}"
                )
            else:
                manual_actions.append(
                    f"Cursor rule frontmatter ownership is unclear and was preserved: {cursor_rule}. "
                    "Adopt its marked Hub blocks or merge the instructions manually."
                )
        configure_cursor_global_routes(
            cursor_dir, install_dir, hub_python, serena, cfg, backup_enabled,
            agent_components, manual_actions,
        )
    if agents_cfg.get("windsurf", True):
        windsurf_dir = Path.home() / ".codeium" / "windsurf"
        if _agent_component_enabled(agent_components, "windsurf", "skills") and not standard_skill_tree_enabled:
            install_agent_skills(install_dir, windsurf_dir / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "windsurf", "instructions")
        ):
            manual_action = merge_windsurf_global_policy(
                windsurf_dir / "memories" / "global_rules.md", install_dir, backup_enabled
            )
            if manual_action:
                manual_actions.append(manual_action)
                log(f"Manual agent setup required: {manual_action}")
        if _agent_component_enabled(agent_components, "windsurf", "mcp"):
            json_mcp_merge(Path.home() / ".codeium" / "windsurf" / "mcp_config.json", build_mcp_entries(install_dir, hub_python, serena, "windsurf", cfg), backup_enabled)
        if _agent_hooks_enabled(agent_components, "windsurf"):
            hook_path = windsurf_dir / "hooks.json"
            if not sync_windsurf_policy_hooks(hook_path, install_dir, hub_python, backup_enabled):
                manual_actions.append(f"Windsurf policy hooks not installed; review and merge manually: {hook_path}")
    if agents_cfg.get("copilot", True):
        copilot_dir = copilot_home()
        if _agent_component_enabled(agent_components, "copilot", "skills"):
            install_agent_skills(install_dir, copilot_dir / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "copilot", "instructions")
        ):
            merge_global_policy(copilot_dir / "copilot-instructions.md", backup_enabled, cfg=cfg)
            merge_token_economy_policy(copilot_dir / "copilot-instructions.md", backup_enabled, cfg=cfg)
        configure_copilot_global_routes(
            copilot_dir, Path.cwd(), install_dir, hub_python, serena, cfg,
            backup_enabled, agent_components, manual_actions,
        )

    if agents_cfg.get("devin", False):
        devin_dir = devin_config_dir()
        plugin_route = bool(agents_cfg.get("devin_plugin_route", False))
        if (
            _agent_component_enabled(agent_components, "devin", "skills")
            and not standard_skill_tree_enabled and not plugin_route
        ):
            install_agent_skills(install_dir, devin_dir / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "devin", "instructions")
        ):
            doc = Path.home() / ".devin" / "global_rules.md"
            try:
                merge_global_policy(doc, backup_enabled, cfg=cfg)
                merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
            except ValueError as exc:
                if "external block has no ownership record" not in str(exc):
                    raise
                action = f"Devin Local instructions preserved: {doc} ({exc})"
                manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
        if _agent_component_enabled(agent_components, "devin", "mcp"):
            mcp_path = devin_mcp_config_path()
            if plugin_route:
                action = (
                    "Devin Local plugin route is selected; install the bundled plugin manually with "
                    f"`devin plugins install --local {install_dir / 'plugins' / 'devin' / 'local-ai-hub'}`"
                )
                manual_actions.append(action)
                log(f"Manual agent setup required: {action}")
                if global_hub_mcp_configured(mcp_path):
                    duplicate = (
                        f"Devin Local standalone Hub MCP remains in {mcp_path}; remove that managed route "
                        "after confirming the plugin works"
                    )
                    manual_actions.append(duplicate)
                    log(f"Manual agent setup required: {duplicate}")
            else:
                json_mcp_merge(
                    mcp_path,
                    build_mcp_entries(install_dir, hub_python, serena, "devin", cfg),
                    backup_enabled,
                )
        if _agent_hooks_enabled(agent_components, "devin"):
            hooks_path = devin_dir / "config.json"
            if not sync_devin_pre_tool_hook(hooks_path, install_dir, hub_python, backup_enabled):
                manual_actions.append(
                    f"Devin Local PreToolUse hook not installed; review and merge manually: {hooks_path}"
                )
            if not sync_devin_post_tool_hook(hooks_path, install_dir, hub_python, backup_enabled):
                manual_actions.append(
                    f"Devin Local PostToolUse hook not installed; review and merge manually: {hooks_path}"
                )

    if agents_cfg.get("opencode", True):
        for oc_dir in opencode_config_dirs():
            if _agent_component_enabled(agent_components, "opencode", "skills"):
                install_agent_skills(install_dir, oc_dir / "skills", include_companion=include_companion)
            if (
                cfg.get("tool_policy", {}).get("install_global_instructions", True)
                and _agent_component_enabled(agent_components, "opencode", "instructions")
            ):
                doc = oc_dir / "AGENTS.md"
                try:
                    merge_global_policy(doc, backup_enabled, cfg=cfg)
                    merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
                except ValueError as exc:
                    if "external block has no ownership record" not in str(exc):
                        raise
                    manual_action = f"OpenCode instructions preserved: {doc} ({exc})"
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
            if _agent_component_enabled(
                agent_components, "opencode", "plugin",
                default=bool(agents_cfg.get("opencode_plugin_route", True)),
            ):
                plugin_config = oc_dir / "opencode.json"
                existing_mcp_paths = opencode_hub_mcp_paths(oc_dir)
                existing_plugin_paths = opencode_hub_plugin_paths(oc_dir)
                if existing_mcp_paths:
                    refreshable_route = (
                        len(existing_mcp_paths) == 1
                        and existing_mcp_paths[0].suffix.lower() == ".json"
                        and _opencode_direct_hub_mcp_server_name(existing_mcp_paths[0]) == "local-ai-hub"
                        and (not existing_plugin_paths or existing_plugin_paths == existing_mcp_paths)
                    )
                    if refreshable_route:
                        plugin_config = existing_mcp_paths[0]
                        if not sync_opencode_plugin_config(
                            plugin_config, install_dir, hub_python, cfg, backup_enabled,
                        ):
                            manual_action = f"OpenCode Hub plugin requires a manual merge in {plugin_config}"
                            manual_actions.append(manual_action)
                            log(f"Manual agent setup required: {manual_action}")
                    else:
                        manual_action = (
                            "OpenCode standalone Hub MCP already exists in "
                            f"{', '.join(str(path) for path in existing_mcp_paths)}; "
                            "plugin route was preserved and not added to avoid duplicate tools"
                        )
                        manual_actions.append(manual_action)
                        log(f"Manual agent setup required: {manual_action}")
                elif existing_plugin_paths:
                    # JSON configs can be merged transactionally with per-key rollback.
                    # Keep JSONC and multiple-config cases untouched because rewriting
                    # them could discard comments or create a competing plugin route.
                    if len(existing_plugin_paths) == 1 and existing_plugin_paths[0].suffix.lower() == ".json":
                        plugin_config = existing_plugin_paths[0]
                        if not sync_opencode_plugin_config(
                            plugin_config, install_dir, hub_python, cfg, backup_enabled,
                        ):
                            manual_action = f"OpenCode Hub plugin requires a manual merge in {plugin_config}"
                            manual_actions.append(manual_action)
                            log(f"Manual agent setup required: {manual_action}")
                    else:
                        log(
                            "OpenCode Hub plugin already registered in "
                            f"{', '.join(str(path) for path in existing_plugin_paths)}; preserved"
                        )
                elif not sync_opencode_plugin_config(
                    plugin_config, install_dir, hub_python, cfg, backup_enabled,
                ):
                    manual_action = f"OpenCode Hub plugin requires a manual merge in {plugin_config}"
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
            elif _agent_component_enabled(agent_components, "opencode", "mcp"):
                existing_mcp_paths = opencode_hub_mcp_paths(oc_dir)
                existing_plugin_paths = opencode_hub_plugin_paths(oc_dir)
                if existing_mcp_paths:
                    manual_action = (
                        "OpenCode standalone Hub MCP already exists in "
                        f"{', '.join(str(path) for path in existing_mcp_paths)}; "
                        "existing route was preserved"
                    )
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
                elif existing_plugin_paths:
                    manual_action = (
                        "OpenCode Hub plugin already exists in "
                        f"{', '.join(str(path) for path in existing_plugin_paths)}; "
                        "standalone MCP route was not added to avoid duplicate tools"
                    )
                    manual_actions.append(manual_action)
                    log(f"Manual agent setup required: {manual_action}")
                else:
                    opencode_mcp_merge(
                        oc_dir / "opencode.json", install_dir, hub_python, cfg, backup_enabled,
                    )

    # Escape hatch for any MCP host/build whose config path differs from
    # the common defaults above. Users provide explicit paths, so setup never guesses
    # at vendor-specific locations or overwrites unrelated files.
    generic_entries = build_mcp_entries(install_dir, hub_python, serena, "generic", cfg)
    for raw in agents_cfg.get("extra_mcp_json_paths", []) or []:
        if str(raw).strip():
            json_mcp_merge(expand(str(raw)), generic_entries, backup_enabled)
    for raw in agents_cfg.get("extra_vscode_mcp_paths", []) or []:
        if str(raw).strip():
            vscode_mcp_merge(expand(str(raw)), generic_entries, backup_enabled)
    write_generated_agent_manifests(install_dir, hub_python, serena, cfg)
    return manual_actions


def configure_agents(
    install_dir: Path,
    hub_python: Path,
    serena: Path | None,
    cfg: dict[str, Any],
    *,
    include_companion: bool = True,
    agent_components: dict[str, Any] | None = None,
) -> list[str]:
    global _ACTIVE_INSTALL_ROOT
    previous_root = _ACTIVE_INSTALL_ROOT
    candidate_root = Path(install_dir)
    _ACTIVE_INSTALL_ROOT = candidate_root if candidate_root.is_dir() else None
    if _ACTIVE_INSTALL_ROOT is not None:
        write_install_manifest(_ACTIVE_INSTALL_ROOT)
    try:
        return _configure_agents_impl(
            install_dir, hub_python, serena, cfg,
            include_companion=include_companion,
            agent_components=agent_components,
        )
    finally:
        _ACTIVE_INSTALL_ROOT = previous_root



def select_config_source(explicit: Path | None) -> tuple[Path, dict[str, Any], Path]:
    """Resolve config for idempotent installs.

    A normal rerun preserves the config already living in the install directory.
    Passing --config is explicit replacement/import intent and therefore wins.
    """
    if explicit is not None:
        source = explicit.expanduser().resolve()
    else:
        local_config = SOURCE_ROOT / "config.toml"
        example_config = SOURCE_ROOT / "config.toml.example"
        source = (local_config if local_config.is_file() else example_config).expanduser().resolve()
    if source.name != "config.toml.example":
        run_config_migrations(source)
    cfg = load_hub_config(str(source))
    install_dir = expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
    installed = (install_dir / "config.toml").resolve()
    if explicit is None and installed.exists() and installed != source:
        source = installed
        run_config_migrations(source)
        cfg = load_hub_config(str(source))
    return source, cfg, install_dir

def main() -> int:
    global _ADOPT_UNOWNED_HUB_BLOCKS
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required. Use install.ps1/install.sh to bootstrap a supported Python automatically.")
    parser = argparse.ArgumentParser(description="Install Local AI Hub")
    parser.add_argument("--config", type=Path, default=None, help="Import/replace config from this path. Without it, reruns preserve the installed config.")
    parser.add_argument("--profile", choices=["auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max"])
    parser.add_argument("--skip-model-pull", action="store_true", default=None)
    parser.add_argument("--skip-local-nlp-preload", action="store_true")
    parser.add_argument("--skip-laya-runtime", action="store_true", default=None)
    parser.add_argument("--skip-ast-index", action="store_true", default=None)
    parser.add_argument("--skip-performance", action="store_true", default=None)
    parser.add_argument("--skip-profiling", action="store_true", default=None)
    parser.add_argument("--skip-tools", action="store_true", default=None, help="Do not install Serena")
    parser.add_argument("--skip-agent-config", action="store_true", default=None)
    parser.add_argument("--skip-service", action="store_true", default=None)
    parser.add_argument("--skip-ollama-install", action="store_true")
    parser.add_argument("--skip-token-economy", action="store_true", default=None, help="Do not install token economy packages or probe external CLI tools")
    parser.add_argument("--skip-companion-skills", action="store_true", default=None, help="Do not install companion skills or pinned Superpowers for Gemini/Antigravity")
    parser.add_argument("--adopt-existing-hub-blocks", action="store_true", help="Adopt only current marked Hub blocks after saving rollback copies")
    setup_mode = parser.add_mutually_exclusive_group()
    setup_mode.add_argument("--interactive", dest="interactive", action="store_true", default=None, help="Show the installer wizard even when setup is scripted")
    setup_mode.add_argument("--non-interactive", action="store_true", help="Never prompt; use explicit flags, saved choices, and safe defaults")
    parser.add_argument("--full-reinstall", action="store_true", help="Remove the managed virtual environment, Hub state, and Hub model cache before reinstalling")
    parser.add_argument("--confirm-full-reinstall", help="Non-interactive confirmation; must exactly equal `DELETE <resolved state directory>`")
    parser.add_argument("--generate-only", action="store_true", help="Generate dynamic skill, instructions, MCP manifests, and schemas without re-installing dependencies or service.")
    parser.add_argument("--expected-revision", help="Exact verified 40-character source commit required for install/update.")
    parser.add_argument("--host-project-root", type=Path, help="Explicit project root for isolated host-hook maintenance; skips Hub install/service/model actions.")
    parser.add_argument("--host-adapter", choices=["codex", "gemini_cli"], help="Documented local host hook format.")
    parser.add_argument("--host-action", choices=["preview", "apply", "rollback"], default="preview")
    parser.add_argument("--host-preview-revision", help="Fresh preview revision required by host apply.")
    parser.add_argument("--superpowers-root", type=Path, help="Explicit installed Superpowers package to check against supported 7.0.1; never installs or overwrites it.")
    parser.add_argument("--install-superpowers", action="store_true", help="Explicitly install missing pinned Gemini extension during --host-action apply; normal setup separately checks the Codex plugin.")
    parser.add_argument("--superpowers-executable", type=Path, help="Absolute native Gemini executable, or node.exe with --superpowers-entrypoint; no .cmd/.bat wrappers.")
    parser.add_argument("--superpowers-entrypoint", type=Path, help="Absolute Gemini CLI JavaScript entrypoint for a native Node launcher.")
    parser.add_argument("--superpowers-consent", action="store_true", help="Explicitly acknowledge third-party Gemini extension installation risks.")
    args = parser.parse_args()
    _ADOPT_UNOWNED_HUB_BLOCKS = bool(args.adopt_existing_hub_blocks)

    if args.host_project_root is not None or args.host_adapter is not None:
        if args.host_project_root is None or args.host_adapter is None:
            parser.error("--host-project-root and --host-adapter are required together")
        from local_ai_hub.repo_plan.host_hooks import ManagedHostInstallation, inspect_superpowers, install_superpowers
        try:
            manager = ManagedHostInstallation(args.host_project_root, args.host_adapter)
            dependency = inspect_superpowers(args.host_adapter, args.superpowers_root)
            if args.host_action == "apply":
                if not args.host_preview_revision:
                    parser.error("host apply requires --host-preview-revision from preview")
                if args.install_superpowers:
                    if args.superpowers_root is None or args.superpowers_executable is None:
                        parser.error("dependency install requires --superpowers-root and --superpowers-executable")
                    installed = install_superpowers(args.host_adapter, repo_root=args.host_project_root,
                                package_root=args.superpowers_root, executable=args.superpowers_executable,
                                entrypoint=args.superpowers_entrypoint, operator_authorized=True,
                                consent=args.superpowers_consent)
                    if not installed["success"]:
                        print(json.dumps(installed))
                        return 1
                    dependency = installed["dependency"]
                result = manager.apply(expected_revision=args.host_preview_revision)
            elif args.host_action == "rollback":
                result = manager.rollback()
            else:
                result = manager.preview()
            result["superpowers"] = dependency
        except (OSError, ValueError) as exc:
            print(json.dumps({"success": False, "error": str(exc)}))
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if any([args.superpowers_root is not None, args.host_preview_revision is not None, args.host_action != "preview",
            args.install_superpowers, args.superpowers_executable is not None,
            args.superpowers_entrypoint is not None, args.superpowers_consent]):
        parser.error("host maintenance options require --host-project-root and --host-adapter")

    if not args.generate_only and args.expected_revision:
        try:
            verified_revision = verify_source_revision(args.expected_revision)
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        log(f"Verified clean source commit: {verified_revision}")

    config_source, cfg, install_dir = select_config_source(args.config)
    try:
        with installation_update_lock(install_dir):
            return run_installation(args, config_source, cfg, install_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        log(f"Setup refused or failed: {exc}")
        return 1


def run_installation(args: argparse.Namespace, config_source: Path, cfg: dict[str, Any], install_dir: Path) -> int:
    global _ADOPT_UNOWNED_HUB_BLOCKS
    setup_choices = configure_setup_choices(args, cfg, install_dir, argv=sys.argv[1:])
    include_companion = not args.skip_companion_skills and bool(cfg.get("setup", {}).get("install_companion_skills", True))
    if args.generate_only:
        hub_python = venv_python(install_dir / ".venv")
        if not hub_python.exists():
            hub_python = Path(sys.executable)
        write_all_generated(cfg, SOURCE_ROOT, hub_python)
        if install_dir.resolve() != SOURCE_ROOT.resolve():
            write_all_generated(cfg, install_dir, hub_python)
        if not args.skip_agent_config and bool(cfg.get("setup", {}).get("install_agent_configs", True)):
            for manual_action in configure_agents(
                install_dir, hub_python, None, cfg,
                include_companion=include_companion,
                agent_components=setup_choices,
            ):
                log(f"Manual agent setup required: {manual_action}")
        log("Skill, agent instructions, and MCP artifacts successfully generated.")
        return 0

    log(f"Installing to {install_dir}")

    # Stop a currently managed instance if this exact install already exists. This is
    # normal idempotent setup behavior for this installation target.
    old_python = venv_python(install_dir / ".venv")
    old_service = install_dir / "tools" / "service.py"
    runtime_stop_result: list[tuple[bool, str] | None] = [None]

    def stop_before_commit() -> tuple[bool, str]:
        if runtime_stop_result[0] is None:
            runtime_stop_result[0] = stop_existing_runtime(install_dir, old_python, old_service, run)
        return runtime_stop_result[0]

    if args.full_reinstall:
        state_dir = expand(str(cfg.get("server", {}).get("state_dir", install_dir / "state")))
        try:
            removed = perform_full_reinstall(
                install_dir,
                state_dir,
                SOURCE_ROOT,
                home=Path.home(),
                stop_runtime=stop_before_commit,
                interactive=not args.non_interactive and args.confirm_full_reinstall is None and sys.stdin.isatty(),
                confirmation=args.confirm_full_reinstall,
            )
            log(f"Full reinstall removed Hub runtime/state paths: {', '.join(str(path) for path in removed)}")
        except Exception as exc:
            log(f"Full reinstall refused: {exc}")
            write_setup_failure_report(install_dir, state_dir, stage="full_reinstall", error=exc)
            return 1

    state_dir = expand(str(cfg.get("server", {}).get("state_dir", install_dir / "state")))
    try:
        migration_preflight = inspect_state_migration_path(state_dir)
        log(
            "State migration preflight passed: "
            f"{migration_preflight.get('status')} (version {migration_preflight.get('version')})."
        )
    except Exception as exc:
        log(f"Setup/update refused before replacing installed code: state migration preflight failed: {exc}")
        write_migration_failure_report(
            install_dir, state_dir, stage="preflight", error=exc, selected=setup_choices
        )
        log(f"Recovery guide: {SOURCE_ROOT / 'docs' / 'INSTALLER_RECOVERY.md'}")
        return 1

    migration_result: dict[str, Any] = {}
    migration_error: Exception | None = None
    embedding_reset_backup: str | None = None

    def migrate_state_after_swap() -> tuple[bool, str]:
        nonlocal migration_result, migration_error, embedding_reset_backup
        try:
            migration_result = migrate_release_state(state_dir)
            embedding_reset_backup = migration_result.get("embedding_reset_backup")
            return True, str(migration_result.get("status", "completed"))
        except Exception as exc:
            migration_error = exc
            return False, str(exc)

    if not copy_install_tree(
        install_dir, config_source,
        before_commit=stop_before_commit,
        after_swap=migrate_state_after_swap,
    ):
        log("Setup incomplete: install transaction did not commit; runtime setup and service start skipped.")
        if migration_error is not None:
            write_migration_failure_report(
                install_dir, state_dir, stage="apply", error=migration_error, selected=setup_choices
            )
            log(f"Recovery guide: {SOURCE_ROOT / 'docs' / 'INSTALLER_RECOVERY.md'}")
        else:
            write_setup_failure_report(
                install_dir, state_dir, stage="install_payload", error="Install transaction did not commit."
            )
        return 1
    log(f"State migration status: {migration_result.get('status')} (version {migration_result.get('version')}).")
    for backup_path in migration_result.get("backups", []):
        log(f"Verified state backup: {backup_path}")
    for warning in migration_result.get("warnings", []):
        log(f"WARNING: state migration cleanup: {warning}")
    installed_config = install_dir / "config.toml"
    if args.profile:
        text = installed_config.read_text(encoding="utf-8")
        section = re.search(r"(?ms)^\[hardware\]\s*$(.*?)(?=^\[|\Z)", text)
        if section:
            body = section.group(1)
            if re.search(r"(?m)^profile\s*=", body):
                body = re.sub(r'(?m)^profile\s*=.*$', f'profile = "{args.profile}"', body)
            else:
                body = f'\nprofile = "{args.profile}"' + body
            text = text[:section.start(1)] + body + text[section.end(1):]
        else:
            text = text.rstrip() + f'\n\n[hardware]\nprofile = "{args.profile}"\nauto_tune = true\n'
        installed_config.write_text(text, encoding="utf-8")
    cfg = load_hub_config(str(installed_config))
    apply_setup_choices(args, cfg, setup_choices)
    state_dir = expand(str(cfg.get("server", {}).get("state_dir", install_dir / "state")))
    if args.skip_model_pull:
        cfg.setdefault("features", {})["pull_models_during_setup"] = False
    fp4_model_catalog: dict[str, Any] = {"status": "unavailable", "catalog_version": "unavailable"}
    try:
        source_src = str(SOURCE_ROOT / "src")
        if source_src not in sys.path:
            sys.path.insert(0, source_src)
        from local_ai_hub.fp4_capabilities import load_fp4_catalog

        catalog = load_fp4_catalog()
        hardware = cfg.get("_hardware", {})
        routes = hardware.get("fp4_model_routes", {}) if isinstance(hardware, dict) else {}
        fp4_model_catalog = {
            "status": "loaded" if catalog.get("catalog_version") != "unavailable" else "unavailable",
            "catalog_version": catalog.get("catalog_version", "unavailable"),
            "checked_at": catalog.get("checked_at"),
            "selected_routes": routes if isinstance(routes, dict) else {},
        }
        log(f"FP4 catalog: {fp4_model_catalog['catalog_version']} (pre-checked static data; no model audit run).")
    except Exception as exc:
        fp4_model_catalog = {"status": "unavailable", "catalog_version": "unavailable", "reason": str(exc)}
        log(f"NOTICE: static FP4 catalog unavailable; configured routes are retained: {exc}")
    try:
        hub_python = ensure_venv(install_dir / ".venv")
        install_requirements(hub_python, install_dir / "requirements-core.txt")
        # Register the package and console entry points inside the managed runtime.
        # Otherwise the global CLI wrappers only work with an explicit PYTHONPATH.
        run([str(hub_python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "-e", str(install_dir)], timeout=300)
    except Exception as exc:
        log(f"Setup incomplete: core runtime installation failed: {exc}")
        write_setup_failure_report(install_dir, state_dir, stage="core_runtime", error=exc)
        return 1
    token_economy_result: dict[str, Any] = {"status": "not_selected"}
    if not args.skip_token_economy:
        try:
            token_economy_result = install_token_economy_suite(
                install_dir, hub_python, allow_external_tools=True
            )
        except Exception as exc:
            token_economy_result = {"status": "failed", "error": str(exc)}
            log(f"WARNING: Token Economy setup stopped early: {exc}")

    serena: Path | None = None
    setup_cfg = cfg.get("setup", {})
    if args.adopt_existing_hub_blocks or setup_cfg.get("adopt_existing_hub_blocks", True):
        _ADOPT_UNOWNED_HUB_BLOCKS = True
    if not args.skip_tools and bool(setup_cfg.get("install_optional_tools", True)):
        intelligence = cfg.get("code_intelligence", {})
        if intelligence.get("serena_enabled", True):
            serena = install_tool_env(install_dir, "serena", str(cfg.get("tools", {}).get("serena_package", "serena-agent==1.7.0")), ["serena"])

    features = cfg.get("features", {})
    model_cfg = cfg.get("models", {})
    embedding_backend = str(model_cfg.get("embedding_backend", "sentence-transformers")).lower()
    reranker_backend = str(model_cfg.get("reranker_backend", "torch")).lower()
    needs_local_nlp = (
        (bool(features.get("reranker", True)) and reranker_backend != "openvino")
        or (bool(features.get("rag", True)) and embedding_backend in {"sentence-transformers", "auto"})
    )
    local_nlp_ok = False
    local_nlp_preload_ok: bool | None = None
    local_nlp_model_report: dict[str, Any] = {
        "status": "not_needed" if not needs_local_nlp else "not_started",
        "models": {},
    }
    if needs_local_nlp and features.get("install_local_nlp_dependencies", True):
        local_nlp_ok = install_requirements(hub_python, install_dir / "requirements-local-nlp.txt", optional=True)
        if not local_nlp_ok:
            local_nlp_model_report["status"] = "dependencies_unavailable"
        elif args.skip_local_nlp_preload:
            local_nlp_model_report["status"] = "skipped"
        else:
            try:
                preload_result = run(
                    [
                        str(hub_python), str(install_dir / "tools" / "prefetch_local_nlp.py"), "--json",
                        "--allow-hf-downloads" if setup_choices.get("download_hf_models", False)
                        else "--no-hf-downloads",
                    ],
                    check=False, timeout=1800, capture=True,
                )
                try:
                    parsed = json.loads(preload_result.stdout or "")
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                if isinstance(parsed, dict):
                    local_nlp_model_report = {
                        "status": "ready" if parsed.get("success") is True else "unavailable",
                        "models": {
                            name: parsed.get(name)
                            for name in ("embedding", "reranker")
                        },
                    }
                    local_nlp_preload_ok = parsed.get("success") is True
                else:
                    local_nlp_model_report["status"] = "unavailable"
                    local_nlp_preload_ok = False
            except Exception as exc:
                local_nlp_model_report["status"] = "unavailable"
                local_nlp_preload_ok = False
                log(f"WARNING: local NLP model preload failed: {exc}")
    elif needs_local_nlp:
        local_nlp_model_report["status"] = "disabled"

    hw_detected = cfg.get("_hardware", {})
    detected_gpus = hw_detected.get("gpus", []) if isinstance(hw_detected, dict) else []
    detected_npus = hw_detected.get("npus", []) if isinstance(hw_detected, dict) else []
    has_intel_gpu = any(str(g.get("vendor", "")).lower() == "intel" for g in detected_gpus if isinstance(g, dict))
    has_intel_npu = any(
        str(npu.get("vendor", "")).lower() == "intel"
        for npu in detected_npus
        if isinstance(npu, dict)
    )

    needs_openvino = (
        embedding_backend == "openvino"
        or reranker_backend == "openvino"
        or has_intel_npu
        or (has_intel_gpu and cfg.get("_hardware", {}).get("profile") == "integrated")
    )
    ov_cfg = cfg.get("openvino", {})
    install_openvino = (
        needs_openvino
        and features.get("install_openvino_dependencies", True)
        and bool(ov_cfg.get("enabled", True))
        and bool(ov_cfg.get("auto_install", True))
    )
    openvino_ok = False
    openvino_preload_ok: bool | None = None
    openvino_model_report: dict[str, Any] = {
        "status": "not_needed" if not needs_openvino else "not_started",
        "models": {},
    }
    if install_openvino:
        openvino_ok = install_requirements(hub_python, install_dir / "requirements-openvino.txt", optional=True)
        if not openvino_ok:
            openvino_model_report["status"] = "dependencies_unavailable"
        elif args.skip_local_nlp_preload:
            openvino_model_report["status"] = "skipped"
        else:
            try:
                preload_result = run(
                    [
                        str(hub_python), str(install_dir / "tools" / "prefetch_openvino.py"),
                        "--allow-hf-downloads" if setup_choices.get("download_hf_models", False)
                        else "--no-hf-downloads",
                    ],
                    check=False, timeout=1800, capture=True,
                )
                try:
                    parsed = json.loads(preload_result.stdout or "")
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                requested_models = {
                    "embedding": embedding_backend == "openvino" and bool(features.get("rag", True)),
                    "reranker": reranker_backend == "openvino" and bool(features.get("reranker", True)),
                }
                model_results: dict[str, Any] = {}
                for name, requested in requested_models.items():
                    if not requested:
                        model_results[name] = {"status": "not_selected"}
                    elif isinstance(parsed, dict) and isinstance(parsed.get(name), dict):
                        result = parsed[name]
                        if result.get("success") is not True:
                            status = "unavailable"
                        elif str(result.get("backend", "")).lower() == "openvino":
                            status = "ready"
                        else:
                            status = "fallback"
                        model_results[name] = {
                            "status": status,
                            "model": result.get("model"),
                            "backend": result.get("backend"),
                            "device": result.get("device"),
                        }
                    else:
                        model_results[name] = {"status": "unavailable"}
                attempted = [m for m in model_results.values() if m.get("status") != "not_selected"]
                all_ready = bool(attempted) and all(m.get("status") == "ready" for m in attempted)
                openvino_model_report = {
                    "status": (
                        "ready" if all_ready
                        else "fallback" if attempted and all(m.get("status") in {"ready", "fallback"} for m in attempted)
                        else "unavailable" if attempted
                        else "not_selected"
                    ),
                    "models": model_results,
                }
                openvino_preload_ok = all_ready if attempted else None
            except Exception as exc:
                openvino_model_report["status"] = "unavailable"
                openvino_preload_ok = False
                log(f"WARNING: OpenVINO model preload failed: {exc}")
    elif needs_openvino:
        openvino_model_report["status"] = "disabled"

    if needs_openvino and not openvino_ok and features.get("install_local_nlp_dependencies", True):
        # CPU fallback is part of the OpenVINO reliability contract. Install its
        # lightweight SentenceTransformers dependency even when Intel acceleration
        # was explicitly disabled, auto-install was disabled, or the optional
        # OpenVINO install failed. Users can still disable both dependency installers.
        install_requirements(hub_python, install_dir / "requirements-local-nlp.txt", optional=True)

    laya_cfg = cfg.get("laya", {}) if isinstance(cfg.get("laya", {}), dict) else {}
    laya_runtime_cfg = laya_cfg.get("runtime", {}) if isinstance(laya_cfg.get("runtime", {}), dict) else {}
    laya_checkpoint_path = str(laya_runtime_cfg.get("checkpoint_path", "") or "").strip()
    laya_local_dir_present = bool(laya_checkpoint_path and Path(laya_checkpoint_path).is_dir())
    laya_hf_repo = str(laya_runtime_cfg.get("hf_repo_id", "") or "").strip()
    laya_hf_rev = str(laya_runtime_cfg.get("hf_revision", "") or "").strip()
    laya_hf_sha256 = laya_runtime_cfg.get("hf_sha256")
    laya_hf_configured = bool(
        laya_hf_repo and laya_hf_rev and isinstance(laya_hf_sha256, dict) and bool(laya_hf_sha256)
    )
    laya_checkpoint_configured = bool(laya_checkpoint_path or laya_hf_configured)
    laya_hf_cached = False
    laya_integrity_verified = False
    if laya_local_dir_present:
        expected_hashes = laya_runtime_cfg.get("expected_sha256") or (laya_hf_sha256 if isinstance(laya_hf_sha256, dict) else None)
        if isinstance(expected_hashes, dict) and expected_hashes:
            try:
                chk_dir = Path(laya_checkpoint_path)
                mismatches = [
                    rel for rel, digest in expected_hashes.items()
                    if not (chk_dir / rel).is_file() or hashlib.sha256((chk_dir / rel).read_bytes()).hexdigest() != digest
                ]
                laya_integrity_verified = not mismatches
            except Exception:
                laya_integrity_verified = False
        else:
            laya_integrity_verified = True
    elif laya_hf_configured:
        try:
            from local_ai_hub.trained_models import download_trained_model
            snapshot = download_trained_model(
                laya_hf_repo, laya_hf_rev, laya_hf_sha256, allow_download=False,
            )
            laya_hf_cached = bool(snapshot and snapshot.is_dir())
            laya_integrity_verified = laya_hf_cached
            if laya_hf_cached and not laya_checkpoint_path:
                laya_checkpoint_path = str(snapshot)
        except Exception:
            laya_hf_cached = False
            laya_integrity_verified = False

    laya_checkpoint_exists = bool(laya_local_dir_present or laya_hf_cached)
    laya_runtime_selected = bool(setup_choices.get("laya_runtime", False))
    laya_runtime_ok: bool | None = None
    if laya_runtime_selected:
        laya_python = ensure_venv(install_dir / "tool-envs" / "laya")
        laya_runtime_ok = install_requirements(
            laya_python, install_dir / "requirements-laya-runtime.txt", optional=True
        )
        if laya_runtime_ok:
            cleanup = run(
                [str(hub_python), "-m", "pip", "uninstall", "-y", "laya", "vegaml"],
                check=False, timeout=300, capture=True,
            )
            if cleanup is None or cleanup.returncode != 0:
                laya_runtime_ok = False
                log("WARNING: could not remove isolated Laya packages from the shared Hub environment.")

    optional_runtime_extras: dict[str, dict[str, Any]] = {}
    for choice, requirement in (
        ("ast_index", "requirements-ast-index.txt"),
        ("performance", "requirements-performance.txt"),
        ("profiling", "requirements-profiling.txt"),
    ):
        selected = bool(setup_choices.get(choice, False))
        installed = (
            install_requirements(hub_python, install_dir / requirement, optional=True)
            if selected else None
        )
        optional_runtime_extras[choice] = {
            "selected": selected,
            "status": "installed" if installed is True else "failed" if selected else "not_selected",
        }

    selected_agents = cfg.get("agents", {})
    if not args.skip_agent_config and bool(setup_cfg.get("install_agent_configs", True)) and include_companion:
        _add_runtime_site_packages(hub_python)
        if selected_agents.get("codex", True):
            codex = shutil.which("codex")
            if codex:
                from local_ai_hub.repo_plan.host_hooks import ensure_codex_superpowers
                try:
                    dependency = ensure_codex_superpowers(Path(codex).absolute(), repo_root=install_dir)
                except (OSError, ValueError) as exc:
                    dependency = {"success": False, "error": str(exc)}
                if not dependency.get("success"):
                    log(f"Setup incomplete: Codex Superpowers dependency: {json.dumps(dependency)}")
                    write_setup_failure_report(
                        install_dir, state_dir, stage="codex_superpowers", error=dependency.get("error", "dependency setup failed")
                    )
                    return 1
                log("Codex Superpowers dependency is installed and enabled.")
            else:
                log("Codex was not found on PATH; its Superpowers dependency was not checked.")
        if selected_agents.get("gemini", True):
            gemini = shutil.which("gemini")
            if gemini:
                from local_ai_hub.repo_plan.host_hooks import ensure_gemini_superpowers
                try:
                    dependency = ensure_gemini_superpowers(Path(gemini).absolute(), repo_root=install_dir)
                except (OSError, ValueError) as exc:
                    dependency = {"success": False, "error": str(exc)}
                if not dependency.get("success"):
                    log(f"Setup incomplete: Gemini Superpowers dependency: {json.dumps(dependency)}")
                    write_setup_failure_report(
                        install_dir, state_dir, stage="gemini_superpowers", error=dependency.get("error", "dependency setup failed")
                    )
                    return 1
                log("Gemini Superpowers dependency is present; host activation still requires verification.")
            else:
                log("Gemini CLI was not found on PATH; its Superpowers dependency was not checked.")

    if os.name == "nt":
        has_nvidia = any(str(g.get("vendor", "")).lower() == "nvidia" for g in detected_gpus if isinstance(g, dict))
        has_igpu = any(bool(g.get("integrated")) or "intel" in str(g.get("name", "")).lower() or "radeon" in str(g.get("name", "")).lower() for g in detected_gpus if isinstance(g, dict))
        is_integrated_profile = cfg.get("_hardware", {}).get("profile") == "integrated" or cfg.get("hardware", {}).get("profile") == "integrated"
        ollama_enabled = bool(cfg.get("ollama", {}).get("enabled", False)) if isinstance(cfg.get("ollama", {}), dict) else False
        if ollama_enabled and (has_igpu or is_integrated_profile) and not has_nvidia:
            if not os.environ.get("OLLAMA_VULKAN"):
                try:
                    ps_cmd = "[System.Environment]::SetEnvironmentVariable('OLLAMA_VULKAN', '1', 'User')"
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, timeout=10)
                    os.environ["OLLAMA_VULKAN"] = "1"
                    log("Configured OLLAMA_VULKAN=1 in Windows user environment for iGPU acceleration.")
                except Exception as exc:
                    log(f"Notice: Could not set OLLAMA_VULKAN environment variable: {exc}")

    try:
        ollama_setup_ok = ensure_ollama_for_setup(cfg, install_dir, allow_install=not args.skip_ollama_install)
        ollama_model_report = pull_ollama_models(cfg)
        managed_llama_cpp_selected = llama_cpp_managed_selected(cfg)
        managed_llama_cpp_ok = ensure_llama_cpp_for_setup(cfg)
    except Exception as exc:
        log(f"Setup incomplete: configured model provisioning failed: {exc}")
        write_setup_failure_report(install_dir, state_dir, stage="model_provisioning", error=exc)
        return 1

    service_required = not args.skip_service and bool(setup_cfg.get("install_service", True)) and cfg.get("headless", {}).get("enabled", True)
    service_ok = True
    if service_required:
        service_ok = install_persistent_service(hub_python, install_dir)

    if service_required and not service_ok:
        log("Setup incomplete: service registration failed. Review service-manager output, then rerun install/update with the same verified commit.")
        write_setup_failure_report(
            install_dir, state_dir, stage="service_registration", error="Persistent service registration failed."
        )
        return 1

    try:
        # Cold starts may include managed inference/backend initialization.
        run([str(hub_python), str(install_dir / "tools" / "hubctl.py"), "restart"], check=True, timeout=420)
    except Exception as exc:
        log(f"Setup incomplete: Hub restart before agent configuration failed: {exc}")
        write_setup_failure_report(install_dir, state_dir, stage="hub_restart", error=exc)
        return 1

    agent_config_error: str | None = None
    agent_config_manual_actions: list[str] = []
    agent_config_selected = not args.skip_agent_config and bool(setup_cfg.get("install_agent_configs", True))
    try:
        if agent_config_selected:
            agent_config_manual_actions = configure_agents(
                install_dir, hub_python, serena, cfg,
                include_companion=include_companion,
                agent_components=setup_choices,
            )
        else:
            write_generated_agent_manifests(install_dir, hub_python, serena, cfg)
    except Exception as exc:
        agent_config_error = str(exc)
        log(f"WARNING: agent configuration was incomplete: {exc}")

    try:
        run([str(hub_python), str(install_dir / "tools" / "doctor.py")], check=False, timeout=60)
    except Exception as exc:
        log(f"WARNING: doctor could not complete: {exc}")

    hw = cfg.get("_hardware", {})
    manual_actions: list[str] = []
    manual_actions.extend(agent_config_manual_actions)
    if needs_local_nlp and not features.get("install_local_nlp_dependencies", True):
        manual_actions.append("Local NLP dependencies were disabled; use the installation guide if embeddings or reranking are needed.")
    elif needs_local_nlp and not local_nlp_ok:
        manual_actions.append("Local NLP dependency installation failed; CPU/runtime fallback may be limited.")
    if local_nlp_preload_ok is False:
        manual_actions.append("Hugging Face local NLP model preload failed; check network access and model cache. Enable the saved Hugging Face download choice in the installer to fetch missing models, then follow the recovery guide.")
    elif needs_local_nlp and local_nlp_model_report.get("status") == "skipped":
        manual_actions.append("Hugging Face model preload was skipped; see the recovery guide to download selected models later.")
    if needs_openvino and not install_openvino:
        manual_actions.append("OpenVINO was needed but disabled by configuration or installer choice; CPU fallback remains available.")
    elif needs_openvino and not openvino_ok:
        manual_actions.append("OpenVINO dependencies or model preload failed; use the Intel acceleration guide if required.")
    if openvino_preload_ok is False:
        manual_actions.append("OpenVINO was not the active backend for every selected model (some may have used CPU fallback); check network access, drivers, and model cache. Enable the saved Hugging Face download choice in the installer to fetch missing models, then follow the recovery guide.")
    elif needs_openvino and openvino_model_report.get("status") == "skipped":
        manual_actions.append("OpenVINO model preload was skipped; see the recovery guide to download selected models later.")
    if laya_runtime_selected and laya_runtime_ok is False:
        manual_actions.append("Laya runtime dependencies failed to install; see the Laya recovery steps in the installer guide.")
    if laya_checkpoint_configured and not laya_checkpoint_exists:
        manual_actions.append("The configured Laya checkpoint is missing locally; provide the pinned checkpoint locally or verify the Hugging Face cache and hashes.")
    elif laya_checkpoint_configured and not laya_runtime_selected:
        manual_actions.append("A Laya checkpoint is configured but its optional runtime packages were not selected; enable Laya runtime in the installer wizard if this route is needed.")
    elif laya_runtime_selected and not laya_checkpoint_configured:
        manual_actions.append("Laya runtime packages were selected, but no local or pinned Hugging Face checkpoint is configured.")
    for name, result in optional_runtime_extras.items():
        if result["status"] == "failed":
            manual_actions.append(f"Optional {name.replace('_', '-')} packages failed to install; see the runtime-extra recovery steps in the installation guide.")
    if ollama_model_report["unavailable"]:
        manual_actions.append(
            "Ollama model downloads failed or were unavailable: "
            + ", ".join(ollama_model_report["unavailable"])
            + ". See the recovery guide."
        )
    if not args.skip_token_economy:
        if token_economy_result.get("error"):
            manual_actions.append(
                f"Token Economy setup stopped early: {token_economy_result['error']}. See the recovery guide."
            )
        if token_economy_result.get("dependencies") != "installed":
            manual_actions.append("Token Economy Python dependencies did not install; see the recovery guide.")
        if token_economy_result.get("wrappers") != "installed":
            manual_actions.append("Token Economy command wrappers were not created; see the recovery guide.")
        else:
            manual_actions.append(
                "If newly installed Token Economy commands are not visible, open a new terminal to reload PATH."
            )
        missing_external = [
            name for name, details in token_economy_result.get("external_tools", {}).items()
            if isinstance(details, dict) and details.get("status") == "not_detected_after_install"
        ]
        if missing_external:
            manual_actions.append(
                "Optional CLI tools were not detected after setup (" + ", ".join(missing_external)
                + "); reopen the terminal and follow the recovery guide if still missing."
            )
    if not ollama_setup_ok and ollama_setup_required(cfg):
        manual_actions.append("Ollama setup did not complete although the configured provider requires it.")
    if managed_llama_cpp_selected and not managed_llama_cpp_ok:
        manual_actions.append(
            "Managed llama.cpp or its configured model is not ready; inspect the exact error, "
            "preserve the configured provider, and follow the llama.cpp steps in docs/INSTALLER_RECOVERY.md."
        )
    if not args.skip_tools and bool(setup_cfg.get("install_optional_tools", True)) and bool(cfg.get("code_intelligence", {}).get("serena_enabled", True)) and serena is None:
        manual_actions.append("Serena installation did not complete; rerun setup or follow the external-tool guide.")
    if not args.skip_agent_config and bool(setup_cfg.get("install_agent_configs", True)):
        if agent_config_error:
            manual_actions.append(
                f"Agent MCP/skills/instruction setup failed or was partial: {agent_config_error}. Read the recovery guide."
            )
        else:
            manual_actions.append("Restart configured coding agents so they reload MCP, skills, and instructions.")
    serena_selected = (
        not args.skip_tools
        and bool(setup_cfg.get("install_optional_tools", True))
        and bool(cfg.get("code_intelligence", {}).get("serena_enabled", True))
    )
    agent_names = ("codex", "claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "opencode", "devin")
    agent_manual_actions_by_provider = provider_manual_actions(agent_config_manual_actions)
    agent_component_selection = {
        name: {
            component: bool(
                agent_config_selected
                and cfg.get("agents", {}).get(name, False)
                and setup_choices.get(f"agent_{name}_{component}", True)
                and not (
                    name == "devin"
                    and cfg.get("agents", {}).get("devin_plugin_route", False)
                    and component in {"mcp", "skills"}
                )
                and (
                    component != "instructions"
                    or cfg.get("tool_policy", {}).get("install_global_instructions", True)
                )
            )
            for component in ("mcp", "skills", "instructions")
        }
        for name in agent_names
    }
    agent_component_installation = {
        name: {
            component: provider_setup_component_state(
                selected,
                batch_error=agent_config_error,
                manual_actions=agent_manual_actions_by_provider[name],
            )
            for component, selected in components.items()
        }
        for name, components in agent_component_selection.items()
    }
    agent_setup_selection = {
        name: bool(
            agent_config_selected
            and cfg.get("agents", {}).get(name, False)
        )
        for name in agent_names
    }
    hook_setup_agents = {"claude", "gemini", "antigravity", "cursor", "windsurf", "copilot", "devin"}
    agent_hook_installation: dict[str, str] = {}
    for name in agent_names:
        if name in hook_setup_agents:
            selected = agent_setup_selection[name] and bool(setup_choices.get(f"agent_{name}_hooks", True))
            agent_hook_installation[name] = provider_setup_component_state(
                selected,
                batch_error=agent_config_error,
                manual_actions=agent_manual_actions_by_provider[name],
            )
        elif name == "codex":
            agent_hook_installation[name] = (
                "bundled_in_plugin_not_installed_by_setup" if agent_setup_selection[name]
                else "not_selected"
            )
        elif name == "opencode":
            agent_hook_installation[name] = "not_separate_from_plugin"
        else:
            agent_hook_installation[name] = "not_supported_by_hub_setup"
    agent_plugin_installation: dict[str, str] = {}
    for name in agent_names:
        if name == "opencode":
            selected = agent_setup_selection[name] and bool(setup_choices.get("agent_opencode_plugin", True))
            agent_plugin_installation[name] = provider_setup_component_state(
                selected,
                batch_error=agent_config_error,
                manual_actions=agent_manual_actions_by_provider[name],
            )
        elif name == "codex":
            agent_plugin_installation[name] = "bundled_external_installation_and_trust_not_probed"
        elif name == "devin":
            agent_plugin_installation[name] = (
                "selected_for_manual_install" if agent_setup_selection[name]
                and cfg.get("agents", {}).get("devin_plugin_route", False)
                else "bundled_external_installation_and_trust_not_probed"
            )
        elif name in {"claude", "gemini", "antigravity", "cursor", "copilot", "devin"}:
            agent_plugin_installation[name] = "bundled_external_installation_and_trust_not_probed"
        else:
            agent_plugin_installation[name] = "not_supported_by_hub_setup"
    provider_status = provider_integration_status(
        agent_names, agent_setup_selection, agent_component_installation,
        agent_hook_installation, agent_plugin_installation,
        batch_error=agent_config_error,
        manual_actions_by_provider=agent_manual_actions_by_provider,
    )
    selected_components = {
        "ollama_models": bool(
            not args.skip_model_pull
            and features.get("pull_models_during_setup", True)
            and ollama_setup_required(cfg)
        ),
        "managed_llama_cpp": managed_llama_cpp_selected,
        "local_nlp": bool(setup_choices.get("local_nlp")),
        "openvino": bool(setup_choices.get("openvino")),
        "download_hf_models": bool(setup_choices.get("download_hf_models", False)),
        "laya_runtime": laya_runtime_selected,
        "ast_index": bool(setup_choices.get("ast_index")),
        "performance": bool(setup_choices.get("performance")),
        "profiling": bool(setup_choices.get("profiling")),
        "serena": serena_selected,
        "token_economy": not args.skip_token_economy,
        "agent_config": bool(
            not args.skip_agent_config and setup_cfg.get("install_agent_configs", True)
        ),
        "service": bool(setup_choices.get("service")),
        "companion_skills": bool(setup_choices.get("companion_skills")),
        "agents": {
            name: bool(
                not args.skip_agent_config
                and setup_cfg.get("install_agent_configs", True)
                and cfg.get("agents", {}).get(name, False)
            )
            for name in agent_names
        },
        "agent_components": agent_component_selection,
    }
    if embedding_reset_backup:
        try:
            discard_embedding_reset_backup(state_dir, embedding_reset_backup)
            embedding_reset_backup = None
        except (OSError, RuntimeError, ValueError) as exc:
            log(f"Setup incomplete: v8 embedding reset backup cleanup failed: {exc}")
            write_setup_failure_report(install_dir, state_dir, stage="embedding_reset_cleanup", error=exc)
            return 1

    install_report = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "completed_with_manual_steps" if manual_actions else "completed",
        "install_dir": str(install_dir),
        "state_dir": str(expand(str(cfg.get("server", {}).get("state_dir", install_dir / "state")))),
        "profile": hw.get("profile", "unknown"),
        "model_provider": cfg.get("models", {}).get("provider", "configured"),
        "selected": selected_components,
        "model_provisioning": {
            "ollama_setup_ok": ollama_setup_ok,
            "ollama_models": ollama_model_report,
            "ollama_model_pull_failures": ollama_model_report["unavailable"],
            "fp4_model_catalog": fp4_model_catalog,
            "managed_llama_cpp_selected": managed_llama_cpp_selected,
            "managed_llama_cpp_ok": managed_llama_cpp_ok,
            "hugging_face_model_preload": local_nlp_preload_ok,
            "hugging_face_models": local_nlp_model_report,
            "openvino_model_preload": openvino_preload_ok,
            "hugging_face_downloads_enabled": bool(setup_choices.get("download_hf_models", False)),
            "openvino_models": openvino_model_report,
            "laya_runtime_dependencies": laya_runtime_ok,
            "laya_checkpoint": {
                "configured": laya_checkpoint_configured,
                "status": "present" if laya_checkpoint_exists else ("missing" if laya_checkpoint_configured else "not_configured"),
                "directory_present": laya_local_dir_present,
                "hf_declared": laya_hf_configured,
                "hf_cached": laya_hf_cached,
                "path": laya_checkpoint_path if (laya_local_dir_present or laya_hf_cached) else None,
                "revision": laya_runtime_cfg.get("revision") or (laya_hf_rev if laya_hf_configured else None),
                "integrity_check": "verified" if laya_integrity_verified else ("failed" if (laya_local_dir_present and not laya_integrity_verified) else "not_run"),
            },
            "optional_runtime_extras": optional_runtime_extras,
        },
        "token_economy": token_economy_result,
        "installed": {
            "token_economy": (
                "installed"
                if token_economy_result.get("dependencies") == "installed"
                and token_economy_result.get("wrappers") == "installed"
                else token_economy_result.get("status", "partial")
            ),
            "local_nlp": "installed" if local_nlp_ok else ("not_needed" if not needs_local_nlp else "not_installed"),
            "openvino": "installed" if openvino_ok else ("not_needed" if not needs_openvino else "not_installed"),
            "laya_runtime": (
                "installed" if laya_runtime_ok is True
                else "failed" if laya_runtime_selected
                else "not_selected"
            ),
            "ast_index": optional_runtime_extras["ast_index"]["status"],
            "performance": optional_runtime_extras["performance"]["status"],
            "profiling": optional_runtime_extras["profiling"]["status"],
            "managed_llama_cpp": (
                "ready" if managed_llama_cpp_selected and managed_llama_cpp_ok
                else "failed" if managed_llama_cpp_selected
                else "not_selected"
            ),
            "serena": (
                str(serena) if serena is not None
                else "failed" if serena_selected
                else "not_selected"
            ),
            "service": (
                "installed" if service_required and service_ok
                else "failed" if service_required
                else "not_selected"
            ),
            "agent_config": (
                "failed_or_partial" if agent_config_error
                else "configured" if agent_config_selected
                else "not_selected"
            ),
            "agent_config_error": agent_config_error,
            "agent_components": agent_component_installation,
        },
        "provider_integration": provider_status,
        "agent_config_unattributed_manual_actions": agent_manual_actions_by_provider["unattributed"],
        "state_migration": migration_result,
        "manual_actions": manual_actions,
        "recovery_guide": str(SOURCE_ROOT / "docs" / "INSTALLER_RECOVERY.md"),
    }
    try:
        write_install_manifest(install_dir)
    except (OSError, ValueError) as exc:
        log(f"Setup incomplete: install ownership marker could not be written: {exc}")
        write_setup_failure_report(install_dir, state_dir, stage="install_ownership", error=exc)
        return 1
    try:
        report_path = write_setup_report(install_dir, install_report)
        log(f"Installer report: {report_path}")
    except OSError as exc:
        log(f"WARNING: installer report could not be saved: {exc}")
    if manual_actions:
        log(f"Manual actions: {SOURCE_ROOT / 'docs' / 'INSTALLER_RECOVERY.md'}")
    log(f"Setup complete. Detected profile: {hw.get('profile', 'unknown')} ({hw.get('os', '')}/{hw.get('arch', '')}).")
    log("Restart configured agents so they reload the Local AI Hub MCP server and tool-first policy.")
    log("Dashboard: http://127.0.0.1:11435/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
