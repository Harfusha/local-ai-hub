from __future__ import annotations

import sqlite3
import io
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub import repo_tools as repo_tools_module
from local_ai_hub.repo_tools import GitFileInventory, RepositoryTools
from local_ai_hub.search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW
from local_ai_hub.services import LocalAIServices


def _index(tmp_path: Path) -> tuple[Path, CodeIndex]:
    root = tmp_path / "repo"
    root.mkdir()
    repo_tools = SimpleNamespace(ignore_dirs={"ignored"})
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=repo_tools,
    )
    return root, index


def _insert_symbols(
    index: CodeIndex,
    root: Path,
    names: list[tuple[str, str]],
    *,
    other_root: str | None = None,
) -> None:
    rows = []
    for line, (path, name) in enumerate(names, start=1):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"{name}\n", encoding="utf-8")
        rows.append((str(root), path, name, "function", line, line, "", name, "", "public", ""))
    if other_root is not None:
        rows.append((other_root, "elsewhere.py", "symbol-elsewhere", "function", 1, 1, "", "symbol-elsewhere", "", "public", ""))
    with closing(index._connect()) as con:
        con.executemany(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        for inserted_root in {str(row[0]) for row in rows}:
            index._replace_symbol_trigrams(
                con,
                inserted_root,
                [str(row[1]) for row in rows if str(row[0]) == inserted_root],
            )
        con.commit()


def test_code_index_pages_are_stable_and_default_limit_is_24(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert_symbols(index, root, [(f"pkg/{i:03}.py", f"symbol-{i:03}") for i in range(65)])

    first = index.query(str(root), "symbol", limit=20)
    second = index.query(str(root), "symbol", limit=20, offset=20)
    third = index.query(str(root), "symbol", limit=20, offset=40)
    fourth = index.query(str(root), "symbol", limit=20, offset=60)
    default = index.query(str(root), "symbol")

    assert [item["path"] for item in first["symbols"] + second["symbols"] + third["symbols"] + fourth["symbols"]] == [
        f"pkg/{i:03}.py" for i in range(65)
    ]
    assert [first["total_matches"], second["total_matches"], third["total_matches"], fourth["total_matches"]] == [65] * 4
    assert [first["has_more"], second["has_more"], third["has_more"], fourth["has_more"]] == [True, True, True, False]
    assert len(default["symbols"]) == 24
    assert default["total_matches"] == 65


def test_code_index_ranks_matches_beyond_old_candidate_cap_and_filters_roots(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    names = [(f"a/{i:03}.py", f"prefix-symbol-{i:03}") for i in range(300)]
    names.extend([("ignored/hidden.py", "symbol-hidden"), ("zz/late.py", "symbol")])
    _insert_symbols(index, root, names, other_root=str(tmp_path / "other"))

    result = index.query(str(root), "symbol", limit=20)

    assert result["symbols"][0]["name"] == "symbol"
    assert result["total_matches"] == 301
    assert all("ignored/" not in item["path"] for item in result["symbols"])
    assert all(item["path"] != "elsewhere.py" for item in result["symbols"])


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (-1, 0),
        (20, -1),
        (True, 0),
        (20, True),
        ("20", 0),
        (20, 1.5),
    ],
)
def test_code_index_rejects_invalid_pagination_inputs(
    tmp_path: Path, limit: object, offset: object,
) -> None:
    root, index = _index(tmp_path)

    result = index.query(str(root), "symbol", limit=limit, offset=offset)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["symbols"] == []


@pytest.mark.parametrize("limit,offset", [(MAX_PAGE_SIZE + 1, 0), (1, MAX_PAGE_WINDOW)])
def test_code_index_rejects_pagination_above_http_bounds(
    tmp_path: Path, limit: int, offset: int,
) -> None:
    root, index = _index(tmp_path)

    result = index.query(str(root), "symbol", limit=limit, offset=offset)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["limit"] == (limit if limit <= MAX_PAGE_SIZE else None)
    assert result["offset"] == (offset if offset < MAX_PAGE_WINDOW else None)


def test_code_index_empty_and_out_of_range_pages_keep_metadata(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert_symbols(index, root, [(f"{i:03}.py", f"symbol-{i:03}") for i in range(3)])

    empty = index.query(str(root), "absent", limit=20)
    beyond = index.query(str(root), "symbol", limit=20, offset=99)

    assert empty["symbols"] == []
    assert empty["total_matches"] == 0
    assert empty["has_more"] is False
    assert beyond["symbols"] == []
    assert beyond["total_matches"] == 3
    assert beyond["has_more"] is False


def test_repo_tools_pages_all_lexical_matches_in_ranked_order(tmp_path: Path) -> None:
    root = tmp_path / "lexical-repo"
    root.mkdir()
    for index in range(65):
        (root / f"{index:03}.py").write_text("needle appears here\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    first = tools.search(str(root), "needle", limit=20)
    second = tools.search(str(root), "needle", limit=20, offset=20)
    third = tools.search(str(root), "needle", limit=20, offset=40)
    fourth = tools.search(str(root), "needle", limit=20, offset=60)

    pages = [first, second, third, fourth]
    assert [item["path"] for page in pages for item in page["results"]] == [f"{index:03}.py" for index in range(65)]
    assert [page["total_matches"] for page in pages] == [65] * 4
    assert [page["has_more"] for page in pages] == [True, True, True, False]


def test_git_inventory_reports_truncation_at_explicit_file_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "git-repo"
    root.mkdir()
    (root / ".git").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (root / name).write_text("needle\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    tools.prefer_git = True
    tools.git_files_timeout = 10

    class FakeProcess:
        pid = 12345
        stdout = io.BytesIO(b"a.py\0b.py\0c.py\0")

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(repo_tools_module, "popen_managed", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(repo_tools_module, "terminate_tree", lambda *_args, **_kwargs: None)

    inventory = tools._git_files(root, max_files=2)

    assert isinstance(inventory, GitFileInventory)
    assert len(inventory) == 2
    assert inventory.complete is False


def test_exact_search_fails_closed_for_truncated_git_inventory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("needle\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    result = tools.search(
        str(root), "needle", limit=10, exact_count=True,
        git_inventory=GitFileInventory([root / "a.py"], complete=False),
    )

    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["results"] == []
    assert "truncated" in result["error"].lower()


def test_exact_search_deduplicates_streamed_paths_with_constant_state(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    match = root / "a.py"
    match.write_text("needle\n", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    class RepeatedInventory:
        complete = True

        def __iter__(self):
            for _ in range(100_000):
                yield match

    result = tools.search(
        str(root), "needle", limit=10, exact_count=True,
        git_inventory=RepeatedInventory(),
    )

    assert result["success"] is True
    assert result["scanned_files"] == 1
    assert result["total_matches"] == 1
    assert [item["path"] for item in result["results"]] == ["a.py"]


def test_service_code_query_keeps_offset_in_cache_identity(tmp_path: Path) -> None:
    calls: list[tuple[int, int]] = []

    class IndexStub:
        def _query_terms(self, query: str) -> list[str]:
            return [query.casefold()]

        def query(self, root: str, query: str, limit: int, *, offset: int) -> dict[str, object]:
            calls.append((limit, offset))
            return {"success": True, "symbols": [{"offset": offset}]}

    service = object.__new__(LocalAIServices)
    service.code_index = IndexStub()
    service.learner = None
    service._refresh_changed_intelligence = lambda _root: None
    cache_params: list[dict[str, object]] = []

    def run_cached(_operation, _root, params, compute):
        cache_params.append(dict(params))
        return compute()

    service._repo_cached = run_cached
    first = service.code_query(str(tmp_path), "symbol", limit=20, offset=0)
    second = service.code_query(str(tmp_path), "symbol", limit=20, offset=20)

    assert cache_params[0] != cache_params[1]
    assert cache_params[0]["offset"] == 0
    assert cache_params[1]["offset"] == 20
    assert calls == [(20, 0), (20, 20)]
    assert first["symbols"] == [{"offset": 0}]
    assert second["symbols"] == [{"offset": 20}]
