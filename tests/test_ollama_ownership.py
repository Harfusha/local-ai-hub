from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("initial_online", [True, False])
def test_ensure_running_takes_over_local_external_ollama(tmp_path: Path, monkeypatch, initial_online: bool):
    import local_ai_hub.ollama as ollama_module
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime(
        {
            "server": {
                "state_dir": str(tmp_path),
                "ollama_url": "http://127.0.0.1:11434",
                "request_timeout_seconds": 0.1,
            },
            "headless": {"autostart_ollama": True, "manage_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "ollama": {"startup_timeout_seconds": 0.2},
        }
    )
    state = {"online": initial_online, "external_terminated": False, "spawns": 0}

    monkeypatch.setattr(runtime, "is_online", lambda: bool(state["online"]))
    monkeypatch.setattr(
        ollama_module,
        "find_listening_pid",
        lambda _port: 9001 if not state["external_terminated"] else None,
        raising=False,
    )
    monkeypatch.setattr(ollama_module, "process_executable", lambda _pid: r"C:\Ollama\ollama.exe")

    def terminate(pid: int, grace_seconds: float = 5.0) -> bool:
        assert pid == 9001
        state["external_terminated"] = True
        state["online"] = False
        return True

    monkeypatch.setattr(ollama_module, "terminate_tree", terminate)

    class Proc:
        pid = 9002

        def poll(self):
            return None

    def popen(*_args, **_kwargs):
        state["spawns"] += 1
        state["online"] = True
        return Proc()

    monkeypatch.setattr(ollama_module.subprocess, "Popen", popen)
    monkeypatch.setattr(ollama_module, "pid_alive", lambda pid: pid == 9002)

    assert runtime.ensure_running() is True
    assert state["external_terminated"] is True
    assert state["spawns"] == 1
    assert runtime.managed_pid_path.read_text(encoding="utf-8") == "9002"


def test_ensure_running_preserves_external_ollama_when_management_disabled(tmp_path: Path, monkeypatch):
    import local_ai_hub.ollama as ollama_module
    from local_ai_hub.ollama import OllamaRuntime

    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "headless": {"autostart_ollama": True, "manage_ollama": False},
            "llama_cpp": {"fallback_to_ollama": True},
        }
    )
    monkeypatch.setattr(runtime, "is_online", lambda: True)
    monkeypatch.setattr(ollama_module, "find_listening_pid", lambda _port: 9001, raising=False)
    monkeypatch.setattr(ollama_module, "process_executable", lambda _pid: r"C:\Ollama\ollama.exe")
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
            "ollama": {"startup_timeout_seconds": 1.0},
        }
    )
    monkeypatch.setattr(runtime.llama_cpp, "is_online", lambda: False)
    monkeypatch.setattr(runtime, "is_online", lambda: False)
    monkeypatch.setattr(ollama_module, "find_listening_pid", lambda _port: None, raising=False)

    terminated: list[int] = []
    monkeypatch.setattr(
        ollama_module,
        "terminate_tree",
        lambda pid, grace_seconds=5.0: terminated.append(pid) or True,
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
    monkeypatch.setattr(ollama_module.subprocess, "Popen", lambda *_args, **_kwargs: proc)

    assert runtime.ensure_running() is False
    assert terminated == [9003]
    assert proc.waited is True
    assert not runtime.managed_pid_path.exists()


def test_generated_agent_instructions_define_ollama_ownership():
    from local_ai_hub.generator import generate_skill_markdown

    generated = generate_skill_markdown({"headless": {"manage_ollama": True}})

    assert "Never run `ollama serve`" in generated
    assert "headless.manage_ollama = false" in generated
