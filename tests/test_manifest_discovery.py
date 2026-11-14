from __future__ import annotations

from local_ai_hub.manifest_discovery import select_manifest_files, walk_manifest_paths


def test_selection_accepts_supported_names_case_insensitively_and_sorts(tmp_path):
    paths = [
        tmp_path / "z" / "BUILD.GRADLE",
        tmp_path / "requirements-dev.in",
        tmp_path / "Foo.CSPROJ",
        tmp_path / "ignored.lock",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    assert select_manifest_files(paths, max_bytes=1) == [paths[2], paths[1], paths[0]]


def test_selection_excludes_oversized_and_unstatable_manifests(tmp_path):
    small = tmp_path / "package.json"
    large = tmp_path / "Cargo.toml"
    missing = tmp_path / "pom.xml"
    small.write_text("{}", encoding="utf-8")
    large.write_text("123456", encoding="utf-8")

    assert select_manifest_files([large, missing, small], max_bytes=2) == [small]


def test_selection_accepts_the_supported_manifest_families(tmp_path):
    names = [
        "package-lock.json", "pnpm-lock.yaml", "deno.jsonc", "composer.lock",
        "uv.lock", "cargo.lock", "go.sum", "go.work", "pom.xml", "Gemfile",
        "Gemfile.lock", "yarn.lock", "libs.versions.toml", "Justfile",
        "packages.lock.json", "global.json", "Directory.Build.targets",
        "module.fsproj", "module.vbproj",
    ]
    paths = [tmp_path / name for name in names]
    for path in paths:
        path.write_text("x", encoding="utf-8")

    assert select_manifest_files(paths, max_bytes=1) == sorted(paths, key=lambda path: str(path).lower())


def test_walk_fallback_prunes_ignored_directories_and_obeys_limit(tmp_path):
    (tmp_path / "visible").mkdir()
    (tmp_path / "ignored").mkdir()
    (tmp_path / "visible" / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "visible" / "two.txt").write_text("2", encoding="utf-8")
    (tmp_path / "ignored" / "secret.txt").write_text("x", encoding="utf-8")

    paths = walk_manifest_paths(
        tmp_path,
        max_files=1,
        ignore_dirs={"ignored"},
    )
    assert len(paths) == 1
    assert paths[0].parent.name == "visible"


def test_walk_fallback_empty_inventory_returns_empty(tmp_path):
    assert walk_manifest_paths(tmp_path, max_files=20, ignore_dirs=set()) == []
