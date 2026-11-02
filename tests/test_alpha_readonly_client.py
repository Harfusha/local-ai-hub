import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("setting", ["preprocessing", "watcher", "code_intelligence", "none", "wrong_fields"])
def test_alpha_client_rejects_workspace_writing_backends(tmp_path, setting):
    script = Path(__file__).resolve().parents[1] / "docs/agent-evaluation/fixtures/alpha_readonly_mcp.py"
    shutil.copyfile(script, tmp_path / script.name)
    workspace = tmp_path / "workspace"
    (workspace / "repo").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    source = tmp_path / "source"
    (source / "src/local_ai_hub").mkdir(parents=True)
    (source / "src/local_ai_hub/mcp_server.py").touch()
    (tmp_path / "source.txt").write_text(str(source), encoding="utf-8")
    flags = {"preprocessing": False, "watcher": False, "code_intelligence": False}
    if setting not in {"none", "wrong_fields"}:
        flags[setting] = True
    boolean = lambda value: str(value).lower()
    config = (
        '[server]\nbind = "127.0.0.1"\nport = 34567\n'
        f'state_dir = {json.dumps((tmp_path / "state").as_posix())}\n'
        '[security]\napi_token = "' + 'x' * 32 + '"\n'
        f'allowed_roots = [{json.dumps(workspace.as_posix())}]\n'
        f'[preprocessing]\nenabled = {boolean(flags["preprocessing"])}\n'
        f'fs_watcher_enabled = {boolean(flags["watcher"])}\n'
        f'[code_intelligence]\nenabled = {boolean(flags["code_intelligence"])}\n'
    )
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    kind = "artifact" if setting == "wrong_fields" else "repo"
    payload = '{"action":"source","path":"config.py","start_line":1}' if setting == "wrong_fields" else '{"action":"preprocess"}'
    result = subprocess.run(
        [sys.executable, "-B", str(tmp_path / script.name), kind, payload],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    expected = "line_start" if setting == "wrong_fields" else (
        "only bounded alpha" if setting == "none" else "invalid isolated alpha Hub configuration"
    )
    assert expected in result.stderr
