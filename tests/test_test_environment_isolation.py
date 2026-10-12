from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from local_ai_hub.operational_mode import set_operational_mode


def test_pytest_collection_ignores_inherited_operator_gaming(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    operator_state = tmp_path / "operator-state"
    operator_config = tmp_path / "operator.toml"
    operator_config.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        "port = 11435\n"
        "state_dir = " + json.dumps(operator_state.as_posix()) + "\n",
        encoding="utf-8",
    )
    set_operational_mode(operator_state, "gaming")
    operator_config_bytes = operator_config.read_bytes()
    operator_state_path = operator_state / "operational_mode.json"
    operator_state_bytes = operator_state_path.read_bytes()
    parent_config = ("LOCAL_AI_CONFIG" in os.environ, os.environ.get("LOCAL_AI_CONFIG"))

    child_dir = tmp_path / "isolated-pytest"
    child_dir.mkdir()
    shutil.copyfile(root / "tests" / "conftest.py", child_dir / "conftest.py")
    (child_dir / "test_probe.py").write_text(
        textwrap.dedent(
            '''
            import json
            import os
            import tempfile
            from pathlib import Path

            from local_ai_hub import mcp_server
            from local_ai_hub.config import load_config
            from local_ai_hub.operational_mode import load_operational_mode, set_operational_mode

            _DEFAULT = load_config()
            _DEFAULT_STATE = Path(_DEFAULT["server"]["state_dir"]).resolve()
            _OPERATOR_CONFIG = Path(os.environ["LOCAL_AI_OPERATOR_CONFIG"]).resolve()
            _OPERATOR_STATE = Path(os.environ["LOCAL_AI_OPERATOR_STATE"]).resolve()

            def test_collection_loaded_private_active_mcp_config():
                assert Path(_DEFAULT["_config_path"]).resolve() == Path(os.environ["LOCAL_AI_CONFIG"]).resolve()
                assert Path(_DEFAULT["_config_path"]).resolve() != _OPERATOR_CONFIG
                assert Path(_DEFAULT["_config_path"]).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
                assert _DEFAULT_STATE.is_relative_to(Path(_DEFAULT["_config_path"]).resolve().parent)
                assert _DEFAULT_STATE != _OPERATOR_STATE
                assert _DEFAULT["server"]["port"] != 11435
                assert _DEFAULT["server"]["bind"] == "127.0.0.1"
                assert _DEFAULT["server"]["auto_start_ollama"] is False
                assert load_operational_mode(_OPERATOR_STATE).mode == "gaming"
                assert load_operational_mode(_DEFAULT_STATE).mode == "active"
                assert Path(mcp_server.CFG["server"]["state_dir"]).resolve() == _DEFAULT_STATE
                assert mcp_server._operational_mode_rejection("run") is None

            def test_explicit_gaming_config_still_blocks(tmp_path, monkeypatch):
                state_dir = tmp_path / "intentional-gaming-state"
                config_path = tmp_path / "intentional-gaming.toml"
                config_path.write_text(
                    chr(10).join(
                        [
                            "[server]",
                            'bind = "127.0.0.1"',
                            f"port = {_DEFAULT['server']['port']}",
                            "auto_start_ollama = false",
                            "state_dir = " + json.dumps(state_dir.as_posix()),
                        ]
                    )
                    + chr(10),
                    encoding="utf-8",
                )
                set_operational_mode(state_dir, "gaming")
                monkeypatch.setenv("LOCAL_AI_CONFIG", str(config_path))
                explicit = load_config()
                monkeypatch.setattr(mcp_server, "CFG", explicit)
                assert Path(explicit["server"]["state_dir"]).resolve() == state_dir.resolve()
                rejection = mcp_server._operational_mode_rejection("run")
                assert rejection["error_code"] == "operational_mode_blocked"
                assert rejection["retryable"] is True
            '''
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(operator_config)
    env["LOCAL_AI_OPERATOR_CONFIG"] = str(operator_config)
    env["LOCAL_AI_OPERATOR_STATE"] = str(operator_state)
    search_path = [str(root / "src"), str(root)]
    if env.get("PYTHONPATH"):
        search_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(search_path)
    runner = textwrap.dedent(
        """
        import os
        import sys
        import pytest

        before = ("LOCAL_AI_CONFIG" in os.environ, os.environ.get("LOCAL_AI_CONFIG"))
        assert before[0] and before[1] == sys.argv[-2]
        child_dir = sys.argv[-1]
        result = pytest.main([
            "-q", "--confcutdir", child_dir, "--rootdir", child_dir, child_dir,
        ])
        after = ("LOCAL_AI_CONFIG" in os.environ, os.environ.get("LOCAL_AI_CONFIG"))
        if after != before:
            raise SystemExit("pytest_unconfigure did not restore LOCAL_AI_CONFIG")
        raise SystemExit(int(result))
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            runner,
            str(operator_config),
            str(child_dir),
        ],
        cwd=child_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert ("LOCAL_AI_CONFIG" in os.environ, os.environ.get("LOCAL_AI_CONFIG")) == parent_config
    assert operator_config.read_bytes() == operator_config_bytes
    assert operator_state_path.read_bytes() == operator_state_bytes
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "2 passed" in result.stdout
