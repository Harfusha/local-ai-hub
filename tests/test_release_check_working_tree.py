from pathlib import Path

import pytest

from tools.release_check import _iter_release_hygiene_violations


def _python_caches(root: Path) -> None:
    cache = root / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-313.pyc").write_bytes(b"cache")
    (root / "legacy.pyc").write_bytes(b"cache")
    (root / "legacy.pyo").write_bytes(b"cache")


def test_working_tree_ignores_python_caches_but_rejects_durable_payload(tmp_path):
    _python_caches(tmp_path)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "agent_state.sqlite3").write_bytes(b"durable")

    violations = list(_iter_release_hygiene_violations(tmp_path))

    assert violations == ["runtime/build payload: agent_state.sqlite3"]


def test_strict_release_tree_ignores_python_cache_payloads(tmp_path):
    _python_caches(tmp_path)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "agent_state.sqlite3").write_bytes(b"durable")

    violations = list(_iter_release_hygiene_violations(tmp_path, strict_tree=True))

    assert violations == ["runtime/build payload: agent_state.sqlite3"]


@pytest.mark.parametrize("options", [{}, {"strict_tree": True}])
def test_config_backup_is_rejected_from_release_tree(tmp_path, options):
    (tmp_path / "config.toml.bak-20260913-integrated").write_text("opaque", encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path, **options))

    assert violations == ["local-only file: config.toml.bak-20260913-integrated"]


def test_allow_installed_allows_local_config_backup(tmp_path):
    (tmp_path / "config.toml.bak-20260913-integrated").write_text("opaque", encoding="utf-8")

    assert list(_iter_release_hygiene_violations(tmp_path, allow_installed=True)) == []


def test_allow_installed_allows_verified_embedding_reset_backup(tmp_path):
    backup = tmp_path / "state.embedding-reset-v8.0-123"
    backup.mkdir()
    (backup / "manifest.json").write_text(
        '{"format":1,"migration":"8.0","databases":["rag.sqlite3"]}',
        encoding="utf-8",
    )
    (backup / "rag.sqlite3").write_bytes(b"verified backup fixture")

    assert list(_iter_release_hygiene_violations(tmp_path, allow_installed=True)) == []


def test_allow_installed_rejects_unverified_embedding_reset_backup(tmp_path):
    backup = tmp_path / "state.embedding-reset-v8.0-123"
    backup.mkdir()
    (backup / "manifest.json").write_text('{"migration":"7.0"}', encoding="utf-8")
    (backup / "rag.sqlite3").write_bytes(b"unverified payload")

    assert list(_iter_release_hygiene_violations(tmp_path, allow_installed=True)) == [
        "runtime/build payload: state.embedding-reset-v8.0-123/rag.sqlite3"
    ]


def test_allow_installed_ignores_local_build_but_release_tree_rejects_it(tmp_path):
    build_file = tmp_path / "build" / "output" / "local-wheel.whl"
    build_file.parent.mkdir(parents=True)
    build_file.write_bytes(b"local build artifact")

    assert list(_iter_release_hygiene_violations(tmp_path, allow_installed=True)) == []
    assert list(_iter_release_hygiene_violations(tmp_path)) == ["forbidden directory: build/"]
    assert list(_iter_release_hygiene_violations(tmp_path, strict_tree=True)) == ["forbidden directory: build/"]


@pytest.mark.parametrize("options", [{}, {"strict_tree": True}, {"post_test": True}])
def test_generated_merge_checks_are_rejected_from_release_tree(tmp_path, options):
    scratch = tmp_path / ".merge-checks" / "pytest-final" / "repo"
    scratch.mkdir(parents=True)
    (scratch / "owned.txt").write_text("generated fixture", encoding="utf-8")

    assert list(_iter_release_hygiene_violations(tmp_path, **options)) == [
        "forbidden directory: .merge-checks/"
    ]


def test_allow_installed_preserves_local_merge_check_fixtures(tmp_path):
    fixture = tmp_path / ".merge-checks" / "pytest-final" / "repo" / "owned.txt"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("preserved fixture", encoding="utf-8")

    assert list(_iter_release_hygiene_violations(tmp_path, allow_installed=True)) == []
    assert fixture.read_text(encoding="utf-8") == "preserved fixture"


@pytest.mark.parametrize("options", [{"post_test": True}, {"allow_installed": True}])
def test_strict_release_tree_cannot_allow_workspace_payloads(tmp_path, options):
    with pytest.raises(ValueError, match="strict_tree cannot allow"):
        list(_iter_release_hygiene_violations(tmp_path, strict_tree=True, **options))


# LAH-001: .agents/ with only the canonical Codex marketplace source must not be a violation
@pytest.mark.parametrize("options", [{}, {"strict_tree": True}])
def test_agents_dir_with_only_canonical_marketplace_is_allowed(tmp_path, options):
    """The tracked Codex marketplace manifest is a canonical source file, not runtime data."""
    marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"local-ai-hub","plugins":[]}', encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path, **options))

    assert violations == [], f"Unexpected violations: {violations}"


@pytest.mark.parametrize("options", [{}, {"strict_tree": True}])
def test_agents_dir_with_extra_runtime_data_is_still_forbidden(tmp_path, options):
    """Runtime/cache files inside .agents/ beyond the canonical set must remain forbidden."""
    marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"name":"local-ai-hub","plugins":[]}', encoding="utf-8")
    runtime = tmp_path / ".agents" / "cache" / "secret.txt"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("runtime", encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path, **options))

    assert "forbidden directory: .agents/" in violations


# LAH-005: Telemetry isolation
@pytest.mark.parametrize("options", [{}, {"strict_tree": True}])
def test_telemetry_payload_rejected_in_release_tree(tmp_path, options):
    telemetry_file = tmp_path / ".local-ai-hub" / "telemetry" / "agents.jsonl"
    telemetry_file.parent.mkdir(parents=True)
    telemetry_file.write_text('{"event": "call"}\n', encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path, **options))

    assert "telemetry payload: .local-ai-hub/telemetry/agents.jsonl" in violations


def test_allow_installed_tolerates_local_ai_hub_telemetry(tmp_path):
    telemetry_file = tmp_path / ".local-ai-hub" / "telemetry" / "agents.jsonl"
    telemetry_file.parent.mkdir(parents=True)
    telemetry_file.write_text('{"event": "call"}\n', encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path, allow_installed=True))

    assert violations == []


def test_no_tracked_telemetry_files_in_repository():
    import subprocess
    proc = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    tracked_telemetry = [
        f for f in proc.stdout.splitlines()
        if "telemetry/" in f.replace("\\", "/") or Path(f).name == "agents.jsonl"
    ]
    assert tracked_telemetry == [], f"Found tracked telemetry files: {tracked_telemetry}"

