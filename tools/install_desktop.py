"""Install a built native desktop into an existing trusted Hub installation.

Accepts a local binary or a verified, exact stable release archive. No shell
invocation, service lifecycle action, or system-wide write.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import re
import zipfile
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def install(binary: Path, root: Path, expected_sha256: str, *, version: str | None = None) -> Path:
    from tools.update_transaction import _has_link_component
    if version is None:
        raise ValueError("A version is required for every desktop installation")
    if _has_link_component(root):
        raise ValueError("Installation root contains a link or junction")
    root = root.resolve(strict=True)
    if not (root / "tools/hubctl.py").is_file() or not (root / "tools/desktop.py").is_file():
        raise ValueError("Choose a trusted Local AI Hub installation containing hubctl.py and desktop.py")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256):
        raise ValueError("A valid SHA-256 receipt is required")
    name = "local-ai-hub-desktop.exe" if os.name == "nt" else "local-ai-hub-desktop"
    if binary.name != name or not binary.is_file():
        raise ValueError(f"Choose the built {name} for this operating system")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid installed release version")
    destination_dir = root / "bin" / "desktop" / version
    if _has_link_component(destination_dir):
        raise ValueError("Desktop directory contains a link or junction")
    destination_dir.mkdir(parents=True, exist_ok=True)
    if _has_link_component(destination_dir) or destination_dir.resolve() != destination_dir:
        raise ValueError("Hub bin directory escapes the installation")
    target = destination_dir / name
    if _has_link_component(target):
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
    retired = root / "bin" / name
    if retired != target and (retired.is_file() or retired.is_symlink()):
        try:
            retired.unlink()
        except PermissionError as exc:
            print(
                "Update installed the versioned desktop, but the retired binary is still in use; "
                f"close it and rerun the update to finish migration: {exc}",
                file=sys.stderr,
            )
    return target


def platform_asset() -> tuple[str, str, str]:
    system = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"amd64": "X64", "x86_64": "X64", "arm64": "ARM64", "aarch64": "ARM64"}.get(machine)
    if (system, arch) not in {("Linux", "X64"), ("Windows", "X64"), ("macOS", "X64"), ("macOS", "ARM64")}:
        raise ValueError("No official desktop binary for this platform; build from source")
    return system, arch, "local-ai-hub-desktop.exe" if system == "Windows" else "local-ai-hub-desktop"


def verify_archive(raw: bytes, *, version: str, revision: str, system: str, arch: str) -> tuple[dict, bytes]:
    name = "local-ai-hub-desktop.exe" if system == "Windows" else "local-ai-hub-desktop"
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Desktop archive exceeds 64 MiB")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        base_entries = {name, "SHA256SUMS", "README.txt", "desktop-receipt.json"}
        auxiliary_limits = {"LICENSE": 128 * 1024, "THIRD-PARTY-NOTICES.txt": 16 * 1024 * 1024,
                            "Cargo.lock": 2 * 1024 * 1024}
        entries = archive.namelist()
        if len(entries) != len(set(entries)) or set(entries) not in (base_entries, base_entries | set(auxiliary_limits)):
            raise ValueError("Unexpected desktop archive entries")
        if any(archive.getinfo(entry).is_dir() for entry in entries):
            raise ValueError("Unexpected desktop archive directory")
        if (archive.getinfo(name).file_size > 32 * 1024 * 1024
                or archive.getinfo("desktop-receipt.json").file_size > 8192
                or archive.getinfo("SHA256SUMS").file_size > 8192
                or archive.getinfo("README.txt").file_size > 64 * 1024):
            raise ValueError("Oversized desktop archive entry")
        receipt = json.loads(archive.read("desktop-receipt.json"))
        if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in {
            "hub_version": version, "repository_revision": revision,
            "os": system, "architecture": arch, "binary": name,
        }.items()):
            raise ValueError("Desktop archive provenance mismatch")
        if type(receipt.get("format")) is not int or receipt["format"] != 2:
            raise ValueError("Only desktop archive format 2 is supported")
        expected_entries = base_entries | set(auxiliary_limits)
        if set(entries) != expected_entries:
            raise ValueError("Desktop archive format and entries disagree")
        binary = archive.read(name)
        digest = hashlib.sha256(binary).hexdigest()
        if not binary or receipt.get("sha256") != digest:
            raise ValueError("Desktop binary digest mismatch")
        auxiliary: dict[str, str] = {}
        for entry, limit in auxiliary_limits.items():
            if not 0 < archive.getinfo(entry).file_size <= limit:
                raise ValueError("Missing or oversized desktop license/lock evidence")
            auxiliary[entry] = hashlib.sha256(archive.read(entry)).hexdigest()
        if receipt.get("auxiliary_sha256") != auxiliary:
            raise ValueError("Desktop license/lock evidence digest mismatch")
        checksum_bytes = (f"{digest}  {name}\n" + "".join(
            f"{sha}  {entry}\n" for entry, sha in sorted(auxiliary.items())
        )).encode("utf-8")
        # Compare exact generated checksum lines; no arbitrary extraction.
        if archive.read("SHA256SUMS") != checksum_bytes:
            raise ValueError("Desktop SHA256SUMS disagrees with verified entries")
        return receipt, binary


def install_release(root: Path, version: str, revision: str) -> Path:
    """Fetch exact official stable asset, never an unpinned latest build."""
    from tools.auto_update import REPOSITORY, DOWNLOAD_URL, RECEIPT_NAME, _asset_digest, read_url
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Exact stable version and source revision required")
    system, arch, name = platform_asset()
    tag = "v" + version
    release = json.loads(read_url(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}", 1024 * 1024))
    if not isinstance(release, dict) or release.get("tag_name") != tag or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("No matching published stable release")
    assets = release.get("assets")
    receipt = read_url(f"{DOWNLOAD_URL}/{tag}/{RECEIPT_NAME}", 65536)
    if hashlib.sha256(receipt).hexdigest() != _asset_digest(assets, RECEIPT_NAME):
        raise ValueError("Release receipt digest mismatch")
    wheel_receipt = json.loads(receipt)
    if (not isinstance(wheel_receipt, dict) or wheel_receipt.get("repository_revision") != revision or wheel_receipt.get("success") is not True
            or wheel_receipt.get("smoke") != "passed"):
        raise ValueError("Release receipt does not verify the requested source revision")
    asset = f"local-ai-hub-desktop-{system}-{arch}.zip"
    expected = _asset_digest(assets, asset)
    raw = read_url(f"{DOWNLOAD_URL}/{tag}/{asset}", 64 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Desktop release archive digest mismatch")
    try:
        metadata, binary = verify_archive(raw, version=version, revision=revision, system=system, arch=arch)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid desktop release archive") from exc
    with tempfile.TemporaryDirectory(prefix="lah-desktop-release-") as directory:
        path = Path(directory) / name
        path.write_bytes(binary)
        return install(path, root, metadata["sha256"], version=version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, nargs="?")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--sha256")
    parser.add_argument("--version")
    parser.add_argument("--revision")
    parser.add_argument("--from-release", action="store_true")
    args = parser.parse_args()
    try:
        if args.from_release:
            if args.binary or args.sha256 or not args.version or not args.revision:
                parser.error("Official release install requires --version and --revision, without binary or SHA argument")
            target = install_release(args.root, args.version, args.revision)
        else:
            if args.binary is None or not args.sha256 or not args.version or args.revision:
                parser.error("Local install requires binary, --sha256 and --version")
            target = install(args.binary, args.root, args.sha256, version=args.version)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Desktop installation failed: {exc}\n")
    print(f"Installed {target}. Run python tools/hubctl.py desktop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
