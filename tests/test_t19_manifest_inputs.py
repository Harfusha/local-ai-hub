from __future__ import annotations

from pathlib import Path
import sys
import tarfile
import unittest
import zipfile

from test_t19_packaged_sdk_smoke import (
    OFFLINE_GUARD, _environment, _inputs, _isolated_toolchain, _run, _snapshot,
)


PUBLIC = {"MANIFEST.in", "pyproject.toml", "README.md", "src/fixture_pkg/__init__.py",
          "src/fixture_pkg/public.py", "docs/public.md", "docs/nested/public.md"}
PRIVATE = {"docs/integration-owner.md", "docs/integration/secret.md",
           "docs/superpowers/owner.md", "docs/PRIVATE_SYNC.md"}
RULES = (
    "include README.md\nrecursive-include docs *.md\n"
    "prune docs/superpowers\nexclude docs/integration-*.md docs/*SYNC*.md\n"
    "prune docs/integration\n"
)


def _fixture(root: Path, manifest: str = RULES) -> None:
    for name in PUBLIC | PRIVATE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("literal bytes: " + name, encoding="utf-8")
    (root / "src/fixture_pkg/__init__.py").write_text("", encoding="utf-8")
    (root / "src/fixture_pkg/public.py").write_bytes(b"PUBLIC_VALUE = 17\n")
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools>=75", "wheel"]\n'
        'build-backend="setuptools.build_meta"\n'
        '[project]\nname="manifest-parser-fixture"\nversion="1.0.0"\n'
        '[tool.setuptools]\npackage-dir={""="src"}\n'
        '[tool.setuptools.packages.find]\nwhere=["src"]\n'
        '[tool.setuptools.data-files]\n'
        '"public-docs"=["docs/public.md"]\n'
        '"public-docs/nested"=["docs/nested/public.md"]\n',
        encoding="utf-8",
    )
    (root / "MANIFEST.in").write_text(manifest, encoding="utf-8")


def _names(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in _inputs(root)}


def test_exclude_globs_and_prunes_preserve_literal_public_inputs(tmp_path):
    _fixture(tmp_path)
    assert _names(tmp_path) == PUBLIC
    snapshot = tmp_path / "snapshot"
    identities = _snapshot(tmp_path, snapshot)
    assert set(identities) == PUBLIC
    for name in PUBLIC:
        assert (snapshot / name).read_bytes() == (tmp_path / name).read_bytes()
    assert all(not (snapshot / name).exists() for name in PRIVATE)


def test_later_include_readds_files_after_exclude_and_prune(tmp_path):
    _fixture(tmp_path, RULES + "exclude docs/public.md\nprune docs/nested\n"
             "include docs/public.md docs/nested/public.md\n")
    assert _names(tmp_path) == PUBLIC


def test_prune_directory_glob_removes_each_private_tree(tmp_path):
    _fixture(tmp_path, RULES + "prune docs/integration-*\n")
    for name in ("docs/integration-alpha/secret.md", "docs/integration-beta/secret.md"):
        path = tmp_path / name
        path.parent.mkdir()
        path.write_text("private", encoding="utf-8")
    assert _names(tmp_path) == PUBLIC


def test_recursive_exclude_directory_glob_keeps_public_files(tmp_path):
    _fixture(tmp_path, RULES + "recursive-exclude docs/private-* *.md\n")
    for name in ("docs/private-one/nested/secret.md", "docs/private-two/secret.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True)
        path.write_text("private", encoding="utf-8")
    assert _names(tmp_path) == PUBLIC


def test_global_patterns_and_graft_follow_rule_order(tmp_path):
    _fixture(tmp_path, "global-include *.md\nglobal-exclude *owner* *secret* *SYNC*\n"
             "graft assets-*\nglobal-exclude *.private\n")
    for name in ("assets-public/public.css", "assets-public/token.private"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("literal asset", encoding="utf-8")
    assert _names(tmp_path) == PUBLIC | {"assets-public/public.css"}


def test_literal_private_docs_absent_from_real_sdist_and_wheel(tmp_path):
    toolchain = _isolated_toolchain()
    if any(toolchain[name] is None for name in ("setuptools", "wheel", "pip")):
        raise unittest.SkipTest("isolated build backend unavailable; never install dependencies")
    source = tmp_path / "fixture"
    source.mkdir()
    _fixture(source)
    snapshot = tmp_path / "source"
    identities = _snapshot(source, snapshot)
    assert set(identities) == PUBLIC
    dist = tmp_path / "dist"
    dist.mkdir()
    env = _environment(tmp_path)
    receipt = {"commands": []}
    code = OFFLINE_GUARD + "import setuptools.build_meta as b; b.build_sdist(sys.argv[1]); assert not forbidden"
    _run([sys.executable, "-I", "-B", "-c", code, str(dist)],
         snapshot, env, tmp_path, "literal-sdist", receipt)
    extracted = tmp_path / "sdist-source"
    extracted.mkdir()
    with tarfile.open(next(dist.glob("*.tar.gz"))) as archive:
        names = {member.name.partition("/")[2] for member in archive.getmembers() if member.isfile()}
        assert PUBLIC <= names
        assert names.isdisjoint(PRIVATE)
        for name in PUBLIC:
            member = next(member for member in archive.getmembers()
                          if member.name.partition("/")[2] == name)
            with archive.extractfile(member) as stream:
                assert stream.read() == (source / name).read_bytes()
        archive.extractall(extracted, filter="data")
    wheel_source = next(extracted.iterdir())
    code = OFFLINE_GUARD + "import setuptools.build_meta as b; b.build_wheel(sys.argv[1]); assert not forbidden"
    _run([sys.executable, "-I", "-B", "-c", code, str(dist)],
         wheel_source, env, tmp_path, "literal-wheel", receipt)
    with zipfile.ZipFile(next(dist.glob("*.whl"))) as archive:
        names = archive.namelist()
        assert archive.read("fixture_pkg/public.py") == b"PUBLIC_VALUE = 17\n"
        assert archive.read("fixture_pkg/__init__.py") == b""
        assert not any(any(name.endswith(private) for private in PRIVATE) for name in names)
        public_docs = [name for name in names if ".data/data/public-docs/" in name]
        assert len(public_docs) == 2
        assert {archive.read(name) for name in public_docs} == {
            b"literal bytes: docs/public.md", b"literal bytes: docs/nested/public.md"}
