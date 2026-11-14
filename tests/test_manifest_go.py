from __future__ import annotations

from local_ai_hub.manifest_go import parse_go_manifest
from local_ai_hub.manifest_go import parse_go_sum_manifest


def test_go_mod_keeps_single_and_block_require_order():
    raw = b"""module example.test/app
require single.test/pkg v1.2.0
require (
    block.test/one v2.0.0
    block.test/two v3.0.0
)
"""

    assert parse_go_manifest("go.mod", raw) == (
        [
            ("single.test/pkg", "v1.2.0", "require"),
            ("block.test/one", "v2.0.0", "require"),
            ("block.test/two", "v3.0.0", "require"),
        ],
        [],
    )


def test_go_work_keeps_single_and_block_workspace_modules():
    raw = b"""go 1.23
use ./single
use (
    ./first
    ./second
)
// ignored
"""

    assert parse_go_manifest("go.work", raw) == (
        [
            ("./single", "", "workspace-module"),
            ("./first", "", "workspace-module"),
            ("./second", "", "workspace-module"),
        ],
        [],
    )


def test_non_go_manifests_are_not_handled():
    assert parse_go_manifest("cargo.toml", b"") is None
    assert parse_go_sum_manifest("go.mod", b"") is None


def test_go_sum_excludes_go_mod_checksums_and_keeps_order():
    raw = b"first.test/pkg v1.2.0 h1:first\nfirst.test/pkg v1.2.0/go.mod h1:mod\nsecond.test/pkg v2.0.0 h1:second\nmalformed\n"

    assert parse_go_sum_manifest("go.sum", raw) == (
        [("first.test/pkg", "v1.2.0", "sum"), ("second.test/pkg", "v2.0.0", "sum")],
        [],
    )
