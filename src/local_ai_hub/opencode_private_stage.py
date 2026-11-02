"""Temporary AppContainer staging access; not project filesystem confinement."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .opencode_pipe_identity import _valid_sid
from .opencode_runtime_stage import _reject_reparse_ancestors
from .opencode_sandbox_session import SandboxSession


class PrivateStage:
    """Own one new private staging directory and its temporary ACL grants.

    Close only after the bound sandbox session has closed. Any unexpected
    reparse point or directory replacement leaves the tree in place for review.
    This does not grant access to a user's project.
    """

    def __init__(self, parent: Path):
        if os.name != "nt":
            raise ValueError("private staging requires Windows")
        self.parent = Path(parent)
        self.path = None
        self._identity = None
        self._session = None
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise RuntimeError("private stage cannot be reused")
        self._entered = True
        if not self.parent.is_absolute() or not self.parent.is_dir():
            raise ValueError("staging parent must be an absolute directory")
        _reject_reparse_ancestors(self.parent, Path(self.parent.anchor))
        self.path = Path(tempfile.mkdtemp(prefix="lah-opencode-", dir=self.parent))
        info = self.path.lstat()
        self._identity = (info.st_dev, info.st_ino)
        return self

    def _validate(self):
        if self.path is None or self._identity is None or self.path.parent != self.parent:
            raise RuntimeError("private stage is unavailable")
        _reject_reparse_ancestors(self.path, Path(self.path.anchor))
        info = self.path.lstat()
        if (info.st_dev, info.st_ino) != self._identity:
            raise RuntimeError("private staging directory was replaced")
        count = 0
        def fail(error):
            raise error
        for directory, names, files in os.walk(self.path, followlinks=False, onerror=fail):
            for name in (*names, *files):
                count += 1
                if count > 25_000:
                    raise RuntimeError("private staging file limit exceeded")
                entry = Path(directory) / name
                stat = entry.lstat()
                if entry.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                    raise RuntimeError("private staging tree contains a reparse point")

    def grant(self, session: SandboxSession) -> None:
        if self._session is not None or not isinstance(session, SandboxSession) or session._state != "open" or session._used:
            raise RuntimeError("an unused open sandbox session is required")
        sid = session.profile.sid
        if not _valid_sid(sid):
            raise ValueError("invalid AppContainer SID")
        self._validate()
        self._session = session
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            raise RuntimeError("system directory is unavailable")
        icacls = Path(system_root) / "System32" / "icacls.exe"
        for options in (("/grant", f"*{sid}:(OI)(CI)(F)"), ("/setintegritylevel", "(OI)(CI)L")):
            self._validate()
            result = subprocess.run([str(icacls), str(self.path), *options, "/T", "/L", "/Q"],
                                    capture_output=True, timeout=120, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise OSError("private staging ACL update failed")
        self._validate()

    def close(self):
        if self.path is None:
            return
        if self._session is not None and not self._session.cleanup_confirmed:
            raise RuntimeError("close the sandbox session with confirmed cleanup before removing its private stage")
        self._validate()
        shutil.rmtree(self.path)
        self.path = None
        self._identity = None

    def __exit__(self, exc_type, exc, traceback):
        self.close()
