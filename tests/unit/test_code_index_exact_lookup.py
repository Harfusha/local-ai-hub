from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex


def _index(tmp_path: Path) -> tuple[Path, CodeIndex]:
    root = tmp_path / "repo"
    root.mkdir()
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=SimpleNamespace(ignore_dirs={"ignored"}),
    )
    return root, index


def _insert(index: CodeIndex, root: Path, path: str, name: str, line: int = 1) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{name}\n", encoding="utf-8")
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (str(root), path, name, "function", line, line, "", name, "", "public", ""),
        )
        index._replace_symbol_trigrams(con, str(root), [path])
        con.commit()


def test_exact_identifier_suppresses_path_only_matches(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert(index, root, "src/generator.py", "generate_tests")
    _insert(index, root, "tests/test_generate_tests.py", "path_noise")

    result = index.query(str(root), "Generate_Tests")

    assert result["total_matches"] == 1
    assert [item["name"] for item in result["symbols"]] == ["generate_tests"]


def test_exact_identifier_paging_and_root_filter(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _insert(index, root, "pkg/a.py", "target")
    _insert(index, root, "pkg/b.py", "target")
    _insert(index, root, "ignored/hidden.py", "target")
    _insert(index, other, "pkg/c.py", "target")

    first = index.query(str(root), "Target", limit=1, offset=0)
    second = index.query(str(root), "Target", limit=1, offset=1)
    other_root = index.query(str(other), "Target", limit=1, offset=0)

    assert first["total_matches"] == second["total_matches"] == 2
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert first["symbols"][0]["path"] != second["symbols"][0]["path"]
    assert other_root["total_matches"] == 1
    assert other_root["symbols"][0]["path"] == "pkg/c.py"


def test_exact_identifier_uses_exact_matches_before_fuzzy_candidates(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert(index, root, "src/generator.py", "generate_tests")
    _insert(index, root, "src/helpers.py", "generate_tests_helper")

    result = index.query(str(root), "generate_tests")

    assert result["total_matches"] == 2
    assert [item["name"] for item in result["symbols"]] == [
        "generate_tests",
        "generate_tests_helper",
    ]


def test_identifier_without_exact_match_keeps_fuzzy_fallback(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert(index, root, "src/generate.py", "generate_tests")
    _insert(index, root, "src/generated.py", "generate_test_helper")

    result = index.query(str(root), "generate")

    assert result["total_matches"] == 2
    assert {item["name"] for item in result["symbols"]} == {
        "generate_tests", "generate_test_helper"
    }


def test_single_character_identifier_uses_exact_lookup(tmp_path: Path) -> None:
    root, index = _index(tmp_path)
    _insert(index, root, "src/x.py", "x")

    result = index.query(str(root), "x")

    assert result["total_matches"] == 1
    assert result["symbols"][0]["name"] == "x"
