from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(__file__).resolve().parents[1]
PATCH = CANDIDATE / "handoff" / "t15-root-current-cache-only-v2.patch"
EXPECTED = {
    "src/local_ai_hub/commands.py": "1b27f83872d439b9167c9b2323bf4be71279e688df6094c002ca20934f761b67",
    "tests/test_project_command_broker.py": "169f086607ccd725c6514b15bc6a54baf66e9f6c096395801b6f0beaa23b8728",
}
SELECTORS = [
    "tests/test_project_command_broker.py::test_project_command_config_cache_invalidates_negative_lookup",
    "tests/test_project_command_broker.py::test_project_command_config_cache_uses_file_signature_invalidation",
    "tests/test_project_command_broker.py::test_project_command_config_cache_invalidates_on_git_revision",
    "tests/test_project_command_broker.py::test_linked_worktree_config_cache_invalidates_all_config_layers",
    "tests/test_project_command_broker.py::test_project_command_environment_values_change_cache_context",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(root: Path) -> dict[str, str]:
    return {name: _sha256(root / name) for name in EXPECTED}


def main() -> int:
    before = _source_hashes(ROOT)
    if before != EXPECTED:
        raise SystemExit(f"root preimage mismatch: {before}")

    with tempfile.TemporaryDirectory(prefix="t15-root-cache-v2-") as temp:
        fixture = Path(temp)
        (fixture / "src").mkdir()
        (fixture / "tests").mkdir()
        shutil.copytree(ROOT / "src" / "local_ai_hub", fixture / "src" / "local_ai_hub")
        shutil.copy2(
            ROOT / "tests" / "test_project_command_broker.py",
            fixture / "tests" / "test_project_command_broker.py",
        )
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=fixture, check=True)
        subprocess.run(["git", "apply", str(PATCH)], cwd=fixture, check=True)

        env = dict(os.environ)
        env["PYTHONPATH"] = str(fixture / "src")
        command = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            *SELECTORS,
        ]
        started = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=fixture,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        elapsed = time.perf_counter() - started
        print(result.stdout, end="")
        print(f"ISOLATED_PATCH_TEST_EXIT={result.returncode}")
        print(f"ISOLATED_PATCH_TEST_ELAPSED_SECONDS={elapsed:.2f}")
        if result.returncode:
            return result.returncode

    after = _source_hashes(ROOT)
    if after != before:
        raise SystemExit(f"root changed during isolated test: before={before}, after={after}")
    print(f"ROOT_PREIMAGES_BEFORE_AFTER_MATCH={before}")
    print("ROOT_WORKSPACE_TESTS=NOT_RUN; isolated patched source copy only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
