import pytest
from pathlib import Path

from local_ai_hub.work_fencing import canonical_resource, normalize_paths, FencingLeaseStore
from local_ai_hub.work_orchestrator import (
    WorkOrchestrator,
    _safe_work_target,
    _string_list,
)


def test_work_fencing_canonical_resource_and_paths():
    with pytest.raises(ValueError, match="resource must be a non-empty filesystem root"):
        canonical_resource(None)

    with pytest.raises(ValueError, match="resource must be a non-empty filesystem root"):
        canonical_resource(True)

    with pytest.raises(ValueError, match="resource must be a non-empty filesystem root"):
        canonical_resource("")

    with pytest.raises(ValueError, match="resource must be a non-empty filesystem root"):
        canonical_resource("bad\x00path")

    with pytest.raises(ValueError, match="invalid root path"):
        normalize_paths(["src/module.py"], root="bad\x00root")


def test_work_fencing_ttl_hardening():
    with pytest.raises(ValueError, match="ttl_seconds"):
        FencingLeaseStore._ttl(True)

    with pytest.raises(ValueError, match="ttl_seconds"):
        FencingLeaseStore._ttl(-5.0)

    with pytest.raises(ValueError, match="ttl_seconds"):
        FencingLeaseStore._ttl(float("nan"))

    with pytest.raises(ValueError, match="ttl_seconds"):
        FencingLeaseStore._ttl(float("inf"))


def test_work_orchestrator_none_config_init(tmp_path: Path):
    # Initializing WorkOrchestrator when config={"work_orchestrator": None}
    cfg = {"work_orchestrator": None}
    orch = WorkOrchestrator(
        cfg,
        tmp_path,
        services=object(),
        commands=object(),
        leases=object(),
        artifacts=object(),
    )
    assert orch.enabled is True
    assert orch.max_active >= 1


def test_safe_work_target_hardening(tmp_path: Path):
    with pytest.raises(ValueError, match="unsafe work journal path"):
        _safe_work_target(tmp_path, None)

    with pytest.raises(ValueError, match="unsafe work journal path"):
        _safe_work_target(tmp_path, "   ")

    with pytest.raises(ValueError, match="unsafe work journal path"):
        _safe_work_target(tmp_path, "file\x00.py")

    with pytest.raises(ValueError, match="unsafe work journal root"):
        _safe_work_target("bad\x00root", "file.py")


def test_string_list_null_byte_sanitization():
    raw = ["hello", "world\x00drop", "   ", None, "clean"]
    cleaned = _string_list(raw)
    assert "hello" in cleaned
    assert "clean" in cleaned
    assert not any("\x00" in item for item in cleaned)
