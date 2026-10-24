"""Regression coverage for bounded dependency manifest parsing and confinement."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from local_ai_hub.dependency_audit import MAX_MANIFEST_BYTES, audit_manifest
from local_ai_hub.deterministic import DeterministicEngine


def _engine_without_state() -> DeterministicEngine:
    # package_audit only needs its configuration-independent file boundary.
    return object.__new__(DeterministicEngine)


def test_unsupported_lockfile_is_explicitly_incomplete(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    lockfile = root / "pnpm-lock.yaml"
    lockfile.write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    result = _engine_without_state().package_audit(str(root), "pnpm-lock.yaml")

    assert result["success"] is False
    assert result["status"] == "unsupported"
    assert result["parse_complete"] is False
    assert result["advisory_complete"] is False


def test_malformed_package_lock_json_cannot_be_clean(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "package-lock.json").write_text('{"packages":', encoding="utf-8")

    result = _engine_without_state().package_audit(str(root), "package-lock.json")

    assert result["success"] is False
    assert result["status"] == "invalid"
    assert result["parse_complete"] is False
    assert result["advisory_complete"] is False


def test_nested_npm_versions_are_counted_and_coverage_stays_unknown(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    lockfile = root / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "app", "version": "1.0.0"},
                    "node_modules/shared": {"version": "1.2.0"},
                    "node_modules/parent/node_modules/shared": {"version": "2.0.0"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = _engine_without_state().package_audit(str(root), "package-lock.json")

    assert result["success"] is True
    assert result["manifest"] == str(lockfile.resolve())
    assert result["packages_scanned"] == 2
    assert result["resolved_count"] == 2
    assert result["unresolved_count"] == 0
    assert result["status"] == "unknown"
    assert result["advisory_complete"] is False


def test_pyproject_extras_and_ranges_remain_unresolved_with_partial_advisories(tmp_path):
    result = audit_manifest(
        Path("pyproject.toml"),
        """[project]
name = "fixture"
dependencies = ["requests[security]>=2,<3"]

[project.optional-dependencies]
fast = ["urllib3[socks]==2.0.6", "range-only>=1.2"]
""",
    )

    assert result["success"] is True
    assert result["parse_complete"] is True
    assert result["packages_scanned"] == 3
    assert result["resolved_count"] == 1
    assert result["unresolved_count"] == 2
    assert result["vulnerabilities_found"] == 1
    assert result["status"] == "vulnerabilities_detected"
    assert result["advisory_complete"] is False
    assert result["advisory_source"] == "bundled_legacy_rules"


def test_package_audit_rejects_relative_root_and_relative_traversal(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "requirements.txt"
    outside.write_text("requests==2.30.0\n", encoding="utf-8")
    engine = _engine_without_state()

    relative_root_result = engine.package_audit("repo", "requirements.txt")
    assert relative_root_result["success"] is False
    assert relative_root_result["status"] == "invalid"

    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.open",
        lambda *_args, **_kwargs: pytest.fail("traversal reached manifest open"),
    )
    traversal_result = engine.package_audit(str(root), "../requirements.txt")
    assert traversal_result["success"] is False
    assert traversal_result["status"] == "invalid"


def test_symlink_detection_rejects_before_opening_manifest(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    manifest = root / "requirements.txt"
    manifest.write_text("requests==2.30.0\n", encoding="utf-8")
    monkeypatch.setattr(
        "local_ai_hub.deterministic._is_symlink_or_reparse_point",
        lambda candidate: Path(candidate) == manifest,
    )
    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.open",
        lambda *_args, **_kwargs: pytest.fail("symlinked manifest reached open"),
    )

    result = _engine_without_state().package_audit(str(root), "requirements.txt")

    assert result["success"] is False
    assert result["status"] == "invalid"
    assert result["advisory_complete"] is False


def test_oversized_manifest_is_rejected_before_open(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    manifest = root / "requirements.txt"
    with manifest.open("wb") as stream:
        stream.truncate(MAX_MANIFEST_BYTES + 1)
    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.open",
        lambda *_args, **_kwargs: pytest.fail("oversized manifest reached open"),
    )

    result = _engine_without_state().package_audit(str(root), "requirements.txt")

    assert result["success"] is False
    assert result["status"] == "invalid"
    assert result["parse_complete"] is False
    assert result["advisory_complete"] is False


@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_actual_directory_link_is_rejected_before_manifest_open(tmp_path, monkeypatch, target_location):
    root = tmp_path / "repo"
    root.mkdir()
    target = (root if target_location == "inside" else tmp_path) / "real-manifests"
    target.mkdir()
    (target / "requirements.txt").write_text("requests==2.30.0\n", encoding="utf-8")
    link = root / "linked-manifests"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    assert link.is_dir()
    monkeypatch.setattr(
        "local_ai_hub.deterministic.os.open",
        lambda *_args, **_kwargs: pytest.fail("directory reparse/symlink reached manifest open"),
    )
    result = _engine_without_state().package_audit(str(root), "linked-manifests/requirements.txt")
    assert result["success"] is False, result
    assert result["status"] == "invalid"
    assert result["parse_complete"] is False


def test_osv_cache_reuse_is_bound_to_resolved_package_query(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"results":[{"vulns":[]}]}'

    requests = []

    def urlopen(request, **_kwargs):
        requests.append(json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    engine = DeterministicEngine(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "dependency_audit": {"osv_enabled": True, "osv_timeout_seconds": 1},
        },
        None,
        None,
    )
    dependency = {"package": "sample", "version": "1.0.0", "manifest": "requirements.txt"}
    try:
        engine._osv_audit([dependency])
        engine._osv_audit([dependency])
        engine._osv_audit([{**dependency, "version": "1.0.1"}])
    finally:
        engine.close()

    assert len(requests) == 2
    assert requests[0]["queries"][0]["version"] == "1.0.0"
    assert requests[1]["queries"][0]["version"] == "1.0.1"
