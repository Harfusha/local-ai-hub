from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("method", "kwargs", "expected"),
    [
        pytest.param(
            "context_compile",
            {
                "task_id": "t19-fixture",
                "token_budget": 2500,
                "changed_paths": ["src/app.py"],
                "since_hash": "etag-1",
                "compact": True,
            },
            (
                "/api/agent-state/context",
                {
                    "action": "compile",
                    "task_id": "t19-fixture",
                    "token_budget": 2500,
                    "changed_paths": ["src/app.py"],
                    "compact": True,
                    "since_hash": "etag-1",
                },
            ),
            id="context-compile-with-etag",
        ),
        pytest.param(
            "context_compile",
            {"task_id": "t19-fixture"},
            (
                "/api/agent-state/context",
                {
                    "action": "compile",
                    "task_id": "t19-fixture",
                    "token_budget": 4000,
                    "changed_paths": [],
                    "compact": False,
                },
            ),
            id="context-compile-defaults",
        ),
        pytest.param(
            "circular_dependencies",
            {"root": "/repo", "language": "python"},
            (
                "/api/repo/circular_dependencies",
                {"root": "/repo", "language": "python"},
            ),
            id="circular-dependencies",
        ),
        pytest.param(
            "complexity",
            {"root": "/repo", "path": None, "max_results": 7},
            ("/api/repo/complexity", {"root": "/repo", "path": None, "max_results": 7}),
            id="complexity-includes-null-path",
        ),
        pytest.param(
            "api_spec",
            {"root": "/repo", "framework": "fastapi"},
            ("/api/repo/api_spec", {"root": "/repo", "framework": "fastapi"}),
            id="api-spec",
        ),
        pytest.param(
            "dependency_slice",
            {
                "root": "/repo",
                "symbol": "HubClient.post",
                "path": "src/client.py",
                "depth": 3,
            },
            (
                "/api/repo/dependency_slice",
                {
                    "root": "/repo",
                    "symbol": "HubClient.post",
                    "path": "src/client.py",
                    "depth": 3,
                },
            ),
            id="dependency-slice",
        ),
        pytest.param(
            "hotspots",
            {"root": "/repo", "days": 14, "limit": 5},
            ("/api/repo/hotspots", {"root": "/repo", "days": 14, "limit": 5}),
            id="hotspots",
        ),
    ],
)
def test_sdk_wrappers_send_exact_route_and_payload(
    method, kwargs, expected, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from local_ai_hub.client import HubClient

    config = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 49191\nstate_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    calls: list[tuple[str, dict[str, object]]] = []

    def capture_post(
        path: str, payload: dict[str, object], timeout: float | None = None
    ):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr(client, "post", capture_post)
    assert getattr(client, method)(**kwargs) == {"ok": True}
    assert calls == [expected]
    client.close()


def test_mutating_post_reports_unknown_outcome_after_transport_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_ai_hub.client import HubClient

    config = tmp_path / "config.toml"
    state_dir = (tmp_path / "state").as_posix()
    config.write_text(
        f'[server]\nport = 49192\nstate_dir = "{state_dir}"\n',
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    attempts: list[str] = []

    def connection_lost(*_args: object, **_kwargs: object) -> bytes:
        attempts.append("sent")
        raise RuntimeError("transport failed after request write")

    monkeypatch.setattr(client, "_pooled_open", connection_lost)
    result = client.post(
        "/api/agent-state/tasks",
        {"action": "create", "root": str(tmp_path), "contract": {"goal": "bounded task"}},
        request_id="t19-task-1",
    )

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["request_id"] == "t19-task-1"
    assert attempts == ["sent"]
    client.close()
