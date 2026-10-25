import os
import hashlib
from typing import get_type_hints

import pytest

from local_ai_hub import context_identity
from local_ai_hub.context_ledger import ContextLedger


def test_context_path_hint_has_required_and_optional_typed_fields():
    hint_type = context_identity.ContextPathHint

    assert hint_type.__required_keys__ == {"path"}
    assert hint_type.__optional_keys__ == {
        "purpose",
        "scope",
        "evidence_id",
        "provenance",
        "repository_revision",
        "config_digest",
        "expires_at",
    }
    annotations = get_type_hints(hint_type)
    assert set(annotations) == hint_type.__required_keys__ | hint_type.__optional_keys__
    assert all(annotation is str for annotation in annotations.values())


def test_context_path_hints_strip_values_omit_blank_metadata_and_preserve_order():
    result = context_identity.normalize_context_path_hints(
        [
            {"path": "  src/first.py  ", "purpose": "  source  ", "scope": "   "},
            {"path": "docs/second.md", "evidence_id": " ev-2 "},
        ]
    )

    assert isinstance(result, tuple)
    assert result == (
        {"path": "src/first.py", "purpose": "source"},
        {"path": "docs/second.md", "evidence_id": "ev-2"},
    )


@pytest.mark.parametrize("value", [None, [], ()])
def test_context_path_hints_empty_input_returns_empty_tuple(value):
    assert context_identity.normalize_context_path_hints(value) == ()


@pytest.mark.parametrize("value", [object(), {"path": "src/a.py"}, iter([{"path": "src/a.py"}])])
def test_context_path_hints_reject_non_list_or_tuple_containers(value):
    with pytest.raises(ValueError):
        context_identity.normalize_context_path_hints(value)


@pytest.mark.parametrize(
    "hint",
    [
        object(),
        {"purpose": "missing path"},
        {"path": "   "},
        {"path": 12},
        {"path": "src/a.py", "unknown": "value"},
        {"path": "src/a.py", "scope": 12},
        {"path": "src/a.py", "scope": "bad\x00value"},
        {"path": "src/a.py", "scope": "x" * 65_537},
    ],
)
def test_context_path_hints_reject_malformed_items_and_values(hint):
    with pytest.raises(ValueError):
        context_identity.normalize_context_path_hints([hint])


def test_context_path_hints_cap_output_at_64_items():
    hints = [{"path": f"src/{index}.py"} for index in range(70)]

    result = context_identity.normalize_context_path_hints(hints)

    assert len(result) == 64
    assert result[0] == {"path": "src/0.py"}
    assert result[-1] == {"path": "src/63.py"}


def test_context_path_hints_accept_string_paths_as_typed_path_records():
    assert context_identity.normalize_context_path_hints(["src/a.py"]) == (
        {"path": "src/a.py"},
    )


def test_context_path_hint_identity_hashes_long_values_stably():
    path = "a" * 1024 + "x"

    identity = context_identity.context_path_hints_identity([{"path": path}])

    assert identity == (
        {"path": {"sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(), "chars": len(path)}},
    )


def test_settings_digest_strips_whitespace_without_requiring_hex():
    assert context_identity.normalize_settings_digest("  rev:abc-123  ") == "rev:abc-123"


@pytest.mark.parametrize("value", [None, 123, "", "  \t  ", "bad\x00digest", "x" * 129])
def test_settings_digest_omits_invalid_values(value):
    assert context_identity.normalize_settings_digest(value) is None


def test_context_root_normalizes_path_and_keeps_empty_root_empty():
    raw_root = "workspace/child/../project//"
    expected = os.path.normcase(os.path.normpath(str(raw_root or "")))

    assert context_identity.normalize_context_root(raw_root) == expected
    assert context_identity.normalize_context_root(None) == ""
    assert context_identity.normalize_context_root("") == ""


def test_context_ledger_uses_shared_path_hint_digest_and_root_normalization(tmp_path):
    ledger = ContextLedger()
    canonical_root = str(tmp_path.resolve())
    first = ledger.compile(
        task_id="task-1",
        revision="rev-1",
        evidence_ids=(),
        context="same context",
        root=os.path.join(canonical_root, "."),
        path_hints=({"path": "src/a.py", "scope": "file"},),
        settings_digest="  rev:abc-123  ",
    )
    equivalent = ledger.compile(
        task_id="task-1",
        revision="rev-1",
        evidence_ids=(),
        context="same context",
        root=canonical_root,
        path_hints=({"scope": "file", "path": "src/a.py"},),
        settings_digest="rev:abc-123",
    )

    assert first["reuse_key"] == equivalent["reuse_key"]


def test_context_ledger_rejects_untyped_path_hint_values():
    ledger = ContextLedger()

    with pytest.raises(ValueError, match="path hint"):
        ledger.compile(
            task_id="task-1",
            revision="rev-1",
            evidence_ids=(),
            context="same context",
            path_hints=(object(),),
        )


def test_context_ledger_materialize_normalizes_root_for_scope_check():
    class ArtifactStore:
        ttl_seconds = 60

        def put(self, text, *, kind):
            return "artifact-1"

        def get(self, artifact_id, *, offset, max_chars):
            return {"success": True, "text": "same context"}

    ledger = ContextLedger()
    store = ArtifactStore()
    compiled = ledger.compile(
        task_id="task-1",
        revision="rev-1",
        evidence_ids=(),
        context="same context",
        root="C:\\Repo",
        artifact_store=store,
        session_id="session-1",
    )

    result = ledger.materialize(
        compiled["reuse_key"],
        store,
        root="C:\\Repo",
        task_id="task-1",
        session_id="session-1",
    )

    assert result["success"] is True
