from local_ai_hub.client import HubClient


def test_local_profile_cannot_auto_start_another_service(tmp_path, monkeypatch):
    config = tmp_path / "client.toml"
    config.write_text("[server]\nport=11435\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_AI_AGENT_PROFILE", "opencode-local")
    monkeypatch.setenv("LOCAL_AI_HUB_TOKEN", "")
    client = HubClient(config_path=str(config), auto_start=True)
    assert client.auto_start is False
    client.close()


def test_other_clients_retain_requested_auto_start(tmp_path, monkeypatch):
    config = tmp_path / "client.toml"
    config.write_text("[server]\nport=11435\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_AI_AGENT_PROFILE", "cloud-agent")
    client = HubClient(config_path=str(config), auto_start=True)
    assert client.auto_start is True
    client.close()
