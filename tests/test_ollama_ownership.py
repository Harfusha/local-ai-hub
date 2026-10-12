from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("initial_online", [True, False])
def test_ensure_running_borrows_online_or_starts_owned_ollama(tmp_path: Path, monkeypatch, initial_online: bool):
    import local_ai_hub.ollama as module
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime({
        "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
        "headless": {"autostart_ollama": True, "manage_ollama": True},
        "ollama": {"enabled": True},
    })
    state = {"online": initial_online, "spawns": 0}
    monkeypatch.setattr(runtime, "is_online", lambda: state["online"])
    monkeypatch.setattr(module, "terminate_tree", lambda *_a, **_k: pytest.fail("foreign endpoint cannot authorize takeover"))

    class Proc:
        pid = 9002

        def poll(self):
            return None

    def popen(*_args, **kwargs):
        state["spawns"] += 1
        state["online"] = True
        return Proc()

    owner = {"pid": 9002, "executable": "ollama", "creation_identity": 123,
             "creation_identity_type": "test", "state_dir": str(tmp_path), "role": "ollama"}
    monkeypatch.setattr(module, "popen_managed", popen)
    monkeypatch.setattr(module, "process_owner_record", lambda *_a: dict(owner))
    monkeypatch.setattr(module, "set_process_priority", lambda *_a: True)
    assert runtime.ensure_running() is True
    assert state["spawns"] == (0 if initial_online else 1)
    assert runtime.managed_owner_path.exists() is (not initial_online)
    assert runtime.managed_pid_path.exists() is (not initial_online)


def test_ensure_running_preserves_external_ollama_when_management_disabled(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as ollama_module
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "headless": {"autostart_ollama": True, "manage_ollama": False},
            "llama_cpp": {"fallback_to_ollama": True},
            "ollama": {"enabled": True},
        }
    )
    monkeypatch.setattr(runtime, "is_online", lambda: True)
    monkeypatch.setattr(ollama_module, "find_listening_pid", lambda _port: 9001, raising=False)
    monkeypatch.setattr(ollama_module, "process_executable", lambda _pid: r"C:\Ollama\ollama.exe", raising=False)
    monkeypatch.setattr(
        ollama_module,
        "terminate_tree",
        lambda *_args, **_kwargs: pytest.fail("user-managed Ollama must not be terminated"),
    )

    assert runtime.ensure_running() is True


def test_ensure_running_cleans_process_when_startup_never_becomes_healthy(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as ollama_module
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime(
        {
            "server": {
                "state_dir": str(tmp_path),
                "ollama_url": "http://127.0.0.1:11434",
                "request_timeout_seconds": 0.01,
            },
            "headless": {"autostart_ollama": True, "manage_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "ollama": {"enabled": True, "startup_timeout_seconds": 1.0},
        }
    )
    monkeypatch.setattr(runtime.llama_cpp, "is_online", lambda: False)
    monkeypatch.setattr(runtime, "is_online", lambda: False)
    monkeypatch.setattr(ollama_module, "find_listening_pid", lambda _port: None, raising=False)

    terminated: list[int] = []
    monkeypatch.setattr(
        ollama_module,
        "terminate_tree",
        lambda pid, grace_seconds=5.0, process_handle=None: terminated.append(pid) or True,
    )

    class Proc:
        pid = 9003

        def __init__(self) -> None:
            self.waited = False

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.waited = True
            return 1

        def kill(self):
            return None

    proc = Proc()
    monkeypatch.setattr(ollama_module, "popen_managed", lambda *_args, **_kwargs: proc)

    assert runtime.ensure_running() is False
    assert terminated == [9003]
    assert proc.waited is True
    assert not runtime.managed_pid_path.exists()


def test_generated_agent_instructions_define_ollama_ownership():
    from local_ai_hub.generator import generate_skill_markdown

    generated = generate_skill_markdown({"ollama": {"enabled": True}, "headless": {"manage_ollama": True}})

    assert "Never run `ollama serve`" in generated
    assert "headless.manage_ollama = false" in generated
def test_gaming_unload_covers_every_loaded_ollama_model():
    from types import SimpleNamespace

    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime.__new__(OllamaRuntime)
    runtime.config = {"ollama": {"enabled": True}, "models": {"chat": "configured:7b"}}
    runtime.llama_cpp = SimpleNamespace()
    runtime._invalidate_loaded_cache = lambda: None
    unloads = []

    def request(endpoint, payload=None, *, timeout=None, deadline=None, should_stop=None):
        if endpoint == "/api/ps":
            return {"models": [] if unloads else [{"name": "configured:7b"}, {"name": "", "model": "runtime-only:9b"}]}
        unloads.append(payload["model"])
        return {"done_reason": "unload"}

    runtime.request = request

    result = runtime.unload_configured_models()

    assert result["success"] is True
    assert unloads == ["configured:7b", "runtime-only:9b"]
