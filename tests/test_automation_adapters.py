import json
import pytest

from local_ai_hub.automation import TargetPolicy
from local_ai_hub.automation_adapters import BrowserMCPAdapter, WinAppAdapter


class Transport:
    def __init__(self, result=None):
        self.result = result or {"url": "http://localhost:8765/", "text": "ok"}
        self.calls = []
        self.closed = False

    def call(self, code, timeout):
        self.calls.append((code, timeout))
        return self.result

    def close(self):
        self.closed = True


def test_browser_uses_fixed_code_and_owned_output_directory(tmp_path):
    transport = Transport()
    backend = BrowserMCPAdapter("isolated", {}, {"url": "http://localhost:8765/"},
                                TargetPolicy(["http://localhost:8765/"]), tmp_path, transport=transport)
    result = backend.execute({"command": "fill", "selector": "#input", "text": "'); throw Error('injected"}, 2)
    assert result["text"] == "ok"
    code = transport.calls[-1][0]
    assert "const request = " in code
    assert "JSON.stringify" in code
    assert "_localHubAutomation" in code
    assert "context.pages()" in code
    backend.close()
    assert transport.closed


def test_browser_unknown_command_and_unscoped_artifact_reject(tmp_path):
    transport = Transport({"artifact_path": str(tmp_path.parent / "foreign.png")})
    backend = BrowserMCPAdapter("isolated", {}, {"url": "http://localhost:8765/"},
                                TargetPolicy(["http://localhost:8765/"]), tmp_path, transport=transport)
    with pytest.raises(ValueError):
        backend.execute({"command": "evaluate", "code": "evil"}, 2)
    with pytest.raises(ValueError):
        backend.execute({"command": "screenshot"}, 2)
    backend.close()


@pytest.mark.parametrize("selector", ["iframe >> internal:control=enter-frame >> body", "xpath=//iframe", "internal:control=enter-frame"])
def test_browser_selector_cannot_enter_an_unowned_frame(tmp_path, selector):
    transport = Transport()
    backend = BrowserMCPAdapter("isolated", {}, {"url": "http://localhost:8765/"}, TargetPolicy(["http://localhost:8765/"]), tmp_path, transport=transport)
    try:
        with pytest.raises(ValueError):
            backend.execute({"command": "click", "selector": selector}, 2)
        assert not transport.calls
    finally:
        backend.close()


def test_desktop_requires_matching_window_executable_and_blocks_browser(tmp_path):
    exe = tmp_path / "app.exe"
    exe.touch()
    config = {"winapp_executable": str(exe), "allowed_applications": {"editor": str(exe)}}
    identity = {"exe": str(exe), "pid": 10, "creation_identity": "one"}
    output = []

    def runner(argv, **kwargs):
        output.append((argv, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": json.dumps({"value": "ok"}), "stdout_truncated": False})()

    backend = WinAppAdapter("desktop", config, {"application": "editor", "window_id": 123},
                            tmp_path, resolver=lambda hwnd: identity.copy(), runner=runner)
    backend.execute({"command": "set_value", "selector": "input", "text": "ordinary value"}, 2)
    assert output[-1][0] == [str(exe), "ui", "set-value", "input", "ordinary value", "-w", "123", "--json"]
    assert 0 < output[-1][1]["timeout"] <= 2
    assert output[-1][1].get("shell", False) is False
    identity["creation_identity"] = "two"
    with pytest.raises(PermissionError):
        backend.execute({"command": "inspect"}, 2)
    assert len(output) == 1
    identity["exe"] = str(tmp_path / "chrome.exe")
    with pytest.raises(PermissionError):
        WinAppAdapter("desktop", config, {"application": "editor", "window_id": 123},
                      tmp_path, resolver=lambda hwnd: identity.copy(), runner=runner)


def test_desktop_rejects_flag_injection_and_physical_input_by_default(tmp_path):
    exe = tmp_path / "app.exe"
    exe.touch()
    backend = WinAppAdapter("desktop", {"winapp_executable": str(exe), "allowed_applications": {"app": str(exe)}},
                            {"application": "app", "window_id": 1}, tmp_path,
                            resolver=lambda hwnd: {"exe": str(exe), "pid": 1, "creation_identity": "one"})
    for request in ({"command": "invoke", "selector": "--on"}, {"command": "press", "key": "WIN+R"},
                    {"command": "evaluate", "code": "evil"}, {"command": "fill", "selector": "field", "text": "x"}):
        with pytest.raises((ValueError, PermissionError)):
            backend.execute(request, 2)


def test_sandbox_resolves_guest_identity_and_never_falls_back_to_host(tmp_path):
    exe = tmp_path / "winapp.exe"
    exe.touch()
    config = {"winapp_executable": str(exe), "sandbox_enabled": True,
              "allowed_sandbox_applications": {"editor": r"C:\Windows\System32\notepad.exe"}}
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[1:4] == ["target", "exec", "sandbox"]:
            value = {"exe": r"C:\Windows\System32\notepad.exe", "pid": 42, "creation_identity": "one"}
        else:
            value = {"value": "guest value"}
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(value), "stdout_truncated": False})()
    backend = WinAppAdapter("desktop_sandbox", config, {"application": "editor", "window_id": 123}, tmp_path, runner=runner)
    assert backend.execute({"command": "get_value", "selector": "input"}, 3)["value"] == "guest value"
    assert all("sandbox" in argv for argv in calls)
    assert "--on" in calls[2]
    assert calls[2][calls[2].index("--on") + 1] == "sandbox"


def test_file_artifact_storage_preserves_image_only_contract(tmp_path):
    from local_ai_hub.artifacts import ArtifactStore, ArtifactTransportError
    store = ArtifactStore(tmp_path)
    with pytest.raises(ArtifactTransportError):
        store.put_bytes(b"downloaded", kind="automation-output", mime_type="application/octet-stream")
    identity = store.put_file_bytes(b"downloaded", kind="automation-output")
    assert identity.startswith("art_")
    metadata = store.get_binary(identity)
    assert metadata["success"], metadata
    assert metadata["mime_type"] == "application/octet-stream"
    assert metadata["encoding"] == "base64"
