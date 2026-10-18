from __future__ import annotations

from contextlib import closing
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _Rag:
    index_reset = False

    @staticmethod
    def workspace_id(_root):
        return "project-config-test"


class _Noop:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _settings(*, excluded=("private/**",), skipped=(), overrides=None, project_type="python", solution_path=None, maximum_size=None):
    return SimpleNamespace(
        exclude_paths=(),
        force_include_paths=(),
        preprocess_exclude_paths=tuple(excluded),
        path_overrides={},
        text_extensions=(),
        binary_extensions=(),
        max_file_size_bytes=maximum_size,
        skip_phases=tuple(skipped),
        language_overrides=overrides or {},
        project_type=project_type,
        solution_path=solution_path,
    )


def _install_project_config(monkeypatch, settings):
    state = {"settings": settings, "digest": "config-v1"}
    module = types.ModuleType("local_ai_hub.project_config")
    module.resolve_project_context = lambda root, _state_dir: SimpleNamespace(
        root=Path(root), settings=state["settings"], config_digest=state["digest"]
    )
    module.phase_is_allowed = lambda current, phase: phase not in current.skip_phases

    def path_is_allowed(root, path, current, *, phase, size_bytes=None, **_kwargs):
        relative = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        if current.max_file_size_bytes is not None and (
            size_bytes is None or size_bytes > current.max_file_size_bytes
        ):
            return False
        return not (
            phase == "preprocess"
            and any(fnmatch.fnmatchcase(relative, pattern) for pattern in current.preprocess_exclude_paths)
        )

    module.path_is_allowed = path_is_allowed

    class MockProjectPathPolicy:
        def __init__(self, root, current):
            self.root = root
            self.current = current

        def allows(self, path, *, phase, size_bytes=None, **kwargs):
            return module.path_is_allowed(self.root, path, self.current, phase=phase, size_bytes=size_bytes, **kwargs)

    module.ProjectPathPolicy = MockProjectPathPolicy
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", module)
    return state


def _preprocessor(tmp_path: Path, *, code_index=None) -> ProjectPreprocessor:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"extensions": [".py"], "ignore_dirs": []},
        "preprocessing": {"enabled": False, "fs_watcher_enabled": False},
    }
    tools = RepositoryTools(config)
    return ProjectPreprocessor(
        config, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=code_index
    )


def test_preprocess_policy_filters_inventory_and_config_digest_invalidates_cache(tmp_path, monkeypatch):
    settings = _settings(
        solution_path="src/app.sln",
        overrides={"python": {"text_extensions": (".pyx",)}},
    )
    state = _install_project_config(monkeypatch, settings)
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "private").mkdir()
    (root / "src" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (root / "src" / "custom.pyx").write_text("def custom():\n    return 2\n", encoding="utf-8")
    (root / "private" / "generated.py").write_text("secret = 1\n", encoding="utf-8")
    pre = _preprocessor(tmp_path)
    pre._yield = lambda: False
    pre.repo_tools.git_blob_map = lambda _root: {}
    pre._link_content_reuse = lambda _root: None
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "test", "running", "inventory", 0, 0, 1.0, 1.0, 0, 0, 1.0, "test"),
            )
            con.commit()
        assert pre._step_inventory({"root": str(root), "generation": 0}) is True
        detected_profile = {"project_type": "detected", "solution_path": "auto.sln", "validation_commands": []}
        configured_profile = pre._project_profile(str(root), detected_profile)
        assert configured_profile["project_type"] == "python"
        assert configured_profile["solution_path"] == "src/app.sln"
        assert configured_profile["validation_commands"] == []
        assert detected_profile["project_type"] == "detected"
        with closing(pre._connect()) as con:
            paths = {row[0] for row in con.execute("SELECT path FROM file_refs WHERE root=?", (str(root),))}
            first = con.execute("SELECT structural_hash,generation FROM projects WHERE root=?", (str(root),)).fetchone()
        assert paths == {"src/main.py", "src/custom.pyx"}

        pre._watcher_active = True
        first_fingerprint = pre.cache_fingerprint(str(root))["fingerprint"]
        state["settings"] = _settings(solution_path="src/other.sln")
        state["digest"] = "config-v2"
        second_fingerprint = pre.cache_fingerprint(str(root))["fingerprint"]
        assert second_fingerprint != first_fingerprint

        assert pre._step_inventory(dict(pre._project_row(str(root)))) is True
        with closing(pre._connect()) as con:
            second = con.execute("SELECT structural_hash,generation FROM projects WHERE root=?", (str(root),)).fetchone()
        assert second["structural_hash"] != first["structural_hash"]
        assert second["generation"] == first["generation"] + 1
    finally:
        pre.close()


def test_code_index_enforces_call_graph_policy_and_reindexes_language_override(tmp_path, monkeypatch):
    settings = _settings(
        excluded=(),
        overrides={"python": {"text_extensions": (".pyx",)}},
    )
    state = _install_project_config(monkeypatch, settings)
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "private.py").write_text("secret = 1\n", encoding="utf-8")
    custom = root / "src" / "custom.pyx"
    custom.write_text("def visible():\n    return 3\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    tools = RepositoryTools(config)
    index = CodeIndex(config, tools)
    module = sys.modules["local_ai_hub.project_config"]
    original_path_policy = module.path_is_allowed
    module.path_is_allowed = lambda base, path, current, *, phase, **kwargs: (
        False if Path(path).name == "private.py" else original_path_policy(base, path, current, phase=phase, **kwargs)
    )

    assert index.update_file(str(root), "src/private.py")["skipped"] is True
    assert index.update_file(str(root), "src/custom.pyx")["success"] is True
    with closing(index._connect()) as con:
        row = con.execute("SELECT language FROM files WHERE root=? AND path=?", (str(root), "src/custom.pyx")).fetchone()
        assert row["language"] == "python"

    content_hash, _ = tools._read_snapshot(custom)
    state["settings"] = _settings(excluded=(), overrides={"javascript": {"text_extensions": (".pyx",)}})
    state["digest"] = "config-v2"
    assert index.files_needing_reindex(str(root), [("src/custom.pyx", content_hash)]) == [
        ("src/custom.pyx", content_hash)
    ]
    state["settings"] = _settings(excluded=(), skipped=("call_graph",))
    skipped = index.update_files_batch(str(root), [("src/custom.pyx", content_hash)])
    assert skipped["skipped"] == 1
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE root=? AND path=?", (str(root), "src/custom.pyx")
        ).fetchone() is None
    state["settings"] = _settings(excluded=(), skipped=("call_graph",))
    skipped = index.update_files_batch(str(root), [("src/custom.pyx", content_hash)])
    assert skipped["skipped"] == 1
    with closing(index._connect()) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE root=? AND path=?", (str(root), "src/custom.pyx")
        ).fetchone() is None


def test_skipped_call_graph_and_modules_resume_at_next_durable_phase(tmp_path, monkeypatch):
    state = _install_project_config(
        monkeypatch, _settings(skipped=("call_graph", "modules"))
    )
    root = tmp_path / "repo"
    root.mkdir()
    pre = _preprocessor(tmp_path)
    pre._background_work_allowed = lambda: True
    pre._yield = lambda: False
    pre.code_index = SimpleNamespace(
        prune=lambda _root, paths: (setattr(pre, "pruned", paths) or {"success": True})
    )
    called = []
    pre._step_code_index = lambda _row: called.append("call_graph") or True
    pre._step_module = lambda _row: called.append("modules") or True
    now = 1.0
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(root), "test", "running", "code_index", 0, 0, now, now, 0, 0, now, "test"),
            )
            con.commit()
        assert pre._step({"root": str(root), "phase": "code_index"}) is True
        assert pre._project_row(str(root))["phase"] == "deterministic"
        assert pre.pruned == []
        assert called == []

        with closing(pre._connect()) as con:
            con.execute("UPDATE projects SET phase='modules' WHERE root=?", (str(root),))
            con.commit()
        assert pre._step({"root": str(root), "phase": "modules"}) is True
        assert pre._project_row(str(root))["phase"] == "project"
        assert called == []

        pre._step_diagnostics = lambda _row: called.append("diagnostics") or True
        with closing(pre._connect()) as con:
            con.execute("UPDATE projects SET phase='diagnostics' WHERE root=?", (str(root),))
            con.commit()
        assert pre._step({"root": str(root), "phase": "diagnostics"}) is True
        assert called == ["diagnostics"]

        state["settings"] = _settings(skipped=())
        with closing(pre._connect()) as con:
            con.execute("UPDATE projects SET phase='code_index' WHERE root=?", (str(root),))
            con.commit()
        assert pre._step({"root": str(root), "phase": "code_index"}) is True
        assert called == ["diagnostics", "call_graph"]
    finally:
        pre.close()


def test_code_index_phase_applies_project_file_size_limit(tmp_path, monkeypatch):
    _install_project_config(monkeypatch, _settings(excluded=(), maximum_size=8))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "small.py").write_text("x=1\n", encoding="utf-8")
    (root / "large.py").write_text("x = 'too large'\n", encoding="utf-8")
    pre = _preprocessor(tmp_path)
    submitted = []
    pre.code_index = SimpleNamespace(
        prune=lambda *_args: {"success": True},
        files_needing_reindex=lambda _root, items: items,
        update_files_batch=lambda _root, items: submitted.extend(items) or {"files_processed": len(items), "cached": 0},
    )
    pre._record_progress = lambda *_args: None
    try:
        with closing(pre._connect()) as con:
            con.executemany(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (str(root), "small.py", "small-hash", 4, 1, 0, None, 0, 1.0),
                    (str(root), "large.py", "large-hash", 16, 1, 0, None, 0, 1.0),
                ],
            )
            con.commit()
        assert pre._step_code_index({"root": str(root), "generation": 0}) is True
        assert submitted == [("small.py", "small-hash")]
    finally:
        pre.close()


def test_candidate_consumers_with_real_root_project_config(tmp_path, monkeypatch):
    root_checkout = os.environ.get("T10_ROOT_REPOSITORY")
    if not root_checkout:
        import pytest

        pytest.skip("T10_ROOT_REPOSITORY must identify the live root checkout")
    root_checkout = Path(root_checkout).resolve()
    root_package = root_checkout / "src" / "local_ai_hub"
    assert (root_package / "project_config.py").is_file()

    candidate_package = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub"
    overlay_source = tmp_path / "overlay" / "src"
    overlay_package = overlay_source / "local_ai_hub"
    shutil.copytree(
        candidate_package,
        overlay_package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "project_config.py"),
    )
    monkeypatch.setenv("T10_OVERLAY_SOURCE", str(overlay_source))
    monkeypatch.setenv("T10_ROOT_PACKAGE", str(root_package))
    script = textwrap.dedent(
        r"""
        from contextlib import closing
        from pathlib import Path
        from types import SimpleNamespace
        import hashlib
        import importlib.util
        import json
        import os
        import subprocess
        import sys
        from unittest.mock import patch

        overlay_source = Path(os.environ["T10_OVERLAY_SOURCE"]).resolve()
        root_package = Path(os.environ["T10_ROOT_PACKAGE"]).resolve()
        sys.path.insert(0, str(overlay_source))
        import local_ai_hub
        assert Path(local_ai_hub.__file__).resolve() == (overlay_source / "local_ai_hub" / "__init__.py").resolve()
        # Keep candidate modules isolated while resolving the authoritative
        # root project_config imported by preprocess during module loading.
        local_ai_hub.__path__.insert(0, str(root_package))
        from local_ai_hub.code_index import CodeIndex
        from local_ai_hub.preprocess import ProjectPreprocessor
        from local_ai_hub.repo_tools import RepositoryTools
        from local_ai_hub import treesitter_parser
        import local_ai_hub.project_config as project_config
        assert Path(project_config.__file__).resolve() == (root_package / "project_config.py").resolve()
        root_module_sha256 = hashlib.sha256(Path(project_config.__file__).read_bytes()).hexdigest()
        assert root_module_sha256 == os.environ["T10_ROOT_PROJECT_CONFIG_SHA256"], root_module_sha256
        services_spec = importlib.util.spec_from_file_location(
            "local_ai_hub.services", root_package / "services.py",
        )
        root_services = importlib.util.module_from_spec(services_spec)
        sys.modules["local_ai_hub.services"] = root_services
        services_spec.loader.exec_module(root_services)
        assert Path(root_services.__file__).resolve() == (root_package / "services.py").resolve()
        root_services_sha256 = hashlib.sha256(Path(root_services.__file__).read_bytes()).hexdigest()
        assert root_services_sha256 == os.environ["T10_ROOT_SERVICES_SHA256"], root_services_sha256

        class Rag:
            index_reset = False
            @staticmethod
            def workspace_id(_root):
                return "root-config-overlay"

        class Noop:
            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: None

        work = Path(os.environ["T10_OVERLAY_WORK"]).resolve()
        work.mkdir()
        primary = work / "primary"
        linked = work / "linked"
        primary.mkdir()
        subprocess.run(["git", "init", "--quiet", str(primary)], check=True)
        (primary / "src").mkdir()
        (primary / "shared").mkdir()
        (primary / "private").mkdir()
        (primary / "src" / "main.py").write_text("def main(): return 1\n", encoding="utf-8")
        (primary / "src" / "custom.pyx").write_text(
            "def target(): return 2\ndef caller(): return target()\n", encoding="utf-8",
        )
        (primary / "shared" / "hidden.py").write_text("def hidden(): return 0\n", encoding="utf-8")
        (primary / "private" / "secret.py").write_text("def secret(): return 0\n", encoding="utf-8")
        (primary / ".local-ai.toml").write_text(
            'exclude_paths = ["shared/**"]\n'
            'project_type = "python"\n'
            'solution_path = "primary.sln"\n'
            '[preprocess]\nexclude_paths = ["private/**"]\n'
            '[language_overrides.python]\ntext_extensions = [".pyx"]\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(primary), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(primary), "-c", "user.name=T10", "-c", "user.email=t10@example.invalid", "commit", "-qm", "fixture"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(primary), "worktree", "add", "--quiet", "-b", "feature", str(linked)],
            check=True,
        )
        override = linked / ".local-ai.worktree.toml"
        override.write_text('solution_path = "feature.sln"\n', encoding="utf-8")
        context = project_config.resolve_project_context(linked, work / "state")
        assert Path(project_config.__file__).resolve() == (root_package / "project_config.py").resolve()
        assert context.resolution.active_sources == ("defaults", "primary_project", "project", "worktree")
        assert context.settings.project_type == "python"
        assert context.settings.solution_path == "feature.sln"
        assert context.settings.language_overrides["python"]["text_extensions"] == (".pyx",)
        context.save_path_hint(project_config.PathHint(
            path="src/main.py", purpose="entry", scope="root-overlay",
            evidence_id="overlay-evidence", provenance="overlay-test",
            repository_revision="rev-one", config_digest=context.config_digest,
        ))
        revision_hint_hit = [hint.path for hint in context.path_hints(
            purpose="entry", scope="root-overlay", repository_revision="rev-one",
        )] == ["src/main.py"]
        revision_hint_miss = not context.path_hints(
            purpose="entry", scope="root-overlay", repository_revision="rev-two",
        )
        assert revision_hint_hit and revision_hint_miss
        context.save_path_hint(project_config.PathHint(
            path="shared/hidden.py", purpose="excluded-probe", scope="root-overlay",
            evidence_id="excluded-evidence", provenance="overlay-test",
            repository_revision="rev-one", config_digest=context.config_digest,
        ))
        excluded_usage = context.prioritize_paths(
            ["src/main.py", "shared/hidden.py"], purpose="excluded-probe",
            scope="root-overlay", repository_revision="rev-one",
        )
        excluded_hint_prioritized = excluded_usage.paths[0] == "shared/hidden.py" and excluded_usage.hint_used
        excluded_hint_denied = not project_config.path_is_allowed(
            linked, linked / "shared" / "hidden.py", context.settings,
            phase="preprocess", size_bytes=(linked / "shared" / "hidden.py").stat().st_size,
        )
        assert excluded_hint_prioritized and excluded_hint_denied

        config = {
            "server": {"state_dir": str(work / "state")},
            "rag": {"extensions": [".py"], "ignore_dirs": []},
            "preprocessing": {"enabled": False, "fs_watcher_enabled": False},
        }
        tools = RepositoryTools(config)
        code_index = CodeIndex(config, tools)
        pre = ProjectPreprocessor(config, Noop(), Rag(), Noop(), Noop(), tools, code_index=code_index)
        pre._yield = lambda: False
        pre._background_work_allowed = lambda: True
        pre._link_content_reuse = lambda _root: None
        try:
            with closing(pre._connect()) as con:
                con.execute(
                    "INSERT INTO diagnostic_baselines(root,command,exit_code,error_count,stdout_preview,updated_at) VALUES(?,?,?,?,?,?)",
                    (str(primary), "gemini-seed-fixture", 0, 0, "preserve-seed", 1.0),
                )
                now = 1.0
                con.execute(
                    "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(primary), "test", "running", "inventory", 0, 0, now, now, 0, 0, now, "test"),
                )
                for rel in ("src/main.py", "shared/hidden.py", "private/secret.py"):
                    path = primary / rel
                    data = path.read_bytes()
                    stat = path.stat()
                    con.execute(
                        "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (str(primary), rel, hashlib.sha256(data).hexdigest(), stat.st_size, stat.st_mtime_ns, 0, None, 1, now),
                    )
                con.commit()
            seeded = pre._seed_from_parent(str(linked), str(primary))
            assert seeded["file_refs"] == 3, seeded
            with closing(pre._connect()) as con:
                con.execute(
                    "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(linked), "test", "running", "inventory", 0, 0, 1.0, 1.0, 0, 0, 1.0, "test"),
                )
                con.commit()
            assert pre._step_inventory({"root": str(linked), "generation": 0}) is True
            with closing(pre._connect()) as con:
                paths = {row[0] for row in con.execute("SELECT path FROM file_refs WHERE root=?", (str(linked),))}
                row = con.execute("SELECT generation,phase FROM projects WHERE root=?", (str(linked),)).fetchone()
            assert paths == {"src/main.py", "src/custom.pyx"}, paths
            assert pre._watch_relevant(linked, override) == ".local-ai.worktree.toml"
            assert pre._step_incremental_inventory(
                {"root": str(linked), "generation": int(row[0])}, {".local-ai.worktree.toml"},
            ) is False
            custom_extension_watcher_relevant = (
                pre._watch_relevant(linked, linked / "src" / "custom.pyx") == "src/custom.pyx"
            )
            assert custom_extension_watcher_relevant
            hidden_stat = (linked / "shared" / "hidden.py").stat()
            with closing(pre._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (str(linked), "shared/hidden.py", "stale-seed", hidden_stat.st_size, hidden_stat.st_mtime_ns, 0, None, 1, 1.0),
                )
                con.commit()
            assert pre._step_incremental_inventory(
                {"root": str(linked), "generation": int(row[0])}, {"shared/hidden.py"},
            ) is True
            with closing(pre._connect()) as con:
                hidden_ref = con.execute(
                    "SELECT 1 FROM file_refs WHERE root=? AND path=?", (str(linked), "shared/hidden.py"),
                ).fetchone()
                row = con.execute("SELECT generation,phase FROM projects WHERE root=?", (str(linked),)).fetchone()
            incremental_excluded_ref_removed = hidden_ref is None
            assert incremental_excluded_ref_removed

            indexed = code_index.update_file(str(linked), "src/custom.pyx")
            assert indexed.get("success") is True, indexed
            caller_edges = code_index.find_callers(str(linked), "target", limit=10).get("callers", [])
            custom_extension_callgraph_correct = any(
                edge.get("caller") == "caller" and edge.get("callee") == "target"
                for edge in caller_edges
            )
            assert custom_extension_callgraph_correct, caller_edges
            excluded_indexed = code_index.update_file(str(linked), "shared/hidden.py")
            assert excluded_indexed.get("skipped") is True, excluded_indexed
            with closing(code_index._connect()) as con:
                language = con.execute("SELECT language FROM files WHERE root=? AND path=?", (str(linked), "src/custom.pyx")).fetchone()[0]
            assert language == "python", language

            class SearchTools:
                max_hits = 20
                ignore_dirs = set()
                targeted_paths = []
                def _path_extension_is_searchable(self, _path, *, project_settings=None):
                    return True
                def _git_files(self, _root):
                    return []
                def search(self, root, _query, *_args, **_kwargs):
                    return {"success": True, "root": root, "results": [
                        {"path": "shared/hidden.py", "start_line": 1, "text": "hidden"},
                        {"path": "src/main.py", "start_line": 1, "text": "main"},
                    ]}
                def search_paths(self, _root, _query, paths, *_args, **_kwargs):
                    self.targeted_paths.extend(paths)
                    return {"success": True, "results": []}

            search_context = project_config.resolve_project_context(linked, work / "state")
            search_service = root_services.LocalAIServices.__new__(root_services.LocalAIServices)
            search_service.config = config
            search_service.repo_tools = SearchTools()
            search_service.learner = None
            search_service.deterministic = None
            search_service.code_index = None
            search_service.preprocessor = None
            search_service.evidence_store = None
            search_service._repo_cache_state = lambda _root: {"fingerprint": "rev-one"}
            search_service._repo_cached = lambda _op, _root, _params, compute: compute()
            search_result = search_service.repo_search(
                str(linked), "needle", path_hints=[{
                    "path": "shared/hidden.py", "purpose": "repository_search", "scope": "repo_search",
                    "evidence_id": "excluded-search-hint", "provenance": "overlay-test",
                    "repository_revision": "rev-one", "config_digest": search_context.config_digest,
                }],
            )
            search_paths = [item["path"] for item in search_result.get("results", [])]
            search_hint_blocked = "shared/hidden.py" not in search_paths and "shared/hidden.py" not in search_service.repo_tools.targeted_paths
            assert search_paths == ["src/main.py"] and search_hint_blocked, (search_paths, search_service.repo_tools.targeted_paths)

            def search_with_hint(*, revision, digest):
                search_service.repo_tools.targeted_paths.clear()
                result = search_service.repo_search(
                    str(linked), "needle", path_hints=[{
                        "path": "src/main.py", "purpose": "repository_search", "scope": "repo_search",
                        "evidence_id": "allowed-search-hint", "provenance": "overlay-test",
                        "repository_revision": revision, "config_digest": digest,
                    }],
                )
                return result, list(search_service.repo_tools.targeted_paths)

            allowed_result, allowed_targeted = search_with_hint(
                revision="rev-one", digest=search_context.config_digest,
            )
            allowed_hint_applied = "src/main.py" in allowed_targeted
            assert allowed_hint_applied
            assert any(item["path"] == "src/main.py" for item in allowed_result.get("results", []))
            stale_revision_result, stale_revision_targets = search_with_hint(
                revision="rev-stale", digest=search_context.config_digest,
            )
            stale_config_result, stale_config_targets = search_with_hint(
                revision="rev-one", digest="stale-config-digest",
            )
            stale_revision_hint_rejected = "src/main.py" not in stale_revision_targets
            stale_config_hint_rejected = "src/main.py" not in stale_config_targets
            assert stale_revision_hint_rejected
            assert stale_config_hint_rejected
            assert any(item["path"] == "src/main.py" for item in stale_revision_result.get("results", []))
            assert any(item["path"] == "src/main.py" for item in stale_config_result.get("results", []))

            pre._watcher_active = True
            before = pre.cache_fingerprint(str(linked))
            assert before and before["project_config_digest"]
            override.write_text('solution_path = "next.sln"\n', encoding="utf-8")
            after = pre.cache_fingerprint(str(linked))
            assert after and after["fingerprint"] != before["fingerprint"]
            updated_context = project_config.resolve_project_context(linked, work / "state")
            config_hint_miss = not updated_context.path_hints(
                purpose="entry", scope="root-overlay", repository_revision="rev-one",
            )
            assert config_hint_miss
            with closing(pre._connect()) as con:
                unchanged = con.execute("SELECT generation,phase FROM projects WHERE root=?", (str(linked),)).fetchone()
            assert tuple(unchanged) == tuple(row), (tuple(row), tuple(unchanged))

            pre._dirty_paths[str(linked)] = {".local-ai.worktree.toml"}
            with closing(pre._connect()) as con:
                con.execute("UPDATE projects SET last_complete_at=1,force_refresh=0 WHERE root=?", (str(linked),))
                con.commit()
            full_inventory_calls = []
            original_inventory = pre.repo_tools.file_inventory
            def record_full_inventory(*args, **kwargs):
                full_inventory_calls.append(str(args[0]))
                return original_inventory(*args, **kwargs)
            pre.repo_tools.file_inventory = record_full_inventory
            assert pre._step_inventory(dict(pre._project_row(str(linked)))) is True
            config_change_full_inventory_used = str(linked) in full_inventory_calls
            assert config_change_full_inventory_used

            override.write_text('solution_path = "next.sln"\nskip_phases = ["call_graph"]\n', encoding="utf-8")
            with closing(pre._connect()) as con:
                con.execute("UPDATE projects SET phase='code_index' WHERE root=?", (str(linked),))
                con.commit()
            assert pre._step({"root": str(linked), "phase": "code_index"}) is True
            assert pre._project_row(str(linked))["phase"] == "deterministic"

            class DiagnosticProcess:
                pid = 1
                returncode = 0
                stdout = None
                stderr = None
                def communicate(self, timeout):
                    assert timeout == 15.0
                    return ("ok", "")

            real_popen = subprocess.Popen
            def diagnostic_popen(command, *args, **kwargs):
                if command == ["fixture-command"]:
                    return DiagnosticProcess()
                return real_popen(command, *args, **kwargs)

            pre.scheduler = SimpleNamespace(background_allowed=lambda: True, foreground_busy=lambda: False)
            pre.services.repo_profile = lambda _root: {"validation_commands": [{"command": "fixture-command"}]}
            with closing(pre._connect()) as con:
                con.execute(
                    "INSERT INTO diagnostic_baselines(root,command,exit_code,error_count,stdout_preview,updated_at) VALUES(?,?,?,?,?,?)",
                    (str(linked), "gemini-linked-seed", 0, 0, "preserve-linked-seed", 1.0),
                )
                con.commit()
                seeded_diagnostic = con.execute(
                    "SELECT command,exit_code,error_count,stdout_preview FROM diagnostic_baselines WHERE root=?",
                    (str(linked),),
                ).fetchone()
            linked_seed_preserved = tuple(seeded_diagnostic) == (
                "gemini-linked-seed", 0, 0, "preserve-linked-seed",
            )
            assert linked_seed_preserved
            with closing(pre._connect()) as con:
                con.execute("UPDATE projects SET phase='diagnostics' WHERE root=?", (str(linked),))
                con.commit()
            with patch("subprocess.Popen", side_effect=diagnostic_popen):
                assert pre._step({"root": str(linked), "phase": "diagnostics"}) is True
            with closing(pre._connect()) as con:
                baseline = con.execute("SELECT command,exit_code FROM diagnostic_baselines WHERE root=?", (str(linked),)).fetchone()
                parent_seed = con.execute(
                    "SELECT command,exit_code,error_count,stdout_preview FROM diagnostic_baselines WHERE root=?",
                    (str(primary),),
                ).fetchone()
            assert tuple(baseline) == ("fixture-command", 0), tuple(baseline) if baseline else None
            parent_seed_preserved = tuple(parent_seed) == ("gemini-seed-fixture", 0, 0, "preserve-seed")
            assert parent_seed_preserved
            assert pre._project_row(str(linked))["phase"] == "complete"
        finally:
            pre.close()
        print(json.dumps({"import_origin": str(Path(project_config.__file__).resolve()), "root_module_sha256": root_module_sha256, "root_services_origin": str(Path(root_services.__file__).resolve()), "root_services_sha256": root_services_sha256, "sources": list(context.resolution.active_sources), "seeded_file_refs": seeded["file_refs"], "indexed_custom_language": language, "custom_extension_watcher_relevant": custom_extension_watcher_relevant, "incremental_excluded_ref_removed": incremental_excluded_ref_removed, "config_change_full_inventory_used": config_change_full_inventory_used, "excluded_paths": sorted({"shared/hidden.py", "private/secret.py"} - paths), "excluded_hint_prioritized": excluded_hint_prioritized, "excluded_hint_denied": excluded_hint_denied, "repository_search_hint_blocked": search_hint_blocked, "allowed_hint_applied": allowed_hint_applied, "stale_revision_hint_rejected": stale_revision_hint_rejected, "stale_config_hint_rejected": stale_config_hint_rejected, "cache_digest_changed": before["project_config_digest"] != after["project_config_digest"], "path_hint_revision_hit": revision_hint_hit, "path_hint_revision_miss": revision_hint_miss, "path_hint_config_miss": config_hint_miss, "linked_seed_preserved": linked_seed_preserved, "parent_gemini_seed_preserved": parent_seed_preserved, "diagnostic_baseline": list(baseline)}))
        """
    )
    env = dict(os.environ)
    env["T10_ROOT_PACKAGE"] = str(root_package)
    env["T10_OVERLAY_SOURCE"] = str(overlay_source)
    env["T10_OVERLAY_WORK"] = str(tmp_path / "runtime")
    env["T10_ROOT_PROJECT_CONFIG_SHA256"] = hashlib.sha256((root_package / "project_config.py").read_bytes()).hexdigest()
    env["T10_ROOT_SERVICES_SHA256"] = hashlib.sha256((root_package / "services.py").read_bytes()).hexdigest()
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    assert Path(receipt["import_origin"]).resolve() == (root_package / "project_config.py").resolve()
    print("ROOT_OVERLAY_RECEIPT=" + json.dumps(receipt, sort_keys=True))
