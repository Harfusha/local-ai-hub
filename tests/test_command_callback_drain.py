import json
import sys
import threading

from local_ai_hub.app import LocalAIApp


def _app(tmp_path):
    config = tmp_path / "isolated.toml"
    config.write_text("[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
                      + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
                      + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
                      + "\n[preprocessing]\nenabled = false\n", encoding="utf-8")
    return LocalAIApp(str(config))


def test_delivered_callback_does_not_depend_on_worker_exit(tmp_path, monkeypatch):
    app = _app(tmp_path)
    delivered = []
    original = threading.Thread.is_alive
    monkeypatch.setattr(threading.Thread, "is_alive", lambda thread: True if thread.name == "command-log-callback" else original(thread))
    try:
        result = app.commands._execute([sys.executable, "-c", "print('ok')"], str(tmp_path), 10,
                                       log_callback=lambda stream, text: delivered.append((stream, text)))
        assert result["success"] is True
        assert any("ok" in text for _, text in delivered)
        assert result.get("log_callback_delivery_unconfirmed", False) is False
    finally:
        app.close()


def test_blocked_callback_remains_unconfirmed(tmp_path):
    app = _app(tmp_path)
    release = threading.Event()
    app.commands.post_kill_drain_seconds = 0.1
    try:
        result = app.commands._execute([sys.executable, "-c", "print('ok')"], str(tmp_path), 10,
                                       log_callback=lambda _stream, _text: release.wait(timeout=5))
        assert result.get("log_callback_delivery_unconfirmed") is True
    finally:
        release.set()
        app.close()
