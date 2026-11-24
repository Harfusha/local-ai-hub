from __future__ import annotations

import ast
import hashlib
import json
import os
import socket
import tempfile
import sys
from contextlib import ExitStack, contextmanager
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest


@pytest.fixture
def expired_sqlite_transaction(monkeypatch):
    from local_ai_hub import sqlite_support

    @contextmanager
    def expire_at_commit(connection, **kwargs):
        kwargs["max_duration_seconds"] = 1.0
        now = 0.0
        clock = SimpleNamespace(**vars(sqlite_support.time))
        clock.monotonic = lambda: now
        with monkeypatch.context() as patch:
            patch.setattr(sqlite_support, "time", clock)
            with sqlite_support.write_transaction(connection, **kwargs) as transaction:
                yield transaction
                now = 2.0

    return expire_at_commit


@pytest.fixture
def mcp_diagnostics_enabled(tmp_path, monkeypatch):
    """Opt into persisted detail only for tests of diagnostic dispatch."""
    from local_ai_hub import mcp_server

    path = tmp_path / "diagnostic-config.toml"
    path.write_text(
        '[local_ai_hub]\nconfig_schema_version=1\n\n[telemetry]\nmode="full"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_server, "CFG", {
        **mcp_server.CFG, "_config_path": str(path),
        "_defaults_path": None, "_runtime_override_path": None,
    })


@pytest.fixture(autouse=True)
def _close_test_owned_background_services():
    """Do not carry test-created observers, pools or Hub loops into later tests."""
    with ExitStack() as resources, pytest.MonkeyPatch.context() as patcher:
        def track(service_type):
            original_init = service_type.__init__
            original_close = service_type.close

            @wraps(original_init)
            def initialize(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                resources.callback(original_close, self)

            patcher.setattr(service_type, "__init__", initialize)

        # Preserve lightweight/import-isolation tests: do not import services here.
        for module_name, type_name in (
            ("local_ai_hub.preprocess", "ProjectPreprocessor"),
            ("local_ai_hub.app", "LocalAIApp"),
        ):
            module = sys.modules.get(module_name)
            service_type = getattr(module, type_name, None)
            if isinstance(service_type, type):
                track(service_type)
        yield

_TEST_PORT_GUARD: socket.socket | None = None
_ORIGINAL_CONFIG_CAPTURED = False
_ORIGINAL_CONFIG_PRESENT = False
_ORIGINAL_CONFIG: str | None = None


def pytest_configure(config):
    """Isolate default config, mode state, and loopback port before collection."""
    global _TEST_PORT_GUARD
    global _ORIGINAL_CONFIG_CAPTURED, _ORIGINAL_CONFIG_PRESENT, _ORIGINAL_CONFIG
    if _ORIGINAL_CONFIG_CAPTURED:
        return
    _ORIGINAL_CONFIG_CAPTURED = True
    _ORIGINAL_CONFIG_PRESENT = "LOCAL_AI_CONFIG" in os.environ
    _ORIGINAL_CONFIG = os.environ.get("LOCAL_AI_CONFIG")
    root = Path(tempfile.mkdtemp(prefix="local-ai-hub-pytest-"))
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        guard.bind(("127.0.0.1", 0))
        port = guard.getsockname()[1]
        config_path = root / "config.toml"
        config_path.write_text(
            "[local_ai_hub]\n"
            "config_schema_version = 1\n\n"
            "[server]\n"
            'bind = "127.0.0.1"\n'
            f"port = {port}\n"
            "auto_start_ollama = false\n"
            "state_dir = " + json.dumps((root / "state").as_posix()) + "\n",
            encoding="utf-8",
        )
        _TEST_PORT_GUARD = guard
        os.environ["LOCAL_AI_CONFIG"] = str(config_path)
    except BaseException:
        guard.close()
        raise


def pytest_unconfigure(config):
    """Restore inherited environment; retain isolated config/state as artifacts."""
    global _TEST_PORT_GUARD, _ORIGINAL_CONFIG_CAPTURED
    if not _ORIGINAL_CONFIG_CAPTURED:
        return
    if _ORIGINAL_CONFIG_PRESENT:
        os.environ["LOCAL_AI_CONFIG"] = _ORIGINAL_CONFIG or ""
    else:
        os.environ.pop("LOCAL_AI_CONFIG", None)
    if _TEST_PORT_GUARD is not None:
        _TEST_PORT_GUARD.close()
        _TEST_PORT_GUARD = None
    _ORIGINAL_CONFIG_CAPTURED = False


def pytest_addoption(parser):
    """Register CLI options for test suite execution control."""
    parser.addoption(
        "--run-all",
        action="store_true",
        default=False,
        help="Explicitly permit running the entire test suite without markers or target paths.",
    )
    parser.addoption(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable result caching and run every selected test.",
    )
    parser.addoption(
        "--test-result-cache",
        action="store_true",
        default=False,
        help="Opt into local pure-unit test result caching; CI, coverage and release always run fresh.",
    )


_HASH_CACHE: dict[Path, str] = {}
_SUITE_SIGNATURE: str | None = None


def _suite_dependency_signature() -> str:
    """Invalidate opt-in result caching on any Hub source, policy or environment change.

    Deliberate over-invalidation is safer than skipping a test whose transitive
    import or shared fixture changed. Never emit the environment into receipts.
    """
    global _SUITE_SIGNATURE
    if _SUITE_SIGNATURE is not None:
        return _SUITE_SIGNATURE
    digest = hashlib.sha256()
    digest.update(repr((sys.version, sys.platform, os.name, sys.executable)).encode())
    digest.update(os.environ.get("PYTHONPATH", "").encode())
    for base in (SRC / "local_ai_hub", ROOT / "tests"):
        if not base.is_dir():
            continue
        # Including all test helpers/fixtures makes indirect imports fail safe.
        for file in sorted(base.rglob("*.py")):
            if "__pycache__" in file.parts:
                continue
            digest.update(file.relative_to(ROOT).as_posix().encode())
            digest.update(_file_hash(file).encode())
    for relative in ("pyproject.toml", "defaults.toml", "config.toml.example"):
        file = ROOT / relative
        if file.is_file():
            digest.update(relative.encode())
            digest.update(_file_hash(file).encode())
    _SUITE_SIGNATURE = digest.hexdigest()
    return _SUITE_SIGNATURE


def _result_cache_enabled(config) -> bool:
    """A local, explicit convenience only; never release or coverage evidence."""
    return bool(
        config.getoption("--test-result-cache", False)
        and not config.getoption("--no-cache", False)
        and not config.getoption("--run-all", False)
        and not os.environ.get("CI")
        and os.environ.get("NO_TEST_CACHE") != "1"
        and os.environ.get("RUN_ALL_TESTS") != "1"
        and os.environ.get("RUN_FULL_SUITE") != "true"
        and not os.environ.get("COVERAGE_FILE")
        and getattr(config, "cache", None) is not None
    )


def _file_hash(path: Path) -> str:
    cached = _HASH_CACHE.get(path)
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        digest = ""
    _HASH_CACHE[path] = digest
    return digest


def _extract_imported_hub_modules(test_path: Path) -> set[str]:
    try:
        tree = ast.parse(test_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("local_ai_hub."):
                    parts = alias.name.split(".")
                    if len(parts) > 1:
                        modules.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("local_ai_hub."):
                parts = node.module.split(".")
                if len(parts) > 1:
                    modules.add(parts[1])
            elif node.module == "local_ai_hub":
                for alias in node.names:
                    modules.add(alias.name)
    return modules


def _test_item_signature(item) -> str:
    test_path = Path(str(item.fspath))
    th = _file_hash(test_path)
    conftest_path = ROOT / "tests" / "conftest.py"
    cfgh = _file_hash(conftest_path) if conftest_path.exists() else ""
    modules = _extract_imported_hub_modules(test_path)
    mod_hashes: list[str] = []
    hub_pkg = SRC / "local_ai_hub"
    if hub_pkg.is_dir():
        for mod in sorted(modules):
            sp = hub_pkg / f"{mod}.py"
            if sp.exists():
                mod_hashes.append(f"{mod}={_file_hash(sp)}")
        stem = test_path.stem.removeprefix("test_")
        direct_sp = hub_pkg / f"{stem}.py"
        if direct_sp.exists() and f"{stem}=" not in mod_hashes:
            mod_hashes.append(f"{stem}={_file_hash(direct_sp)}")
    return f"{th}:{cfgh}:{_suite_dependency_signature()}:" + ",".join(mod_hashes)


def _is_targeted_run(config) -> bool:
    """Determine whether the invocation targets a subset or attempts a full-suite run."""
    if config.option.collectonly or config.getoption("--run-all", False):
        return True
    if os.environ.get("RUN_FULL_SUITE") == "true" or os.environ.get("RUN_ALL_TESTS") == "1":
        return True
    if config.option.markexpr or config.option.keyword:
        return True

    raw_args = list(getattr(config.invocation_params, "args", ())) or sys.argv[1:]
    file_targets = []
    skip_next = False
    for arg in raw_args:
        if skip_next:
            skip_next = False
            continue
        if arg in ("-c", "-o", "-m", "-k", "-p", "--override-ini", "--rootdir", "--confcutdir"):
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        normalized = arg.replace("\\", "/").rstrip("/")
        file_targets.append(normalized)

    # If any specific non-root target was passed (e.g. child_dir in isolated tests or tests/unit)
    if any(t not in ("tests", ".") for t in file_targets):
        return True

    return False


def pytest_sessionstart(session):
    """Enforce test execution guard before expensive 17,500+ test collection."""
    if not _is_targeted_run(session.config):
        raise pytest.UsageError(
            "Spuštění všech 17 500+ testů bez filtru je zakázáno!\n"
            "Vyberte testy podle kategorie, rychlosti nebo cesty:\n"
            "  - Podle tématu: pytest -m rag, pytest -m preprocess, pytest -m models, pytest -m training\n"
            "  - Podle odvětví: pytest -m agent, pytest -m http, pytest -m mcp, pytest -m repo, pytest -m automation\n"
            "  - Podle rychlosti: pytest -m fast, pytest -m critical, pytest -m slow\n"
            "  - Konkrétní soubor/složka: pytest tests/unit/test_rag.py, pytest tests/unit/\n"
            "  - Všechny testy (pokud opravdu chcete): pytest --run-all (nebo RUN_ALL_TESTS=1)"
        )


def pytest_collection_modifyitems(config, items):
    """Categorize tests with domain/speed markers."""
    for item in items:
        nodeid = item.nodeid.replace("\\", "/").lower()
        path = "/" + nodeid.partition("::")[0].lstrip("/")

        # Speed / execution layer
        if "/acceptance/" in path or "acceptance" in nodeid:
            item.add_marker(pytest.mark.acceptance)
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)
        elif "/unit/" in path:
            item.add_marker(pytest.mark.unit)
            item.add_marker(pytest.mark.fast)
        else:
            if any(k in path for k in ("subprocesses", "sleep", "daemon", "timeout_cleanup")):
                item.add_marker(pytest.mark.slow)
            else:
                item.add_marker(pytest.mark.fast)

        # Critical / audit / security
        if any(k in path or k in nodeid for k in ("critical", "security", "auth", "audit", "rollback", "quarantine", "fence")):
            item.add_marker(pytest.mark.critical)

        # Domains / Topics (each test can receive multiple tags)
        if any(k in path or k in nodeid for k in ("rag", "docset", "ingest", "retrieval", "vector", "embedding", "search_fusion", "hybrid")):
            item.add_marker(pytest.mark.rag)

        if any(k in path or k in nodeid for k in ("preprocess", "treesitter", "parser", "ast_", "outline", "skeleton", "polyglot", "code_index", "symbols")):
            item.add_marker(pytest.mark.preprocess)

        if any(k in path or k in nodeid for k in ("model", "ollama", "vram", "accelerator", "prompt", "token_router", "tiered", "inference", "whisper", "vision")):
            item.add_marker(pytest.mark.models)

        if any(k in path or k in nodeid for k in ("training", "finetun", "dataset", "laya", "curate", "benchmark", "evaluation", "eval_")):
            item.add_marker(pytest.mark.training)

        if any(k in path or k in nodeid for k in ("mcp", "tool_", "tools_", "action_guide", "action_alias")):
            item.add_marker(pytest.mark.mcp)

        if any(k in path or k in nodeid for k in ("http", "route", "client", "api_", "transport", "sse", "socket", "network")):
            item.add_marker(pytest.mark.http)

        if any(k in path or k in nodeid for k in ("agent", "task", "memory", "blackboard", "fence", "lease", "work_orchestrator", "semaphore", "coord", "incident", "policy", "delegate")):
            item.add_marker(pytest.mark.agent)

        if any(k in path or k in nodeid for k in ("repo", "git", "diff", "worktree", "source_", "patch", "file_info", "call_graph", "affected_tests")):
            item.add_marker(pytest.mark.repo)

        if any(k in path or k in nodeid for k in ("automation", "browser", "async_job", "scheduler", "daemon", "watchdog", "async_")):
            item.add_marker(pytest.mark.automation)

        if any(k in path or k in nodeid for k in ("security", "audit", "auth", "redact", "leak", "uninstall", "ratchet", "quarantine", "permission")):
            item.add_marker(pytest.mark.security)

        if any(k in path or k in nodeid for k in ("artifact", "slice", "compaction")):
            item.add_marker(pytest.mark.artifacts)

        if any(k in path or k in nodeid for k in ("sqlite", "database", "db_", "lock", "state_", "persistence", "journal")):
            item.add_marker(pytest.mark.storage)

        if any(k in path or k in nodeid for k in ("token_", "tokcount", "repo_map", "trim_run", "budget")):
            item.add_marker(pytest.mark.token_economy)

        if any(k in path or k in nodeid for k in ("process", "supervisor", "subprocesses", "launcher", "cleanup", "shutdown", "signal")):
            item.add_marker(pytest.mark.process)

    # 2. Smart test caching (default: skip passed tests if files unchanged)
    if _result_cache_enabled(config):
        passed_cache = config.cache.get("local_ai_hub/passed_hashes", {})
        config._test_result_cache_enabled = True
        config._test_result_passed_hashes = dict(passed_cache)
        deselected = []
        selected = []
        for item in items:
            sig = _test_item_signature(item)
            item._cached_sig = sig
            if passed_cache.get(item.nodeid) == sig:
                deselected.append(item)
            else:
                selected.append(item)

        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected
            if not selected:
                config._all_tests_cached = True
    else:
        # Fresh CI/coverage runs do not need to fingerprint any test module.
        for item in items:
            item._cached_sig = None


def pytest_sessionfinish(session, exitstatus):
    """Persist opt-in cache after fixture monkeypatches have been restored."""
    config = session.config
    if getattr(config, "_test_result_cache_enabled", False):
        config.cache.set(
            "local_ai_hub/passed_hashes",
            getattr(config, "_test_result_passed_hashes", {}),
        )
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and getattr(config, "_all_tests_cached", False):
        # Only explicit, local result-cache mode may report a cache-only run.
        session.exitstatus = pytest.ExitCode.OK


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Record outcomes in memory only; pytest cache I/O is unsafe under OS mocks.

    A test can temporarily simulate Windows by patching os.name on POSIX.
    Constructing Path inside this hook then raises WindowsPath UnsupportedOperation
    and destroys the whole pytest run before normal monkeypatch teardown.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not getattr(item.config, "_test_result_cache_enabled", False):
        return
    cache = item.config._test_result_passed_hashes
    sig = getattr(item, "_cached_sig", None)
    if report.passed and sig:
        cache[item.nodeid] = sig
    elif report.failed:
        cache.pop(item.nodeid, None)


@pytest.fixture(autouse=True)
def _test_owned_mutation_fence(request, monkeypatch):
    if request.module.__name__ not in {"test_command_rollback", "test_command_transaction_snapshot"}:
        return

    from local_ai_hub.command_broker import CommandBroker
    from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence

    original_init = CommandBroker.__init__

    def init_with_test_fence(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        install_test_work_attempt_fence(self, FakeFencingLeaseStore())

    monkeypatch.setattr(CommandBroker, "__init__", init_with_test_fence)

@pytest.fixture(autouse=True)
def _bind_http_stub_mode_state(monkeypatch, request):
    """Keep incomplete HTTP test doubles away from the installation's mode file."""
    module = sys.modules.get("local_ai_hub.http_server")
    gate = getattr(module, "_http_mode_gate_error", None)
    if not callable(gate):
        return

    @wraps(gate)
    def gate_with_test_state(*args, **kwargs):
        app = module.APP
        config = getattr(app, "config", None)
        jobs_path = getattr(getattr(app, "async_jobs", None), "path", None)
        if app is not None and jobs_path is None and (not hasattr(app, "config") or isinstance(config, dict)):
            server = config.get("server", {}) if isinstance(config, dict) else {}
            if isinstance(server, dict) and "state_dir" not in server:
                tmp_path = request.getfixturevalue("tmp_path")
                bound = dict(config) if isinstance(config, dict) else {}
                bound["server"] = {**server, "state_dir": str(tmp_path / "http-stub-state")}
                with monkeypatch.context() as binding:
                    binding.setattr(app, "config", bound, raising=False)
                    return gate(*args, **kwargs)
        return gate(*args, **kwargs)

    monkeypatch.setattr(module, "_http_mode_gate_error", gate_with_test_state)


import urllib.error

_ORIGINAL_HTTP_ERROR_DEL = getattr(urllib.error.HTTPError, "__del__", None)


def _http_error_del_safe(self):
    try:
        self.close()
    except Exception:
        pass
    if _ORIGINAL_HTTP_ERROR_DEL is not None:
        _ORIGINAL_HTTP_ERROR_DEL(self)


urllib.error.HTTPError.__del__ = _http_error_del_safe
