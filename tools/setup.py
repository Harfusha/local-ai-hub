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
_install_ownership_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_install_ownership", Path(__file__).with_name("install_ownership.py")
)
if _install_ownership_spec is None or _install_ownership_spec.loader is None:
    raise ImportError("could not load sibling install_ownership.py")
_install_ownership_module = importlib.util.module_from_spec(_install_ownership_spec)
_install_ownership_spec.loader.exec_module(_install_ownership_module)
write_install_manifest = _install_ownership_module.write_install_manifest
record_external_block = _install_ownership_module.record_external_block
assert_external_block_writable = _install_ownership_module.assert_external_block_writable
record_external_json_key = _install_ownership_module.record_external_json_key
assert_external_json_key_writable = _install_ownership_module.assert_external_json_key_writable
record_external_json_list_item = _install_ownership_module.record_external_json_list_item
record_external_json_container = _install_ownership_module.record_external_json_container
record_external_file = _install_ownership_module.record_external_file
assert_external_file_writable = _install_ownership_module.assert_external_file_writable
forget_external_record = _install_ownership_module.forget_external_record
_ACTIVE_INSTALL_ROOT: Path | None = None

_update_transaction_spec = importlib.util.spec_from_file_location(
    "_local_ai_hub_update_transaction", Path(__file__).with_name("update_transaction.py")
)
if _update_transaction_spec is None or _update_transaction_spec.loader is None:
    raise ImportError("could not load sibling update_transaction.py")
_update_transaction_module = importlib.util.module_from_spec(_update_transaction_spec)
_update_transaction_spec.loader.exec_module(_update_transaction_module)
replace_install_payload = _update_transaction_module.replace_install_payload
stop_existing_runtime = _update_transaction_module.stop_existing_runtime
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.config import load_config as load_hub_config  # noqa: E402
from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_managed_selected  # noqa: E402
from local_ai_hub.generator import generate_global_policy, generate_token_economy_policy, write_all_generated  # noqa: E402
_state_migrations_spec = importlib.util.spec_from_file_location("_local_ai_hub_state_migrations", Path(__file__).with_name("state_migrations.py"))
if _state_migrations_spec is None or _state_migrations_spec.loader is None:
    raise ImportError("could not load sibling state_migrations.py")
_state_migrations_module = importlib.util.module_from_spec(_state_migrations_spec)
_state_migrations_spec.loader.exec_module(_state_migrations_module)
run_state_migrations = _state_migrations_module.run_state_migrations
inspect_state_migration_path = _state_migrations_module.inspect_state_migration_path

MARKER_BEGIN = "# BEGIN LOCAL AI HUB MANAGED"
MARKER_END = "# END LOCAL AI HUB MANAGED"
GLOBAL_POLICY_BEGIN = "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->"
GLOBAL_POLICY_END = "<!-- END LOCAL AI HUB TOOL POLICY -->"
TOKEN_ECONOMY_POLICY_BEGIN = "<!-- BEGIN TOKEN ECONOMY POLICY -->"
TOKEN_ECONOMY_POLICY_END = "<!-- END TOKEN ECONOMY POLICY -->"
AUTOSETUP_BEGIN = "<!-- BEGIN TOKEN ECONOMIZER AUTOSETUP -->"
AUTOSETUP_END = "<!-- END TOKEN ECONOMIZER AUTOSETUP -->"


def build_global_policy(cfg: dict[str, Any]) -> str:
    """Build a config-aware LOCAL AI HUB TOOL POLICY block.

    Only mentions tools, backends and model names that are actually enabled in
    the given merged config.  The returned string includes the BEGIN/END markers
    so callers can embed it verbatim into AGENTS.md / CLAUDE.md / GEMINI.md.
    """
    return generate_global_policy(cfg)


# Keep a module-level default for callers that do not have a config available
# (e.g. tests or tools that import setup.py directly).  The real policy is
# always built via build_global_policy(cfg) at setup time.
_DEFAULT_POLICY_CFG: dict[str, Any] = {}
GLOBAL_POLICY = build_global_policy(_DEFAULT_POLICY_CFG)
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
    report = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "requires_manual_migration",
        "install_dir": str(install_dir),
        "state_dir": str(state_dir),
        "selected": selected or {},
        "migration": {"stage": stage, "error": str(error)},
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


def copy_install_tree(
    install_dir: Path, config_source: Path, *,
    before_commit: Callable[[], tuple[bool, str]] | None = None,
    after_swap: Callable[[], tuple[bool, str]] | None = None,
) -> bool:
    file_names = (
        "requirements-core.txt", "requirements-token-economy.txt", "requirements-local-nlp.txt", "requirements-openvino.txt",
        "requirements-laya-runtime.txt", "requirements-ast-index.txt", "requirements-performance.txt", "requirements-profiling.txt",
        "defaults.toml", "config.toml.example", "pyproject.toml",
        "README.md", "FEATURES.md", "AGENTS.md", "LICENSE", "CHANGELOG.md", "THIRD_PARTY.md",
        "RELEASE.json", "CONTRIBUTING.md", "SECURITY.md", "install.ps1", "install.sh",
    )
    success, detail = replace_install_payload(
        UPDATE_SOURCE_ROOT, install_dir, config_source, file_names,
        before_commit=before_commit, after_swap=after_swap,
    )
    log(detail if success else f"ERROR: {detail}")
    return success


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
                            result[path.relative_to(directory).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
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
    policy = f"""{ANTIGRAVITY_POLICY_BEGIN}
## Antigravity automatic skill activation

At the start of each conversation, read `~/.gemini/skills/using-superpowers/SKILL.md` and follow the applicable Superpowers workflow. For coding and repository tasks, read `~/.gemini/skills/local-ai-orchestrator/SKILL.md` and use available Local AI Hub MCP tools. Call applicable endpoints directly from the main agent; managing native subagents does not replace Hub retrieval, artifact, or coordination calls. For every non-trivial repository task, start with indexed `local_ai_repo` evidence; use `local_ai_artifact` for exact source after locating it; use `local_ai_coord` for durable task/verification state, memory, or shared edits; use `local_ai_rag` when indexed retrieval cannot answer; use exposed `local_ai_task` semantic actions for matching bounded review, reasoning, exploration or compression tasks after evidence. Consider `local_ai_work` only for explicitly requested closed delegation that passes quality and permission checks. Keep tests/builds on the host-native command tool. Read `~/.gemini/skills/caveman/SKILL.md` and use its ultra mode while preserving technical facts and clarity. For substantial multi-step work, read `~/.gemini/skills/plan-led-work/SKILL.md`: use Superpowers for specifications; use Local AI Hub `plan_reconcile_steering` for changed requirements, `task_checkpoint`/`plan_bind_task` for synced progress and recovery, `session_briefing` for resumption, and the receipt gate for completion when exposed by the active MCP schema. If an action is absent, use the supported project-plan interface or report the precise blocker; never edit plan storage directly. Reuse valid evidence instead of repeating full audits. If the user says `normal mode` or `stop caveman`, stop Caveman style for the rest of the conversation unless they explicitly re-enable it.
If any required skill or the Hub is unavailable, report the precise limitation and use the allowed fallback; do not claim activation from installation alone.
{ANTIGRAVITY_POLICY_END}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(ANTIGRAVITY_POLICY_BEGIN) + r".*?" + re.escape(ANTIGRAVITY_POLICY_END) + r"(?:\r?\n)*", re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        raise RuntimeError(f"multiple Antigravity policy blocks found in {path}")
    preimage = matches[0].group(0).rstrip("\r\n") if matches else None
    marker = {"begin": ANTIGRAVITY_POLICY_BEGIN, "end": ANTIGRAVITY_POLICY_END}
    if preimage is not None and _ACTIVE_INSTALL_ROOT is not None:
        assert_external_block_writable(_ACTIVE_INSTALL_ROOT, path, owner_marker=marker, current_block=preimage)
    unmanaged = pattern.sub("", text)
    separator = "" if not unmanaged else "\n" if unmanaged.startswith("\n") else "\n\n"
    updated = policy + separator + unmanaged
    if updated != text:
        backup(path, backup_enabled)
        path.write_bytes(updated.encode("utf-8"))
        if _ACTIVE_INSTALL_ROOT is not None:
            record_external_block(
                _ACTIVE_INSTALL_ROOT, path, kind="text_block", owner_marker=marker,
                preimage=preimage, postimage=policy,
            )


def get_user_homes() -> list[Path]:
    """Discover all user and MultiGravity profile home directories."""
    homes: list[Path] = []
    seen: set[Path] = set()

    def add_home(p: Path) -> None:
        try:
            resolved = p.resolve()
            if resolved not in seen and p.exists() and p.is_dir():
                seen.add(resolved)
                homes.append(p)
        except Exception:
            pass

    cur_home = Path.home()
    add_home(cur_home)

    if os.name == "nt":
        username = os.environ.get("USERNAME")
        system_drive = os.environ.get("SystemDrive", "C:")
        if username:
            add_home(Path(f"{system_drive}/Users/{username}"))
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            add_home(Path(userprofile))

    # MultiGravity discovery: search cur_home and its ancestors
    mg_profiles_dir: Path | None = None
    for p in [cur_home, *cur_home.parents]:
        cand = p / "Desktop" / "Multigravity" / "profiles"
        if cand.is_dir():
            mg_profiles_dir = cand
            add_home(p)
            break
        if p.name.lower() == "profiles" and p.parent.name.lower() == "multigravity":
            mg_profiles_dir = p
            for anc in p.parents:
                if (anc / "Desktop").is_dir():
                    add_home(anc)
                    break
            break

    env_mg = os.environ.get("MULTIGRAVITY_PROFILES") or os.environ.get("MULTIGRAVITY_HOME")
    if env_mg:
        p_env = Path(env_mg)
        if p_env.name.lower() == "profiles" and p_env.is_dir():
            mg_profiles_dir = p_env
        elif (p_env / "profiles").is_dir():
            mg_profiles_dir = p_env / "profiles"

    if mg_profiles_dir and mg_profiles_dir.is_dir():
        for child in mg_profiles_dir.iterdir():
            if child.is_dir():
                target = child / "home" if (child / "home").is_dir() else child
                add_home(target)

    return homes


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
    container = data.setdefault(container_key, {})
    if not isinstance(container, dict):
        raise RuntimeError(f"{container_key} is not an object in {path}")
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
    if _ACTIVE_INSTALL_ROOT is not None and not owned_writes:
        return
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        for name, preimage, postimage in owned_writes:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container=container_key, key=name,
                preimage=preimage, postimage=postimage,
            )
    log(f"MCP config updated: {path}")


def json_mcp_merge(path: Path, servers: dict[str, dict[str, Any]], backup_enabled: bool) -> None:
    json_server_merge(path, servers, backup_enabled, container_key="mcpServers")


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
    json_mcp_merge(path, build_mcp_entries(install_dir, hub_python, serena, "gemini", cfg), backup_enabled)
    if not bool(cfg.get("code_intelligence", {}).get("direct_agent_mcp", False)):
        prune_direct_code_intelligence(path, serena, backup_enabled)


def sync_antigravity_config_json(path: Path, backup_enabled: bool) -> None:
    """Ensure Antigravity global permissions pre-approve Local AI Hub MCP tools to avoid interactive prompts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        backup(path, backup_enabled)
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
            if raw_text:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    data = parsed
        except Exception as exc:
            log(f"WARNING: could not parse {path}: {exc}")

    if "userSettings" in data and not isinstance(data["userSettings"], dict):
        log(f"WARNING: preserving non-object userSettings in {path}")
        return
    user_settings_created = "userSettings" not in data
    user_settings = data.setdefault("userSettings", {})
    owned_keys: list[tuple[str, str, Any]] = []
    defaults = {
        "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER",
        "enableTerminalSandbox": False,
        "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_ALLOW",
        "permissionPreset": "AGENT_PERMISSION_PRESET_TURBO",
    }
    for key, value in defaults.items():
        if key not in user_settings:
            user_settings[key] = value
            owned_keys.append(("userSettings", key, value))

    if "globalPermissionGrants" in user_settings and not isinstance(user_settings["globalPermissionGrants"], dict):
        log(f"WARNING: preserving non-object globalPermissionGrants in {path}")
        return
    grants_created = "globalPermissionGrants" not in user_settings
    grants = user_settings.setdefault("globalPermissionGrants", {})
    if "allow" in grants and not isinstance(grants["allow"], list):
        log(f"WARNING: preserving non-list globalPermissionGrants.allow in {path}")
        return
    allow_created = "allow" not in grants
    allow_list = grants.setdefault("allow", [])

    required_grants = [
        "mcp(local-ai/*)",
        "mcp(local-ai)",
        "mcp(local_ai/*)",
        "mcp(local_ai)",
        "mcp(local-ai/local_ai_status)",
        "mcp(local-ai/local_ai_coord)",
        "mcp(local-ai/local_ai_repo)",
        "mcp(local-ai/local_ai_task)",
        "mcp(local-ai/local_ai_rag)",
        "mcp(local-ai/local_ai_work)",
        "mcp(local-ai/local_ai_artifact)",
        "mcp(local_ai/local_ai_status)",
        "mcp(local_ai/local_ai_coord)",
        "mcp(local_ai/local_ai_repo)",
        "mcp(local_ai/local_ai_task)",
        "mcp(local_ai/local_ai_rag)",
        "mcp(local_ai/local_ai_work)",
        "mcp(local_ai/local_ai_artifact)",
    ]
    owned_grants: list[str] = []
    for grant in required_grants:
        if grant not in allow_list:
            allow_list.append(grant)
            owned_grants.append(grant)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if _ACTIVE_INSTALL_ROOT is not None:
        if user_settings_created:
            record_external_json_container(_ACTIVE_INSTALL_ROOT, path, container_path="userSettings", container_type="object")
        if grants_created:
            record_external_json_container(_ACTIVE_INSTALL_ROOT, path, container_path="userSettings.globalPermissionGrants", container_type="object")
        if allow_created:
            record_external_json_container(_ACTIVE_INSTALL_ROOT, path, container_path="userSettings.globalPermissionGrants.allow", container_type="list")
        for container_name, key, value in owned_keys:
            record_external_json_key(
                _ACTIVE_INSTALL_ROOT, path, container=container_name, key=key, preimage=None, postimage=value,
            )
        for grant in owned_grants:
            record_external_json_list_item(
                _ACTIVE_INSTALL_ROOT, path,
                container="userSettings.globalPermissionGrants.allow", item=grant,
            )
    log(f"Antigravity permissions configured: {path}")


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
                if isinstance(parsed, dict):
                    data = parsed
        except Exception as exc:
            log(f"WARNING: could not parse {path}: {exc}")

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
) -> None:
    """Configure a single .gemini root (skills, instructions, MCP configs, permissions, schemas)."""
    gemini_dir.mkdir(parents=True, exist_ok=True)
    if _agent_component_enabled(agent_components, "gemini", "skills"):
        install_agent_skills(install_dir, gemini_dir / "skills", include_companion=include_companion)
        install_agent_skills(install_dir, gemini_dir / "config" / "skills", include_companion=include_companion)

    if include_companion and _agent_component_enabled(agent_components, "gemini", "skills"):
        try:
            install_superpowers_skills(gemini_dir / "skills", install_dir / ".local-ai-hub-superpowers" / ".local-ai-hub-skill-ownership.json")
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            log(f"ERROR: Antigravity Superpowers installation failed: {exc}")
            raise RuntimeError(f"Antigravity Superpowers installation failed: {exc}") from exc

    if (
        cfg.get("tool_policy", {}).get("install_global_instructions", True)
        and _agent_component_enabled(agent_components, "gemini", "instructions")
    ):
        doc = gemini_dir / "GEMINI.md"
        merge_global_policy(doc, backup_enabled, cfg=cfg)
        merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        if bool(cfg.get("setup", {}).get("install_antigravity_style_policy", False)):
            merge_antigravity_skill_policy(gemini_dir / "AGENTS.md", backup_enabled)
            merge_antigravity_skill_policy((project_root or Path.cwd()) / "AGENTS.md", backup_enabled)

    if _agent_component_enabled(agent_components, "gemini", "mcp"):
        json_mcp_merge(gemini_dir / "settings.json", build_mcp_entries(install_dir, hub_python, serena, "gemini", cfg), backup_enabled)
        sync_antigravity_mcp_config(
            gemini_dir / "config" / "mcp_config.json",
            install_dir, hub_python, serena, cfg, backup_enabled,
        )
        sync_antigravity_config_json(
            gemini_dir / "config" / "config.json",
            backup_enabled,
        )


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
        )
    finally:
        _ACTIVE_INSTALL_ROOT = previous_root
        sync_antigravity_hooks_json(
            gemini_dir / "config" / "hooks.json",
            install_dir, hub_python, backup_enabled,
        )

    antigravity_mcp = gemini_dir / "antigravity" / "mcp" / "local-ai"
    if _agent_component_enabled(agent_components, "gemini", "mcp") and (
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
    if preimage is not None and _ACTIVE_INSTALL_ROOT is not None:
        assert_external_block_writable(_ACTIVE_INSTALL_ROOT, path, owner_marker=owner_marker, current_block=preimage)
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
            "default_tools_approval_mode": "auto",
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


def merge_global_policy(path: Path, backup_enabled: bool, cfg: dict[str, Any] | None = None) -> None:
    policy = build_global_policy(cfg or {})
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
    if preimage is not None and _ACTIVE_INSTALL_ROOT is not None:
        assert_external_block_writable(_ACTIVE_INSTALL_ROOT, path, owner_marker=marker, current_block=preimage)
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
    owner_marker = {"begin": "---", "end": "---"}
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
    if preimage is not None and _ACTIVE_INSTALL_ROOT is not None:
        assert_external_block_writable(_ACTIVE_INSTALL_ROOT, path, owner_marker=marker, current_block=preimage)
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


def generate_autosetup_policy(skills_dir: Path) -> str:
    orch_skill = (skills_dir / "local-ai-orchestrator" / "SKILL.md").as_posix()
    tok_skill_path = skills_dir / "token-economizer" / "SKILL.md"
    tok_skill = tok_skill_path.as_posix()
    plan_skill = (skills_dir / "plan-led-work" / "SKILL.md").as_posix()
    return (
        f"{AUTOSETUP_BEGIN}\n"
        "## Local AI Hub, plan-led work, and Token-economizer automatic setup\n\n"
        f"- For every coding or repository task, load and follow `{orch_skill}` to orchestrate Local AI Hub tools before repository discovery, even when the user does not name the skill.\n"
        f"- Load and follow `{tok_skill}` before repository discovery for bounded output limits.\n"
        f"- For substantial multi-step work, load and follow `{plan_skill}`: use Superpowers for specifications; use Hub `plan_reconcile_steering` for changed requirements, `task_checkpoint`/`plan_bind_task` for synced progress and recovery, `session_briefing` for resumption, and authentic receipts for completion when exposed by the active MCP schema. If an action is absent, use the supported project-plan interface or report the precise blocker; never edit plan storage directly. Reuse valid evidence instead of repeating full audits. Report `Done / Next / Blocked` updates at milestones.\n"
        "- Use tools already available in the environment; missing optional setup helpers do not block repository discovery or validation.\n"
        f"{AUTOSETUP_END}"
    )


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
    for key in ["background_code", "fast_code", "heavy_code", "reasoning", "general"]:
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
    selections: dict[str, Any] | None, agent: str, component: str
) -> bool:
    if selections is None:
        return True
    return bool(selections.get(f"agent_{agent}_{component}", True))


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
    if (
        cfg.get("agents", {}).get("codex", True)
        and _agent_component_enabled(agent_components, "codex", "mcp")
        and "url" in codex_entry and not _http_mcp_ready(codex_entry["url"])
    ):
        raise RuntimeError("HTTP MCP transport is not ready; Codex configuration was not changed")
    backup_enabled = bool(cfg.get("setup", {}).get("backup_existing_configs", True))
    agents_cfg = cfg.get("agents", {})
    write_all_generated(cfg, install_dir, hub_python, serena)
    # Cursor and Windsurf discover the shared ~/.agents/skills directory too.
    # Keep that shared tree only when every supported consumer is selected;
    # otherwise install for selected clients in their native skill directory.
    standard_skill_tree_enabled = agents_cfg.get("agent_skills_standard", True) and all(
        agents_cfg.get(name, True)
        and _agent_component_enabled(agent_components, name, "skills")
        for name in ("codex", "cursor", "windsurf")
    )
    if standard_skill_tree_enabled:
        for u_home in get_user_homes():
            install_agent_skills(install_dir, u_home / ".agents" / "skills", include_companion=include_companion)
    if agents_cfg.get("codex", True):
        codex_homes: list[Path] = []
        if os.environ.get("CODEX_HOME"):
            codex_homes.append(Path(os.environ["CODEX_HOME"]))
        for u_home in get_user_homes():
            ch = u_home / ".codex"
            if ch.resolve() not in [p.resolve() for p in codex_homes]:
                codex_homes.append(ch)

        for codex_home in codex_homes:
            if _agent_component_enabled(agent_components, "codex", "skills"):
                install_agent_skills(install_dir, codex_home / "skills", include_companion=include_companion)
            if (
                cfg.get("tool_policy", {}).get("install_global_instructions", True)
                and _agent_component_enabled(agent_components, "codex", "instructions")
            ):
                doc = codex_home / ("AGENTS.override.md" if (codex_home / "AGENTS.override.md").exists() else "AGENTS.md")
                merge_global_policy(doc, backup_enabled, cfg=cfg)
                merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
                merge_autosetup_policy(doc, backup_enabled, codex_home / "skills")
            if _agent_component_enabled(agent_components, "codex", "mcp"):
                codex_mcp_merge(
                    codex_home / "config.toml", codex_entries, backup_enabled,
                    startup_timeout=int(cfg.get("client", {}).get("startup_wait_seconds", 15)) + 15,
                    tool_timeout=int(cfg.get("mcp", {}).get("host_tool_timeout_seconds", 900)),
                )
    if agents_cfg.get("claude", True):
        if _agent_component_enabled(agent_components, "claude", "skills"):
            install_agent_skills(install_dir, Path.home() / ".claude" / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "claude", "instructions")
        ):
            doc = Path.home() / ".claude" / "CLAUDE.md"
            merge_global_policy(doc, backup_enabled, cfg=cfg)
            merge_token_economy_policy(doc, backup_enabled, cfg=cfg)
        if _agent_component_enabled(agent_components, "claude", "mcp"):
            json_mcp_merge(Path.home() / ".claude.json", build_mcp_entries(install_dir, hub_python, serena, "claude", cfg), backup_enabled)
    if agents_cfg.get("gemini", True):
        for u_home in get_user_homes():
            g_dir = u_home / ".gemini"
            if u_home.resolve() == Path.home().resolve() or g_dir.exists() or u_home.exists():
                configure_gemini_instance(
                    g_dir, install_dir, hub_python, serena, cfg, backup_enabled, include_companion,
                    agent_components=agent_components,
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
            else:
                manual_actions.append(
                    f"Cursor rule {cursor_rule} already exists without Local AI Hub markers; "
                    "it was preserved. Move it or merge the Hub instructions manually."
                )
        if _agent_component_enabled(agent_components, "cursor", "mcp"):
            json_mcp_merge(Path.home() / ".cursor" / "mcp.json", build_mcp_entries(install_dir, hub_python, serena, "cursor", cfg), backup_enabled)
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
    if agents_cfg.get("copilot", True):
        copilot_dir = Path.home() / ".copilot"
        if _agent_component_enabled(agent_components, "copilot", "skills"):
            install_agent_skills(install_dir, copilot_dir / "skills", include_companion=include_companion)
        if (
            cfg.get("tool_policy", {}).get("install_global_instructions", True)
            and _agent_component_enabled(agent_components, "copilot", "instructions")
        ):
            merge_global_policy(copilot_dir / "copilot-instructions.md", backup_enabled, cfg=cfg)
            merge_token_economy_policy(copilot_dir / "copilot-instructions.md", backup_enabled, cfg=cfg)
        if _agent_component_enabled(agent_components, "copilot", "mcp"):
            vscode_mcp_merge(Path.home() / ".copilot" / "mcp-config.json", build_mcp_entries(install_dir, hub_python, serena, "copilot", cfg), backup_enabled)

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
    cfg = load_hub_config(str(source))
    install_dir = expand(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub"))
    installed = (install_dir / "config.toml").resolve()
    if explicit is None and installed.exists() and installed != source:
        source = installed
        cfg = load_hub_config(str(source))
    return source, cfg, install_dir

def main() -> int:
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

    def migrate_state_after_swap() -> tuple[bool, str]:
        nonlocal migration_result, migration_error
        try:
            migration_result = run_state_migrations(state_dir)
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
    laya_checkpoint_exists = bool(laya_checkpoint_path and Path(laya_checkpoint_path).is_dir())
    laya_runtime_selected = bool(setup_choices.get("laya_runtime", False))
    laya_runtime_ok: bool | None = None
    if laya_runtime_selected:
        laya_runtime_ok = install_requirements(
            hub_python, install_dir / "requirements-laya-runtime.txt", optional=True
        )

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
        run([str(hub_python), str(install_dir / "tools" / "hubctl.py"), "restart"], check=True, timeout=30)
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
    if laya_checkpoint_path and not laya_checkpoint_exists:
        manual_actions.append("The configured Laya checkpoint directory is missing; provide the pinned checkpoint locally and verify its configured revision and file hashes.")
    elif laya_checkpoint_path and not laya_runtime_selected:
        manual_actions.append("A Laya checkpoint is configured but its optional runtime packages were not selected; enable Laya runtime in the installer wizard if this route is needed.")
    elif laya_runtime_selected and not laya_checkpoint_path:
        manual_actions.append("Laya runtime packages were selected, but no checkpoint is configured; inference needs an absolute checkpoint path, matching revision, and file hashes.")
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
    agent_names = ("codex", "claude", "gemini", "cursor", "windsurf", "copilot")
    agent_component_selection = {
        name: {
            component: bool(
                agent_config_selected
                and cfg.get("agents", {}).get(name, False)
                and setup_choices.get(f"agent_{name}_{component}", True)
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
            component: (
                "failed_or_partial" if selected and agent_config_error
                else "configured_with_manual_steps" if selected and agent_config_manual_actions
                else "configured" if selected
                else "not_selected"
            )
            for component, selected in components.items()
        }
        for name, components in agent_component_selection.items()
    }
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
            "managed_llama_cpp_selected": managed_llama_cpp_selected,
            "managed_llama_cpp_ok": managed_llama_cpp_ok,
            "hugging_face_model_preload": local_nlp_preload_ok,
            "hugging_face_models": local_nlp_model_report,
            "openvino_model_preload": openvino_preload_ok,
            "hugging_face_downloads_enabled": bool(setup_choices.get("download_hf_models", False)),
            "openvino_models": openvino_model_report,
            "laya_runtime_dependencies": laya_runtime_ok,
            "laya_checkpoint": {
                "status": "directory_present" if laya_checkpoint_exists else "missing" if laya_checkpoint_path else "not_configured",
                "path": laya_checkpoint_path or None,
                "revision": laya_runtime_cfg.get("revision"),
                "integrity_check": "not_run",
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
