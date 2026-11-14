from __future__ import annotations

import json

import pytest

from local_ai_hub.manifest_deno import parse_deno_manifest


def test_deno_json_keeps_import_and_task_order():
    raw = b'''{"imports":{"std":"jsr:@std/assert"},"tasks":{"test":"deno test","check":"deno check"}}'''

    assert parse_deno_manifest("deno.json", raw, lambda name: f"purpose:{name}") == (
        [("std", "jsr:@std/assert", "deno-import")],
        [("test", "deno test", "purpose:test"), ("check", "deno check", "purpose:check")],
    )


def test_deno_jsonc_removes_comments_and_trailing_commas():
    raw = b'''{\n  /* imports */\n  "imports": {"std": "jsr:@std/assert",},\n  // task list\n  "tasks": {"test": "deno test",},\n}'''

    assert parse_deno_manifest("deno.jsonc", raw, lambda name: name) == (
        [("std", "jsr:@std/assert", "deno-import")],
        [("test", "deno test", "test")],
    )


def test_other_json_names_are_not_handled():
    assert parse_deno_manifest("package.json", b"{}", lambda name: name) is None


def test_invalid_jsonc_propagates_to_existing_error_boundary():
    with pytest.raises(json.JSONDecodeError):
        parse_deno_manifest("deno.jsonc", b"{", lambda name: name)
