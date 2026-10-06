from __future__ import annotations

import socket

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def test_autostart_launches_real_hub_child_and_returns_http_search_result(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "needle.py").write_text(
        'def find_marker():\n    return "T04_REAL_CHILD_MARKER"\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    config_path = tmp_path / "real-child.toml"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {port}\nstate_dir = "{state_dir.as_posix()}"\n'
        "[client]\nstartup_wait_seconds = 15\nstartup_poll_seconds = 0.05\nhealth_timeout_seconds = 0.25\n"
        "[ollama]\nenabled = false\n"
        "[smart_ollama]\nenabled = false\n"
        "[llama_cpp]\nmode = \"off\"\n"
        "[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n"
        "[preprocessing]\nenabled = false\n",
        encoding="utf-8",
    )
    client = HubClient(tenant="t04-real-child", config_path=str(config_path), auto_start=True)
    assert client.config["llama_cpp"]["mode"] == "off"
    assert client.config["ollama"]["enabled"] is False
    assert client.config["smart_ollama"]["enabled"] is False
    assert client.config["code_intelligence"]["enabled"] is False
    assert client.config["code_intelligence"]["serena_enabled"] is False
    assert client.config["code_intelligence"]["preprocess_serena"] is False
    assert client.config["preprocessing"]["enabled"] is False
    with client_module._DETACHED_CHILDREN_LOCK:
        existing_child_ids = {id(child) for child in client_module._DETACHED_CHILDREN}

    try:
        result = client.post(
            "/api/search",
            {"root": str(repo), "query": "T04_REAL_CHILD_MARKER", "top_k": 3},
            request_id="t04-real-child-search",
            timeout=30,
        )
        assert result["success"] is True
        assert any(
            hit.get("path") == "needle.py" and "T04_REAL_CHILD_MARKER" in hit.get("text", "")
            for hit in result.get("results", [])
        )
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        assert len(started_children) == 1
        child = started_children[0]
        assert isinstance(child, client_module.subprocess.Popen)
        assert child.poll() is None
        assert (state_dir / "hub.pid").read_text(encoding="utf-8").strip() == str(child.pid)
        assert not (state_dir / "hub.start.lock").exists()
    finally:
        client._drop_connection()
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        for child in started_children:
            client_module._stop_owned_child(child)
        assert all(child.poll() is not None for child in started_children), (
            "test-owned Hub child remained alive after exact-handle cleanup"
        )
