from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.manifest_packages import parse_package_manifest


def test_package_json_keeps_dependency_section_and_script_order():
    raw = b'''{"dependencies":{"runtime":"^1"},"devDependencies":{"test":"~2"},"scripts":{"test":"pytest","build":"python -m build"}}'''

    deps, scripts = parse_package_manifest("package.json", raw, lambda name: f"purpose:{name}")

    assert deps == [("runtime", "^1", "dependencies"), ("test", "~2", "devDependencies")]
    assert scripts == [("test", "pytest", "purpose:test"), ("build", "python -m build", "purpose:build")]


def test_composer_json_joins_script_arrays_and_preserves_sections():
    raw = b'''{"require":{"runtime/pkg":"^1"},"require-dev":{"test/pkg":"~2"},"scripts":{"test":["first", "second"],"build":"build"}}'''

    deps, scripts = parse_package_manifest("composer.json", raw, lambda name: f"purpose:{name}")

    assert deps == [("runtime/pkg", "^1", "require"), ("test/pkg", "~2", "require-dev")]
    assert scripts == [("test", "first && second", "purpose:test"), ("build", "build", "purpose:build")]


def test_other_manifest_names_are_not_handled():
    assert parse_package_manifest("deno.json", b"{}", lambda name: name) is None


def test_invalid_json_propagates_to_existing_error_boundary():
    with pytest.raises(json.JSONDecodeError):
        parse_package_manifest("package.json", b"{", lambda name: name)


def test_engine_keeps_snapshot_and_blob_cache_around_package_parser(tmp_path):
    path = tmp_path / "package.json"
    path.write_text('{"dependencies":{"runtime":"^1"}}', encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    snapshots: list[str] = []
    cached: list[tuple[object, ...]] = []
    engine.max_manifest_bytes = 1024
    engine.repo_tools = SimpleNamespace(
        _read_snapshot=lambda snapshot_path: (
            snapshots.append(str(snapshot_path)) or "digest",
            path.read_text(encoding="utf-8").splitlines(),
        )
    )
    engine._manifest_blob_get = lambda *args: None
    engine._manifest_blob_put = lambda *args: cached.append(args)
    engine._stats = Counter()
    engine._purpose = lambda name: f"purpose:{name}"

    assert engine._parse_manifest(path, "package.json", "content-hash") == (
        [("runtime", "^1", "dependencies")],
        [],
    )
    assert snapshots == [str(path)]
    assert cached == [("content-hash", "package.json", [("runtime", "^1", "dependencies")], [])]
