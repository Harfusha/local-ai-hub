"""Check or apply an official stable release to a managed Hub installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))

from tools.install_ownership import MANIFEST_NAME, read_install_manifest  # noqa: E402
from tools.prepare_release import version_parts  # noqa: E402
from tools.setup_report import write_install_report  # noqa: E402
from tools.update_transaction import _has_link_component, _is_link, update_recovery_path  # noqa: E402

REPOSITORY = "Harfusha/local-ai-hub"
GIT_URL = f"https://github.com/{REPOSITORY}.git"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
DOWNLOAD_URL = f"https://github.com/{REPOSITORY}/releases/download"
RELEASE_HOSTS = {"github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
RECEIPT_NAME = "wheel-mcp-smoke.json"


@dataclass(frozen=True)
class Release:
    tag: str
    revision: str
    wheel_name: str
    wheel_digest: str

    @property
    def version(self) -> str:
        return self.tag[1:]


class _ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urlsplit(newurl)
        if destination.scheme != "https" or destination.netloc not in RELEASE_HOSTS:
            raise ValueError("release download redirected outside GitHub HTTPS hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "Local-AI-Hub-Updater"})
    with build_opener(_ReleaseRedirect()).open(request, timeout=30) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError("release response exceeds the download size limit")
    return result


def _asset_digest(assets: object, name: str) -> str:
    if not isinstance(assets, list):
        raise ValueError("release asset list is missing")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    digest = matches[0].get("digest") if len(matches) == 1 else None
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"release requires exactly one {name} asset with a SHA-256 digest")
    return digest.removeprefix("sha256:")


def find_update(current: str) -> Release | None:
    installed = version_parts(current)
    try:
        release = json.loads(read_url(LATEST_URL, 1024 * 1024))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(release, dict):
        raise ValueError("invalid GitHub release response")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        return None
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("stable release is missing a version tag")
    version = tag[1:]
    if version_parts(version) <= installed:
        return None

    assets = release.get("assets")
    receipt_digest = _asset_digest(assets, RECEIPT_NAME)
    receipt_bytes = read_url(f"{DOWNLOAD_URL}/{tag}/{RECEIPT_NAME}", 64 * 1024)
    if hashlib.sha256(receipt_bytes).hexdigest() != receipt_digest:
        raise ValueError("release smoke receipt digest mismatch")
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict) or receipt.get("success") is not True or receipt.get("smoke") != "passed":
        raise ValueError("published release has no passing wheel smoke receipt")
    revision = receipt.get("repository_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("release smoke receipt has no verified commit")
    wheel = f"local_ai_hub-{version}-py3-none-any.whl"
    if receipt.get("wheel_file") != wheel:
        raise ValueError("release smoke receipt names a different wheel")
    wheel_digest = _asset_digest(assets, wheel)
    if receipt.get("wheel_sha256") != wheel_digest:
        raise ValueError("release wheel digest differs from the smoke receipt")
    return Release(tag, revision, wheel, wheel_digest)


def installed_version(root: Path) -> str:
    project = root / "pyproject.toml"
    if _has_link_component(project):
        raise ValueError(f"version metadata path contains a link: {project}")
    with project.open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    version_parts(version)
    return version


def managed_target(root: Path) -> None:
    git_markers = (directory / ".git" for directory in (root, *root.parents))
    if _has_link_component(root) or any(marker.exists() or _is_link(marker) for marker in git_markers):
        raise ValueError("automatic updates require a managed installation outside a Git checkout or linked directory")
    if _has_link_component(root / MANIFEST_NAME):
        raise ValueError("installation ownership marker contains a link")
    read_install_manifest(root)
    config = root / "config.toml"
    if _has_link_component(config) or not config.is_file():
        raise ValueError("managed installation is missing a regular config.toml")


def checkout_release(release: Release, destination: Path) -> None:
    destination.mkdir()
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "advice.detachedHead=false", *args], cwd=destination, env=env,
            check=True, timeout=180, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "--quiet")
    git("fetch", "--quiet", "--no-tags", "--depth=1", GIT_URL, f"refs/tags/{release.tag}")
    if git("rev-parse", "--verify", "FETCH_HEAD^{commit}") != release.revision:
        raise ValueError("published tag does not resolve to the verified commit")
    git("checkout", "--quiet", "--detach", release.revision)
    if git("status", "--porcelain=v1", "--untracked-files=all") or installed_version(destination) != release.version:
        raise ValueError("release checkout does not match the published version")
    manifest = json.loads((destination / "RELEASE.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "production-ready" or manifest.get("version") != release.version:
        raise ValueError("release checkout does not declare the published stable release")


def apply_update(release: Release, current: str, root: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="local-ai-hub-release-") as staging:
        stage = Path(staging)
        checkout = stage / "source"
        checkout_release(release, checkout)
        wheel_bytes = read_url(f"{DOWNLOAD_URL}/{release.tag}/{release.wheel_name}", 128 * 1024 * 1024)
        if hashlib.sha256(wheel_bytes).hexdigest() != release.wheel_digest:
            raise ValueError("downloaded release wheel does not match the verified digest")
        wheel = stage / release.wheel_name
        wheel.write_bytes(wheel_bytes)
        entry = checkout / "tools/update_install.py"
        if _has_link_component(entry) or not entry.is_file():
            raise ValueError("release is missing the managed update installer")
        report = stage / "result.json"
        process = subprocess.run([
            sys.executable, "-I", "-B", str(entry), str(root), str(wheel), release.wheel_digest,
            release.revision, release.version, current, str(report),
        ], cwd=stage, check=False)
        if not report.is_file():
            return {"success": False, "error": f"update installer exited without a result ({process.returncode})"}
        result = json.loads(report.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or result.get("success") is not (process.returncode == 0):
            return {"success": False, "error": "update installer returned inconsistent status"}
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the update during the scheduled maintenance window")
    parser.add_argument("--json", action="store_true", help="Print the release check as JSON")
    parser.add_argument("--expect-version")
    parser.add_argument("--expect-revision")
    parser.add_argument("--dashboard", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    expected = (args.expect_version, args.expect_revision)
    if any(expected) and (not args.apply or not all(expected)):
        parser.error("Both release pins require --apply")
    if args.dashboard and args.apply and not all(expected):
        parser.error("Dashboard installs require a reviewed version and commit")
    report_path: Path | None = None
    result: dict = {"checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        if args.apply or args.dashboard:
            managed_target(ROOT)
        if args.apply:
            if sys.prefix != sys.base_prefix:
                raise ValueError("run with system Python outside the managed virtual environment")
            report_path = ROOT / ("auto-update-dashboard.json" if args.dashboard else "auto-update-report.json")
            if _has_link_component(report_path):
                report_path = None
                raise ValueError("update report path contains a link")
            if args.dashboard:
                write_install_report(report_path, {
                    **result, "status": "installing", "target_version": args.expect_version, "revision": args.expect_revision,
                })
        if args.apply or args.dashboard:
            recovery = update_recovery_path(ROOT)
            if recovery.exists() or _is_link(recovery):
                raise ValueError(f"previous update requires recovery before another install: {recovery}")
        current = installed_version(ROOT)
        result["version_before"] = current
        update = find_update(current)
        if all(expected) and (update is None or (update.version, update.revision) != expected):
            raise ValueError("The reviewed release changed. Check for updates and review it again.")
        if update is None:
            if not args.json:
                print(f"Local AI Hub {current}: no newer verified stable release")
            result.update(success=True, status="up_to_date")
        else:
            if not args.json:
                print(f"Local AI Hub {current}: stable update {update.tag} ({update.revision}) available", flush=True)
            result.update(target_version=update.version, revision=update.revision, status="update_available")
            result.update(apply_update(update, current, ROOT) if args.apply else {"success": True})
            if args.apply:
                result["status"] = "installed" if result["success"] else "failed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result.update(success=False, status="failed", error=str(exc))
    if report_path is not None:
        recovery = update_recovery_path(ROOT)
        if recovery.exists():
            result.setdefault("recovery_directory", str(recovery))
        try:
            write_install_report(report_path, result)
        except OSError as exc:
            result.update(success=False, status="failed", error=f"could not write update report: {exc}")
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    if result["success"] is not True:
        print(f"Local AI Hub update failed: {result.get('error', result.get('message'))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
