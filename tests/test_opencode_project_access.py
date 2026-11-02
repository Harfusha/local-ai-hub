import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from local_ai_hub.opencode_private_stage import PrivateStage
from local_ai_hub.opencode_sandbox_session import SandboxSession

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")


def test_disposable_project_acl_probe(tmp_path):
    import win32security
    import ntsecuritycon
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    project = tmp_path / "project"
    project.mkdir()
    target = project / "sample.txt"
    target.write_text("original", encoding="utf-8")
    def dacl(path):
        descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(descriptor, win32security.SDDL_REVISION_1, win32security.DACL_SECURITY_INFORMATION)
    before = {str(path): dacl(path) for path in (project, target)}
    with PrivateStage(tmp_path) as stage:
        executable = stage.path / "node.exe"
        shutil.copyfile(node, executable)
        with SandboxSession(1, 1) as session:
            stage.grant(session)
            sid = session.profile.sid
            principal = win32security.ConvertStringSidToSid(sid)
            for item in (project, target):
                descriptor = win32security.GetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION)
                acl = descriptor.GetSecurityDescriptorDacl()
                mask = ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_WRITE | ntsecuritycon.FILE_GENERIC_EXECUTE | ntsecuritycon.DELETE
                acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 0, mask, principal)
                if item == project:
                    flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE | win32security.INHERIT_ONLY_ACE
                    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, mask, principal)
                descriptor.SetSecurityDescriptorDacl(1, acl, 0)
                win32security.SetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION, descriptor)
            script = ("const fs=require('fs');let out={};"
                      f"try{{out.read=fs.readFileSync({json.dumps(str(target))},'utf8')}}catch(e){{out.readError=e.code}};"
                      f"try{{fs.writeFileSync({json.dumps(str(target))},'changed');out.write=true}}catch(e){{out.writeError=e.code}};"
                      f"try{{fs.writeFileSync({json.dumps(str(project / 'new.txt'))},'new');out.created=true;fs.appendFileSync({json.dumps(str(project / 'new.txt'))},'!');out.new=true}}catch(e){{out.newError=e.code}};"
                      f"try{{fs.mkdirSync({json.dumps(str(project / 'nested'))});fs.writeFileSync({json.dumps(str(project / 'nested' / 'code.py'))},'a');fs.appendFileSync({json.dumps(str(project / 'nested' / 'code.py'))},'b');out.nested=true}}catch(e){{out.nestedError=e.code}};"
                      "fs.writeFileSync('result.json',JSON.stringify(out))")
            env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PATH") if key in os.environ}
            env.update({"TEMP": str(stage.path), "TMP": str(stage.path)})
            assert session.run([str(executable), "-e", script], cwd=stage.path, env=env, timeout=15) == 0
            result = json.loads((stage.path / "result.json").read_text(encoding="utf-8"))
            print("PROJECT_ACL_PROBE", json.dumps(result))
            assert result.get("read") == "original"
            assert result.get("write") is True
            assert result.get("new") is True
            assert result.get("nested") is True
        for item in (project / "nested" / "code.py", project / "nested", project / "new.txt", target, project):
            descriptor = win32security.GetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION)
            acl = descriptor.GetSecurityDescriptorDacl()
            for index in reversed(range(acl.GetAceCount())):
                if acl.GetAce(index)[-1] == principal:
                    acl.DeleteAce(index)
            descriptor.SetSecurityDescriptorDacl(1, acl, 0)
            win32security.SetFileSecurity(str(item), win32security.DACL_SECURITY_INFORMATION, descriptor)
    after = {str(path): dacl(path) for path in (project, target)}
    assert after == before
    for item in (project, target, project / "new.txt", project / "nested", project / "nested" / "code.py"):
        assert sid not in dacl(item)
    assert target.read_text(encoding="utf-8") == "changed"
    assert (project / "nested" / "code.py").read_text(encoding="utf-8") == "ab"


def test_windows_pinned_file_can_still_gain_a_hardlink(tmp_path):
    import win32con
    import win32file

    target = tmp_path / "file.txt"
    target.write_text("keep", encoding="utf-8")
    link = tmp_path / "hardlink.txt"
    handle = win32file.CreateFile(str(target), win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.DELETE,
                                  win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING, 0, None)
    try:
        os.link(target, link)
        assert os.path.samefile(target, link)
    finally:
        handle.Close()
    link.unlink()
    assert target.read_text(encoding="utf-8") == "keep"
