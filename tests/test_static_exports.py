from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.static_exports import named_export_status


@pytest.mark.parametrize(
    ("source", "language", "name", "container", "kind", "access", "expected"),
    [
        (
            "<?php namespace App\\Services; class Exported {}",
            "php", "Exported", "App\\Services", "class", "public",
            (True, "indexed_namespace_type"),
        ),
        (
            "namespace App.Services { public record Exported; }",
            "csharp", "Exported", "App.Services", "record", "public",
            (True, "indexed_namespace_type"),
        ),
        (
            "namespace App; // class Exported {}\nclass Actual {}",
            "php", "Exported", "App", "class", "public",
            (False, "type_declaration_not_found"),
        ),
        (
            "namespace App; class Exported {}",
            "php", "Exported", "Other", "class", "public",
            (False, "nested_type_not_importable_by_namespace"),
        ),
        (
            "namespace App.Services { public class Exported {} }",
            "csharp", "Exported", "App.Services", "class", "private",
            (False, "not_accessible_namespace_type"),
        ),
        (
            "namespace App; class Exported {}",
            "php", "Exported", "", "method", "public",
            (False, "not_accessible_namespace_type"),
        ),
        (
            'namespace App; class Actual { string fake = "class Exported"; }',
            "php", "Exported", "App", "class", "public",
            (False, "type_declaration_not_found"),
        ),
        (
            "class Exported {}",
            "ruby", "Exported", "", "class", "public",
            (False, "export_language_unsupported"),
        ),
    ],
)
def test_php_and_csharp_named_export_validation(
    source: str,
    language: str,
    name: str,
    container: str,
    kind: str,
    access: str,
    expected: tuple[bool, str],
) -> None:
    assert named_export_status(
        source, language, name, container=container, kind=kind, access=access
    ) == expected

def test_type_must_belong_to_the_requested_namespace() -> None:
    source = (
        "namespace App { class Actual {} } "
        "namespace Other { public class Exported {} }"
    )

    assert named_export_status(
        source, "csharp", "Exported", container="App", kind="class", access="public"
    ) == (False, "nested_type_not_importable_by_namespace")

def test_nested_type_is_not_a_namespace_import() -> None:
    source = "namespace App { public class Outer { public class Exported {} } }"

    assert named_export_status(
        source, "csharp", "Exported", container="App", kind="class", access="public"
    ) == (False, "nested_type_not_importable_by_namespace")


def test_resolve_imports_rejects_nested_type_before_emitting_import(tmp_path) -> None:
    source = "namespace App { public class Outer { public class Exported {} } }"
    source_path = tmp_path / "Exports.cs"
    source_path.write_text(source, encoding="utf-8")
    root = str(tmp_path.resolve())
    content_hash = "indexed-source"

    class CodeIndexStub:
        _lock = threading.RLock()

        def _project_config_context(self, _root):
            return None, SimpleNamespace(settings=None)

        def _connect(self):
            connection = sqlite3.connect(":memory:")
            connection.executescript(
                "CREATE TABLE symbols(name TEXT, container TEXT, path TEXT, kind TEXT, "
                "access TEXT, root TEXT, line INTEGER);"
                "CREATE TABLE files(root TEXT, path TEXT, content_hash TEXT);"
            )
            connection.execute(
                "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Exported", "App", "Exports.cs", "class", "public", root, 1),
            )
            connection.execute(
                "INSERT INTO files VALUES (?, ?, ?)",
                (root, "Exports.cs", content_hash),
            )
            return connection

    class RepoToolsStub:
        @staticmethod
        def _project_file_allowed(_root, target, _settings):
            return target.is_file()

        @staticmethod
        def _read_snapshot(_target, *, force):
            assert force is True
            return content_hash, source.splitlines()

    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepoToolsStub(),
        code_index=CodeIndexStub(),
    )

    result = engine.resolve_imports(root, ["Exported"], language="csharp")

    assert result["success"] is True
    assert result["resolved_count"] == 0
    assert result["import_statements"] == []
    assert result["unresolved_symbols"] == ["Exported"]
    assert result["rejected_candidates"] == [
        {
            "symbol": "Exported",
            "path": "Exports.cs",
            "reason": "nested_type_not_importable_by_namespace",
        }
    ]
