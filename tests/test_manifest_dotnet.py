from __future__ import annotations

import json

import pytest

from local_ai_hub.manifest_dotnet import parse_dotnet_manifest


def test_nuget_lock_keeps_target_framework_and_resolved_version():
    raw = json.dumps({
        "dependencies": {
            "net8.0": {"Newtonsoft.Json": {"resolved": "13.0.1", "requested": "13.*"}},
            "net7.0": {"Other": {"requested": "2.*"}},
        },
    }).encode()

    assert parse_dotnet_manifest("packages.lock.json", raw) == (
        [("Newtonsoft.Json", "13.0.1", "nuget-lock:net8.0"), ("Other", "2.*", "nuget-lock:net7.0")],
        [],
    )


def test_global_json_reports_sdk_toolchain_version():
    assert parse_dotnet_manifest("global.json", b'''{"sdk":{"version":"8.0.204"}}''') == (
        [("dotnet-sdk", "8.0.204", "toolchain")],
        [],
    )


def test_unsupported_names_and_malformed_json_keep_existing_boundary():
    assert parse_dotnet_manifest("package.json", b"{}") is None
    with pytest.raises(json.JSONDecodeError):
        parse_dotnet_manifest("global.json", b"{")
