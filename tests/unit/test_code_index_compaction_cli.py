from __future__ import annotations

import pytest

import tools.compact_code_index as compact_cli


@pytest.mark.parametrize("server_state", [True, None])
def test_apply_refuses_when_hub_is_online_or_offline_state_is_unknown(tmp_path, monkeypatch, capsys, server_state):
    monkeypatch.setattr(
        compact_cli,
        "load_config",
        lambda **_kwargs: {"server": {"state_dir": str(tmp_path), "host": "127.0.0.1", "port": 11435}},
    )
    monkeypatch.setattr(compact_cli, "_hub_is_online", lambda _host, _port, *_state_dir: server_state)
    monkeypatch.setattr(
        compact_cli,
        "compact_sqlite_database",
        lambda *_args, **_kwargs: pytest.fail("compaction must not run unless Hub is confirmed offline"),
    )

    exit_code = compact_cli.main(["--apply"])

    assert exit_code != 0
    output = capsys.readouterr().out
    assert "hub_online" in output or "hub_state_unknown" in output


def test_apply_fails_closed_when_timeout_and_listener_probe_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(compact_cli.socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(compact_cli, "_listener_state", lambda _port: None)
    monkeypatch.setattr(compact_cli, "_managed_hub_process_alive", lambda _state_dir: False)

    assert compact_cli._hub_is_online("127.0.0.1", 11435, tmp_path) is None


def test_apply_treats_listener_as_online_after_tcp_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(compact_cli.socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(compact_cli, "_listener_state", lambda _port: True)
    monkeypatch.setattr(compact_cli, "_managed_hub_process_alive", lambda _state_dir: False)

    assert compact_cli._hub_is_online("127.0.0.1", 11435, tmp_path) is True


def test_apply_confirms_offline_only_when_listener_and_managed_process_are_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(compact_cli.socket, "create_connection", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(compact_cli, "_listener_state", lambda _port: False)
    monkeypatch.setattr(compact_cli, "_managed_hub_process_alive", lambda _state_dir: False)

    assert compact_cli._hub_is_online("127.0.0.1", 11435, tmp_path) is False

    monkeypatch.setattr(compact_cli, "_managed_hub_process_alive", lambda _state_dir: True)
    assert compact_cli._hub_is_online("127.0.0.1", 11435, tmp_path) is True
