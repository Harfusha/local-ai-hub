import os
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from local_ai_hub.opencode_private_stage import PrivateStage
from local_ai_hub.opencode_sandbox_session import SandboxSession

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")


def test_private_stage_grants_only_its_owned_directory_and_cleans_up(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    icacls = Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe"
    original_acl = subprocess.run([str(icacls), str(unrelated)], capture_output=True, check=True, timeout=10).stdout
    with PrivateStage(tmp_path) as stage:
        owned = stage.path
        executable = owned / "node.exe"
        shutil.copyfile(node, executable)
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
        env.update({"TEMP": str(owned), "TMP": str(owned)})
        with SandboxSession(1, 1) as session:
            stage.grant(session)
            with pytest.raises(RuntimeError, match="close the sandbox"):
                stage.close()
            script = ("const fs=require('fs');let denied=false;"
                      f"try{{fs.writeFileSync({json.dumps(str(unrelated))},'bad')}}catch{{denied=true}};"
                      "fs.writeFileSync('result.txt',JSON.stringify({denied}))")
            result = session.run([str(executable), "-e", script],
                                 cwd=owned, env=env, timeout=15)
            assert result == 0
            assert json.loads((owned / "result.txt").read_text(encoding="utf-8")) == {"denied": True}
        assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not owned.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert subprocess.run([str(icacls), str(unrelated)], capture_output=True, check=True, timeout=10).stdout == original_acl


def test_private_stage_preserves_tree_if_reparse_point_appears(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    stage = PrivateStage(tmp_path).__enter__()
    link = stage.path / "link"
    try:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            command = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
            result = subprocess.run([str(command), "/d", "/c", "mklink", "/J", str(link), str(target)],
                                    capture_output=True, check=False, timeout=10)
            if result.returncode:
                pytest.skip("directory link creation unavailable")
        with pytest.raises(RuntimeError, match="reparse point"):
            stage.close()
        assert marker.read_text(encoding="utf-8") == "keep"
    finally:
        if link.is_symlink() or os.path.isjunction(link):
            os.rmdir(link)
        stage.close()
