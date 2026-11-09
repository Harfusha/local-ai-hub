from __future__ import annotations

import inspect

import pytest
from pathlib import Path

from local_ai_hub.project_config import PathHint
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.tool_agent import ToolAwareLocalAgent


class _CandidatePreprocessor:
    def __init__(self, paths: list[str]):
        self.paths = paths

    def candidate_paths(self, _root: str, _query: str, limit: int) -> list[str]:
        return self.paths[:limit]


def _search_service(tmp_path: Path, preprocessor: object) -> LocalAIServices:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"extensions": [".php", ".py"]},
        "search": {
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
            "max_files": 50,
            "max_hits": 20,
        },
    }
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = config
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = preprocessor
    services.repo_tools = RepositoryTools(config)
    services.evidence_store = None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev-1", "kind": "test"}
    services._repo_cached = lambda _operation, _root, _params, compute, **_kwargs: compute()
    return services


def test_repo_search_prioritizes_request_and_config_hints_without_narrowing(tmp_path: Path) -> None:
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "templates" / "element" / "button.php").write_text("button\n", encoding="utf-8")
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    (tmp_path / "secret" / "button.php").write_text("button\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        'entry_points = ["templates/element"]\n'
        'exclude_paths = ["secret/**"]\n'
        '[path_overrides]\n'
        '"templates/element/**" = "include"\n'
        '"secret/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, _CandidatePreprocessor(["templates/element/button.php"]))
    request_hint = PathHint(
        path="src",
        purpose="repository_search",
        scope="task",
        repository_revision="rev-1",
    )

    result = services.repo_search(
        str(tmp_path), "button", top_k=2, path_hints=[request_hint], scope="task",
        search_mode="lexical",
    )

    assert [item["path"] for item in result["results"]] == [
        "src/button.py",
        "templates/element/button.php",
    ]
    assert result["preprocessed_hit"] is True
    assert "secret/button.php" not in {item["path"] for item in result["results"]}

    configured = services.repo_search(
        str(tmp_path), "button", top_k=2, scope="task", search_mode="lexical",
    )
    assert [item["path"] for item in configured["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


@pytest.mark.parametrize("use_git", [False, True])
@pytest.mark.parametrize("hint_kind", ["file", "directory"])
@pytest.mark.parametrize("directory_name", ["z_directory", "z český folder"])
def test_request_file_hint_is_considered_before_candidate_limit(tmp_path: Path, use_git: bool, hint_kind: str, directory_name: str) -> None:
    import subprocess

    for number in range(70):
        (tmp_path / f"a_{number:03}.py").write_text("unrelated content\n", encoding="utf-8")
    (tmp_path / directory_name).mkdir()
    target = tmp_path / directory_name / "target.py"
    target.write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    if use_git:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
        subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
        services.repo_tools.prefer_git = True
    result = services.repo_search(
        str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path=f"{directory_name}/target.py" if hint_kind == "file" else directory_name, purpose="repository_search", scope="repo_search")],
    )
    assert result["success"] is True, result
    assert f"{directory_name}/target.py" in {item["path"] for item in result["results"]}
    assert result["coverage_complete"] is False
    assert result["truncated"] is True
    assert "candidate_file_limit" in result["truncation_reasons"]


def test_request_hint_cannot_reintroduce_excluded_file_after_candidate_priority(tmp_path: Path) -> None:
    for number in range(70):
        (tmp_path / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    excluded = tmp_path / "z_locked"
    excluded.mkdir()
    (excluded / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text('exclude_paths = ["z_locked/**"]\n', encoding="utf-8")
    services = _search_service(tmp_path, None)
    result = services.repo_search(
        str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path="z_locked/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_locked/secret.py" not in {item["path"] for item in result.get("results", [])}


@pytest.mark.parametrize("overrides", [
    {"repository_revision": "wrong-revision"},
    {"scope": "wrong-scope"},
    {"expires_at": "2000-01-01T00:00:00+00:00"},
])
def test_invalid_or_stale_hint_does_not_expand_candidate_scan(tmp_path: Path, overrides) -> None:
    for number in range(70):
        (tmp_path / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    (tmp_path / "z_target.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    fields = {"path": "z_target.py", "purpose": "repository_search", "scope": "repo_search", **overrides}
    services = _search_service(tmp_path, None)
    result = services.repo_search(str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical",
                                  exact_count=False, path_hints=[PathHint(**fields)])
    assert "z_target.py" not in {item["path"] for item in result.get("results", [])}
    assert result["coverage_complete"] is False


def test_git_ignored_hint_does_not_bypass_inventory_policy(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / ".gitignore").write_text("z_private/\n", encoding="utf-8")
    for number in range(70):
        (tmp_path / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    private = tmp_path / "z_private"
    private.mkdir()
    (private / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    result = services.repo_search(
        str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path="z_private/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_private/secret.py" not in {item["path"] for item in result.get("results", [])}


def test_git_hint_rechecks_ignore_changes(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    for number in range(70):
        (tmp_path / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    private = tmp_path / "z_private"
    private.mkdir()
    (private / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    hint = PathHint(path="z_private/secret.py", purpose="repository_search", scope="repo_search")
    def search():
        return services.repo_search(str(tmp_path), "uniqueastralmarker", top_k=2,
                                    search_mode="lexical", exact_count=False, path_hints=[hint])
    first = search()
    assert "z_private/secret.py" in {item["path"] for item in first["results"]}
    (tmp_path / ".gitignore").write_text("z_private/\n", encoding="utf-8")
    second = search()
    assert "z_private/secret.py" not in {item["path"] for item in second.get("results", [])}


def test_hint_inventory_failure_keeps_search_explicitly_incomplete(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub.repo_tools import GitFileInventory

    for number in range(60):
        (tmp_path / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    (tmp_path / "z_target.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    def inventory(_root, **kwargs):
        if kwargs.get("pathspecs"):
            return None
        return GitFileInventory([tmp_path / f"a_{number:03}.py" for number in range(50)], complete=False)
    monkeypatch.setattr(services.repo_tools, "_git_files", inventory)
    result = services.repo_search(
        str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path="z_target.py", purpose="repository_search", scope="repo_search")],
    )
    assert result["success"] is True
    assert result["coverage_complete"] is False
    assert result["truncated"] is True
    assert "candidate_file_limit" in result["truncation_reasons"]


def test_explicit_hint_survives_full_preprocessor_candidate_list(tmp_path: Path) -> None:
    candidates = []
    for number in range(64):
        path = f"a_{number:03}.py"
        (tmp_path / path).write_text("noise\n", encoding="utf-8")
        candidates.append(path)
    (tmp_path / "z_target.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=2, exact_count=False, candidate_paths=candidates,
        path_hints=[PathHint(path="z_target.py", purpose="repository_search", scope="repo_search")],
    )
    assert result["success"] is True, result
    assert "z_target.py" in {item["path"] for item in result["results"]}


def test_preprocessor_hint_inventory_failure_does_not_expose_unverified_file(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / ".gitignore").write_text("z_private/\n", encoding="utf-8")
    (tmp_path / "candidate.py").write_text("noise\n", encoding="utf-8")
    private = tmp_path / "z_private"
    private.mkdir()
    (private / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    monkeypatch.setattr(services.repo_tools, "_git_files", lambda *_args, **_kwargs: None)
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=2, exact_count=False, candidate_paths=["candidate.py"],
        path_hints=[PathHint(path="z_private/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_private/secret.py" not in {item["path"] for item in result.get("results", [])}
    assert result["candidate_count_exact"] is False


def test_preprocessor_directory_hint_finds_git_tracked_descendant(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / "candidate.py").write_text("noise\n", encoding="utf-8")
    target = tmp_path / "z_target"
    target.mkdir()
    (target / "code.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=2, exact_count=False, candidate_paths=["candidate.py"],
        path_hints=[PathHint(path="z_target", purpose="repository_search", scope="repo_search")],
    )
    assert "z_target/code.py" in {item["path"] for item in result.get("results", [])}, result


def test_preprocessor_directory_hint_does_not_expose_ignored_descendant(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / ".gitignore").write_text("z_target/secret.py\n", encoding="utf-8")
    (tmp_path / "candidate.py").write_text("noise\n", encoding="utf-8")
    target = tmp_path / "z_target"
    target.mkdir()
    (target / "public.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    (target / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=5, exact_count=False, candidate_paths=["candidate.py"],
        path_hints=[PathHint(path="z_target", purpose="repository_search", scope="repo_search")],
    )
    found = {item["path"] for item in result.get("results", [])}
    assert "z_target/public.py" in found, result
    assert "z_target/secret.py" not in found, result


def test_preprocessor_hint_does_not_restore_gitignored_file(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / ".gitignore").write_text("z_private/\n", encoding="utf-8")
    candidates = []
    for number in range(64):
        path = f"a_{number:03}.py"
        (tmp_path / path).write_text("noise\n", encoding="utf-8")
        candidates.append(path)
    private = tmp_path / "z_private"
    private.mkdir()
    (private / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=2, exact_count=False, candidate_paths=candidates,
        path_hints=[PathHint(path="z_private/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_private/secret.py" not in {item["path"] for item in result.get("results", [])}


def test_preprocessor_hint_retains_explicit_project_force_include(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / ".gitignore").write_text("z_private/\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text('force_include_paths = ["z_private/secret.py"]\n', encoding="utf-8")
    candidates = []
    for number in range(64):
        path = f"a_{number:03}.py"
        (tmp_path / path).write_text("noise\n", encoding="utf-8")
        candidates.append(path)
    private = tmp_path / "z_private"
    private.mkdir()
    (private / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "."], cwd=tmp_path, check=True, timeout=10)
    services = _search_service(tmp_path, None)
    services.repo_tools.prefer_git = True
    result = services._repo_search_lexical(
        str(tmp_path), "uniqueastralmarker", top_k=2, exact_count=False, candidate_paths=candidates,
        path_hints=[PathHint(path="z_private/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_private/secret.py" in {item["path"] for item in result.get("results", [])}


def test_deep_hint_survives_filesystem_walk_entry_budget(tmp_path: Path) -> None:
    for number in range(33):
        directory = tmp_path / f"a_{number:03}"
        directory.mkdir()
        for index in range(25):
            (directory / f"noise_{index:02}.py").write_text("noise\n", encoding="utf-8")
    nested = tmp_path / "z_target" / "nested"
    nested.mkdir(parents=True)
    (nested / "target.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    result = services.repo_search(
        str(tmp_path), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path="z_target/nested/target.py", purpose="repository_search", scope="repo_search")],
    )
    assert "z_target/nested/target.py" in {item["path"] for item in result.get("results", [])}


@pytest.mark.parametrize("use_git", [False, True])
def test_hinted_symlink_cannot_escape_project_root(tmp_path: Path, use_git: bool) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    link = repo / "z_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    for number in range(70):
        (repo / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
    services = _search_service(repo, None)
    if use_git:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=10)
        subprocess.run(["git", "add", "--", "."], cwd=repo, check=True, timeout=10)
        services.repo_tools.prefer_git = True
    result = services.repo_search(
        str(repo), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
        path_hints=[PathHint(path="z_link/secret.py", purpose="repository_search", scope="repo_search")],
    )
    assert not result.get("results"), result


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows junction regression")
@pytest.mark.parametrize("use_git", [False, True])
def test_hinted_windows_junction_cannot_escape_project_root(tmp_path: Path, use_git: bool) -> None:
    import os
    import stat
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert repo.resolve().parent == tmp_path.resolve() == outside.resolve().parent
    (outside / "secret.py").write_text("uniqueastralmarker\n", encoding="utf-8")
    link = repo / "z_link"
    environment = os.environ.copy()
    environment.update(LAH_TEST_JUNCTION=str(link), LAH_TEST_TARGET=str(outside))
    created = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         'New-Item -ItemType Junction -Path $env:LAH_TEST_JUNCTION -Target $env:LAH_TEST_TARGET -ErrorAction Stop | Out-Null'],
        env=environment, capture_output=True, timeout=10, **hidden_run_kwargs(),
    )
    if created.returncode != 0:
        pytest.skip("Windows junction creation unavailable")
    try:
        assert os.lstat(link).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        for number in range(70):
            (repo / f"a_{number:03}.py").write_text("noise\n", encoding="utf-8")
        services = _search_service(repo, None)
        if use_git:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
            subprocess.run(["git", "add", "--", *(f"a_{number:03}.py" for number in range(70))],
                           cwd=repo, check=True, timeout=10, **hidden_run_kwargs())
            services.repo_tools.prefer_git = True
        result = services.repo_search(
            str(repo), "uniqueastralmarker", top_k=2, search_mode="lexical", exact_count=False,
            path_hints=[PathHint(path="z_link/secret.py", purpose="repository_search", scope="repo_search")],
        )
        assert not result.get("results"), result
        assert (outside / "secret.py").is_file()
    finally:
        assert link.parent.resolve() == repo.resolve()
        os.rmdir(link)


def test_repo_search_default_scope_applies_public_repository_search_hint(tmp_path: Path) -> None:
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "templates" / "element" / "button.php").write_text(
        "button\n", encoding="utf-8"
    )
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    services = _search_service(tmp_path, None)

    result = services.repo_search(
        str(tmp_path),
        "button",
        top_k=2,
        search_mode="lexical",
        path_hints=[
            PathHint(
                path="templates/element",
                purpose="repository_search",
                scope="repo_search",
            )
        ],
    )

    assert result["success"] is True
    assert [hit["path"] for hit in result["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


def test_repo_search_hints_cannot_restore_excluded_or_outside_results(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "src" / "allowed.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src" / "quarantined.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / "secret" / "blocked.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        'exclude_paths = ["secret/**"]\n'
        '[path_overrides]\n'
        '"secret/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, None)
    outside = tmp_path.parent / "outside.php"
    outside.write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(
        services.repo_tools,
        "search",
        lambda *_args, **_kwargs: {
            "success": True,
            "root": str(tmp_path),
            "results": [
                {"path": "src/allowed.php", "start_line": 1},
                {"path": "src/quarantined.php", "start_line": 1, "hard_denied": True},
                {"path": "secret/blocked.php", "start_line": 1},
                {"path": "../outside.php", "start_line": 1},
            ],
            "total_matches": 4,
            "count_exact": True,
            "engine": "fixture",
        },
    )

    result = services.repo_search(
        str(tmp_path),
        "needle",
        top_k=5,
        path_hints=[
            PathHint("secret/blocked.php", "repository_search", "task"),
            PathHint("src/quarantined.php", "repository_search", "task"),
            PathHint("../outside.php", "repository_search", "task"),
        ],
        scope="task",
    )

    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["error"] == "repository search filters disagreed while materializing the exact page"
    assert result["results"] == []


def test_repo_search_uses_path_override_include_only_as_priority(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    (tmp_path / "templates" / "element" / "button.php").write_text(
        "button\n", encoding="utf-8"
    )
    (tmp_path / ".local-ai.toml").write_text(
        '[path_overrides]\n"templates/element/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, None)

    result = services.repo_search(str(tmp_path), "button", top_k=2, search_mode="lexical")

    assert [item["path"] for item in result["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


def test_exact_search_hint_ranking_does_not_resolve_each_result_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    candidate = docs / "guide.py"
    candidate.write_text("installation\n", encoding="utf-8")
    services = _search_service(tmp_path, None)
    original_resolve = Path.resolve
    candidate_resolutions = []

    def track_candidate_resolution(path: Path, *args, **kwargs):
        frame = inspect.currentframe().f_back
        path_priority_call = any(
            current.frame.f_code.co_name == "path_priority"
            for current in inspect.getouterframes(frame)
        )
        if path == candidate and kwargs.get("strict") is False and path_priority_call:
            candidate_resolutions.append(path)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", track_candidate_resolution)
    result = services.repo_search(str(tmp_path), "installation", top_k=1)

    assert result["success"] is True
    assert result["results"][0]["path"] == "docs/guide.py"
    assert candidate_resolutions == []


def test_tool_repo_search_routes_request_hints_through_complete_service() -> None:
    class _Services:
        def __init__(self) -> None:
            self.call: tuple[object, ...] | None = None

        def repo_search(self, root, query, top_k, *, path_hints, scope):
            self.call = (root, query, top_k, path_hints, scope)
            return {"success": True, "results": [{"path": "all-candidates-kept"}]}

    class _Preprocessor:
        def candidate_paths(self, *_args, **_kwargs):
            raise AssertionError("tool route must not restrict search to preprocessor candidates")

    services = _Services()
    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.services = services
    agent.preprocessor = _Preprocessor()
    agent.evidence = None
    request_hints = [{"path": "templates/element", "purpose": "repository_search", "scope": "task"}]

    result = agent._execute_tool(
        "repo_search",
        {"query": "button", "top_k": 4, "path_hints": request_hints, "scope": "task"},
        "/tmp/repo",
        "workspace",
    )

    assert result["results"] == [{"path": "all-candidates-kept"}]
    assert services.call == ("/tmp/repo", "button", 4, request_hints, "task")


def test_repo_search_logs_preprocessor_candidate_failure_and_keeps_exact_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingPreprocessor:
        @staticmethod
        def candidate_paths(*_args, **_kwargs):
            raise PermissionError(f"private path: {tmp_path}")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needleSymbol button\n", encoding="utf-8")
    services = _search_service(tmp_path, FailingPreprocessor())

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        result = services.repo_search(str(tmp_path), "needleSymbol", top_k=5, scope="task")

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    messages = [record.getMessage() for record in caplog.records]
    assert any("Preprocessor candidate search skipped (PermissionError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_repo_search_logs_deterministic_candidate_failure_and_keeps_exact_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingDeterministicIndex:
        @staticmethod
        def related_paths(*_args, **_kwargs):
            raise PermissionError(f"private path: {tmp_path}")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needleSymbol button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services.deterministic = FailingDeterministicIndex()

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        result = services.repo_search(str(tmp_path), "needleSymbol", top_k=5, scope="task")

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    messages = [record.getMessage() for record in caplog.records]
    assert any("Deterministic candidate search skipped (PermissionError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_repo_search_skips_partial_code_index_for_natural_query_and_keeps_exact_search(
    tmp_path: Path,
) -> None:
    class FailingCodeIndex:
        def __init__(self):
            self.calls = 0

        def related_paths(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("natural-language search must not scan the partial code index")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    code_index = FailingCodeIndex()
    services.code_index = code_index

    result = services.repo_search(
        str(tmp_path), "needle", top_k=5, scope="task", search_mode="lexical",
    )

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    assert code_index.calls == 0


def test_repo_search_does_not_claim_progressive_disclosure_without_receipts(tmp_path: Path) -> None:
    class IncompleteEvidenceStore:
        @staticmethod
        def put_many(_root: str, hits: list[dict]) -> list[dict]:
            return [dict(hit) for hit in hits]

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services.evidence_store = IncompleteEvidenceStore()

    result = services.repo_search(
        str(tmp_path), "needle", top_k=5, scope="task", search_mode="lexical",
    )

    assert result["success"] is True
    assert result["progressive_disclosure"] is False
    assert "needle button" in result["results"][0]["text"]


def test_tool_repo_search_preserves_text_without_evidence_receipt() -> None:
    class Services:
        @staticmethod
        def repo_search(_root, _query, _top_k, *, path_hints, scope):
            return {
                "success": True,
                "results": [{"path": "src/button.py", "text": "needle button", "file_sha256": "hash"}],
            }

    class IncompleteEvidenceStore:
        @staticmethod
        def put_many(_root, hits):
            return [dict(hit) for hit in hits]

    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.services = Services()
    agent.preprocessor = object()
    agent.evidence = IncompleteEvidenceStore()

    result = agent._execute_tool(
        "repo_search",
        {"query": "needle", "top_k": 1},
        "/tmp/repo",
        "workspace",
    )

    assert result["results"][0]["text"] == "needle button"
    assert result["progressive_disclosure"] is False


@pytest.mark.parametrize(
    ("search_mode", "query"),
    [("lexical", "needle"), ("hybrid", "repoSearch")],
)
def test_repo_search_does_not_claim_complete_coverage_for_truncated_results(
    tmp_path: Path, search_mode: str, query: str,
) -> None:
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services._repo_search_lexical = lambda *_args, **_kwargs: {
        "success": True,
        "results": [],
        "has_more": False,
        "truncated": True,
        "truncation_reasons": ["candidate_file_limit"],
    }

    result = services.repo_search(
        str(tmp_path), query, search_mode=search_mode,
    )

    assert result["success"] is True
    assert result["truncated"] is True
    assert result["coverage_complete"] is False
