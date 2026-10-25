from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest

from tools import selftest


def test_selftest_accepts_a_real_temp_root_alias(tmp_path, monkeypatch):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    alias = tmp_path / "alias"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(canonical), str(alias))
    else:
        alias.symlink_to(canonical, target_is_directory=True)

    class ReachedSupervisor(Exception):
        pass

    def stop_before_supervisor(*args, **kwargs):
        config = Path(kwargs["env"]["LOCAL_AI_CONFIG"])
        assert config == config.resolve(strict=True)
        assert config.is_relative_to(canonical.resolve(strict=True))
        raise ReachedSupervisor

    monkeypatch.setattr(tempfile, "tempdir", str(alias))
    monkeypatch.setattr(selftest, "popen_managed", stop_before_supervisor)
    try:
        # Real configuration and repository enumeration must succeed before
        # stopping at the boundary; this never starts a Hub or calls a model.
        with pytest.raises(ReachedSupervisor):
            selftest.main()
    finally:
        if os.name == "nt":
            alias.rmdir()
        else:
            alias.unlink()
