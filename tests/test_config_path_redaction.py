from pathlib import PurePosixPath

import local_ai_hub.http_server as http_server


def test_config_file_label_hides_windows_path_on_posix(monkeypatch):
    monkeypatch.setattr(http_server, "Path", PurePosixPath)

    assert (
        http_server._safe_config_file_label(r"C:\Users\private\hub.toml")
        == "hub.toml"
    )
