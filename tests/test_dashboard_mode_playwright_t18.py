from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT_SOURCE = os.environ.get("T18_ROOT_SOURCE", "")
if _ROOT_SOURCE:
    sys.path.insert(0, str(Path(_ROOT_SOURCE).resolve()))

from local_ai_hub import dashboard, http_server
from local_ai_hub.dashboard import DASHBOARD_HTML


def _playwright_runtime() -> tuple[Path, Path, Path]:
    runtime = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node"
    node = runtime / "bin" / ("node.exe" if os.name == "nt" else "node")
    if not node.is_file():
        discovered = shutil.which("node")
        if not discovered:
            pytest.skip("bundled Node.js is unavailable")
        node = Path(discovered)

    package = runtime / "node_modules" / "playwright"
    override_package = os.environ.get("T18_PLAYWRIGHT_PACKAGE")
    if override_package:
        package = Path(override_package)
    if not package.exists():
        pytest.skip("bundled Playwright package is unavailable")

    cache = Path.home() / "AppData" / "Local" / "ms-playwright" if os.name == "nt" else Path.home() / ".cache" / "ms-playwright"
    candidates = sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
    candidates += sorted(cache.glob("chromium_headless_shell-*/chrome-win/headless_shell.exe"))
    if not candidates:
        pytest.skip("a preinstalled Playwright headless Chromium is unavailable")
    return node, package, candidates[-1]


def test_dashboard_mode_dom_auth_and_error_projection(tmp_path: Path) -> None:
    if not _ROOT_SOURCE:
        pytest.skip("set T18_ROOT_SOURCE to pin the current root source")
    root_package = Path(_ROOT_SOURCE).resolve() / "local_ai_hub"
    for module, filename, env_key in (
        (http_server, "http_server.py", "T18_ROOT_HTTP_SERVER_SHA256"),
        (dashboard, "dashboard.py", "T18_ROOT_DASHBOARD_SHA256"),
    ):
        source_path = root_package / filename
        expected_sha = os.environ.get(env_key, "").upper()
        assert Path(module.__file__).resolve() == source_path
        assert len(expected_sha) == 64
        assert hashlib.sha256(source_path.read_bytes()).hexdigest().upper() == expected_sha
    node, playwright_package, chromium = _playwright_runtime()
    html_path = tmp_path / "dashboard.html"
    html_path.write_text(DASHBOARD_HTML, encoding="utf-8")
    runner = Path(__file__).parent / "fixtures" / "dashboard_mode_playwright_t18.cjs"

    env = os.environ.copy()
    env["T18_PLAYWRIGHT_PACKAGE"] = str(playwright_package)
    env["T18_CHROMIUM_EXECUTABLE"] = str(chromium)
    result = subprocess.run(
        [str(node), str(runner), str(html_path)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
        env=env,
    )
    assert result.returncode == 0, f"Playwright fixture failed:\n{result.stdout}\n{result.stderr}"
    receipt = json.loads(result.stdout.strip().splitlines()[-1])

    assert receipt["initialMode"] == "active"
    assert receipt["initialModeGetToken"] is None
    assert receipt["overviewHealth"] == "Degraded"
    assert receipt["statusPill"] == {"text": "degraded", "warning": True}
    assert receipt["partialMode"] == "gaming"
    assert receipt["partialBadgeText"] == "Mode: GAMING / PAUSED"
    assert receipt["partialToken"] is None
    assert receipt["partialClient"] == "dashboard"
    assert "Mode persisted as GAMING / PAUSED." in receipt["partialStatus"]
    assert "VRAM unload pending" in receipt["partialStatus"]
    assert "accelerator release incomplete" in receipt["partialStatus"]
    assert "job cancellation incomplete" in receipt["partialStatus"]
    assert receipt["pressedMode"] == "gaming"
    assert receipt["buttonsEnabledAfterPartial"] is True
    assert "VRAM unload complete" in receipt["completedStatus"]
    assert receipt["unauthorizedStatus"] == "Unauthorized (HTTP 401); check the API token."
    assert receipt["modeAfterUnauthorized"] == "gaming"
    assert receipt["unauthorizedToken"] is None
    assert receipt["buttonsEnabledAfterUnauthorized"] is True
    assert receipt["serverErrorStatus"] == "Mode request failed (HTTP 503)."
    assert receipt["modeAfterServerError"] == "gaming"
    assert receipt["serverErrorToken"] is None
    assert receipt["buttonsEnabledAfterServerError"] is True
