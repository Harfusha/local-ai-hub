"""Install a built native desktop into an existing trusted Hub installation.

No downloads, shell invocation, service lifecycle action, or system-wide write.
Use the binary and SHA-256 receipt produced by the native desktop CI.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def install(binary: Path, root: Path, expected_sha256: str) -> Path:
    root = root.resolve(strict=True)
    if not (root / "tools/hubctl.py").is_file() or not (root / "tools/desktop.py").is_file():
        raise ValueError("Choose a trusted Local AI Hub installation containing hubctl.py and desktop.py")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256):
        raise ValueError("A valid SHA-256 receipt is required")
    name = "local-ai-hub-desktop.exe" if os.name == "nt" else "local-ai-hub-desktop"
    if binary.name != name or not binary.is_file():
        raise ValueError(f"Choose the built {name} for this operating system")
    destination_dir = root / "bin"
    if destination_dir.is_symlink():
        raise ValueError("Hub bin directory must not be a symbolic link")
    destination_dir.mkdir(exist_ok=True)
    if destination_dir.resolve() != destination_dir:
        raise ValueError("Hub bin directory escapes the installation")
    target = destination_dir / name
    if target.is_symlink():
        raise ValueError("Desktop destination must not be a symbolic link")
    fd, filename = tempfile.mkstemp(prefix=".desktop-install-", dir=destination_dir)
    tmp = Path(filename)
    try:
        with os.fdopen(fd, "wb") as output, binary.open("rb") as source:
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        with tmp.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != expected_sha256.lower():
            raise ValueError("Desktop SHA-256 verification failed")
        if os.name != "nt":
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    try:
        target = install(args.binary, args.root, args.sha256)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Desktop installation failed: {exc}\n")
    print(f"Installed {target}. Run python tools/hubctl.py desktop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
