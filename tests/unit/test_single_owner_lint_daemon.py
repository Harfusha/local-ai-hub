from __future__ import annotations

import inspect

import pytest

from local_ai_hub.biome_owned_ipc import OwnedBiomeDaemon
from local_ai_hub.lint_daemon import OwnedBiomeDaemonPool, RuffDaemonPool


@pytest.mark.parametrize("pool_type", [RuffDaemonPool, OwnedBiomeDaemonPool])
def test_daemon_pool_run_uses_keyword_only_paths_without_tenant(pool_type: type) -> None:
    parameters = inspect.signature(pool_type.run).parameters

    assert "tenant" not in parameters
    assert parameters["paths"].kind is inspect.Parameter.KEYWORD_ONLY


def test_biome_session_apis_use_repository_root_without_tenant() -> None:
    has_session = inspect.signature(OwnedBiomeDaemon.has_session).parameters
    diagnostics = inspect.signature(OwnedBiomeDaemon.diagnostics).parameters

    assert list(has_session) == ["self", "root"]
    assert "tenant" not in diagnostics
    assert diagnostics["root"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert diagnostics["paths"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("value", [None, False, ""])
@pytest.mark.parametrize("pool_type", [RuffDaemonPool, OwnedBiomeDaemonPool])
def test_daemon_pool_rejects_retired_tenant_keyword(pool_type: type, value: object) -> None:
    pool = pool_type.__new__(pool_type)

    with pytest.raises(TypeError, match="tenant"):
        pool.run("lint-tool", ".", paths=["file.py"], tenant=value)


@pytest.mark.parametrize("pool_type", [RuffDaemonPool, OwnedBiomeDaemonPool])
def test_daemon_pool_rejects_old_positional_tenant_slot(pool_type: type) -> None:
    pool = pool_type.__new__(pool_type)

    with pytest.raises(TypeError):
        pool.run("lint-tool", ".", "legacy-tenant", ["file.py"])
