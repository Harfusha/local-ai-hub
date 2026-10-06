from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools


def _tools() -> RepositoryTools:
    return RepositoryTools({"rag": {"extensions": [".php"]}, "search": {"max_files": 100}})


def test_context_pack_expands_only_bounded_hint_directory_with_exclusions(tmp_path: Path):
    root = tmp_path / "repo"
    element = root / "templates" / "element"
    (element / "forced").mkdir(parents=True)
    (element / "excluded").mkdir()
    (element / "node_modules").mkdir()
    (root / "templates" / "other").mkdir(parents=True)
    (element / "entry.php").write_text("Needle in the requested element template.", encoding="utf-8")
    (element / "forced" / "keep.php").write_text("Needle in explicit forced file.", encoding="utf-8")
    (element / "excluded" / "blocked.php").write_text("Needle in excluded file.", encoding="utf-8")
    (element / "node_modules" / "ignored.php").write_text("Needle in ignored dependency.", encoding="utf-8")
    git_metadata = root / ".git" / "hook.php"
    git_metadata.parent.mkdir()
    git_metadata.write_text("Needle in private Git metadata.", encoding="utf-8")
    (root / "templates" / "other" / "sibling.php").write_text("Needle outside hinted directory.", encoding="utf-8")

    result = _tools().context_pack_paths(
        str(root), "Needle", ["/templates/element"], max_tokens=120, top_k=10,
        directory_hints=["/templates/element"],
        exclude_paths=["templates/element/forced/**", "templates/element/excluded/**"],
        force_include_paths=["templates/element/node_modules/ignored.php", ".git/hook.php"],
        max_directory_files=8,
    )

    evidence_paths = {item["path"] for item in result["evidence"]}
    assert "templates/element/entry.php" in evidence_paths
    assert "templates/element/forced/keep.php" not in evidence_paths
    assert "templates/element/excluded/blocked.php" not in evidence_paths
    assert "templates/element/node_modules/ignored.php" in evidence_paths
    assert ".git/hook.php" not in evidence_paths
    assert "templates/other/sibling.php" not in evidence_paths
    assert result["scanned_files"] <= 8
    assert result["estimated_tokens"] <= 120


def test_context_pack_directory_expansion_obeys_file_cap(tmp_path: Path):
    root = tmp_path / "repo"
    pages = root / "docs" / "pages"
    pages.mkdir(parents=True)
    for index in range(6):
        (pages / f"page-{index}.php").write_text(f"Needle page {index}.", encoding="utf-8")

    result = _tools().search_paths(
        str(root), "Needle", ["docs/pages"], directory_hints=["docs/pages"],
        max_directory_files=2,
    )

    assert result["success"] is True
    assert result["scanned_files"] == 2
    assert all(item["path"].startswith("docs/pages/") for item in result["results"])


def test_search_paths_rejects_traversal_and_symlink_hints(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "leak.php").write_text("Needle outside.", encoding="utf-8")
    tools = _tools()

    traversal = tools.search_paths(str(root), "Needle", ["../outside/leak.php"])
    assert traversal["success"] is False
    assert "repository-relative" in traversal["error"]

    link = root / "linked"
    link.mkdir()
    original_is_symlink = Path.is_symlink

    def report_link(path: Path) -> bool:
        return path == link or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_link)
    symlink = tools.search_paths(
        str(root), "Needle", ["linked"], directory_hints=["linked"],
    )
    assert symlink["success"] is False
    assert "symlink" in symlink["error"].lower()
