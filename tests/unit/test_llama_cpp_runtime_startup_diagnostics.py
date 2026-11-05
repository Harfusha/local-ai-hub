from __future__ import annotations

from unittest.mock import patch

from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime


def test_managed_port_conflict_sets_a_useful_startup_error(tmp_path):
    runtime = LlamaCppManagedRuntime(
        {
            "server": {"state_dir": str(tmp_path)},
            "llama_cpp": {"backend": "cuda", "managed_with_ollama": True},
        }
    )
    runtime._port_and_url = lambda: (12438, "http://127.0.0.1:12438")

    class PortProbe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def setsockopt(self, *_args):
            return None

        def bind(self, _address):
            raise OSError("address already in use")

    with (
        patch.object(runtime, "is_online", return_value=False),
        patch("local_ai_hub.llama_cpp_runtime.socket.socket", return_value=PortProbe()),
        patch.object(runtime, "provision") as provision,
    ):
        assert runtime.ensure_running() is False

    assert "12438" in runtime._last_error
    assert "address already in use" in runtime._last_error
    provision.assert_not_called()


def test_missing_managed_binary_sets_a_useful_startup_error(tmp_path):
    runtime = LlamaCppManagedRuntime(
        {
            "server": {"state_dir": str(tmp_path)},
            "llama_cpp": {"backend": "cuda", "managed_with_ollama": True},
        }
    )
    runtime._port_and_url = lambda: (12438, "http://127.0.0.1:12438")

    class PortProbe:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def setsockopt(self, *_args):
            return None

        def bind(self, _address):
            return None

    with (
        patch.object(runtime, "is_online", return_value=False),
        patch("local_ai_hub.llama_cpp_runtime.socket.socket", return_value=PortProbe()),
        patch.object(runtime, "_find_server", return_value=None),
        patch.object(runtime, "provision") as provision,
    ):
        assert runtime.ensure_running() is False

    assert "llama-server" in runtime._last_error
    assert "not found" in runtime._last_error
    provision.assert_called_once()
