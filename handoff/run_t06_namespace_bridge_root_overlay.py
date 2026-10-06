from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
T06 = Path(r"C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub")
T16 = Path(r"C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub")
PATCH = T06 / "handoff" / "T06-namespace-bridge-v2-root-current.patch"
PREIMAGE_SHA256 = "11887A31E422891DF1B29C7300AAC49B3FB57047343024ADE9493531B3AA2D0B"
POSTIMAGE_SHA256 = "39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E"
PATCH_SHA256 = "9DD78F09779131762CE581F862E2B6C6DAB83D1B44DAB5A913DFAFC6A457ED6C"
PINNED_MODULES = {
    "leases.py": "362F4A0345977B16D04D92B5AFD37C82DEB2DC24DF43F7AB057D3AC3F0E3E694",
    "work_fencing.py": "4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050",
    "work_orchestrator.py": "CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337",
    "http_server.py": "6BA4B79AD0A7D06C11151E07E7261AFD9CAD515C1EF8FBA5A0DB0A34CEAA40CA",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    command_source = ROOT / "src" / "local_ai_hub" / "commands.py"
    command_hash = sha256(command_source)
    if command_hash not in {PREIMAGE_SHA256, POSTIMAGE_SHA256}:
        raise SystemExit("root commands.py matches neither pinned bridge preimage nor postimage")
    if sha256(PATCH) != PATCH_SHA256:
        raise SystemExit("T06 namespace patch hash mismatch")

    module_sources = {
        "leases.py": ROOT / "src" / "local_ai_hub" / "leases.py",
        "work_fencing.py": ROOT / "src" / "local_ai_hub" / "work_fencing.py",
        "work_orchestrator.py": ROOT / "src" / "local_ai_hub" / "work_orchestrator.py",
        "http_server.py": ROOT / "src" / "local_ai_hub" / "http_server.py",
    }
    for name, path in module_sources.items():
        if sha256(path) != PINNED_MODULES[name]:
            raise SystemExit(f"current T16 source fingerprint changed: {name}")
        print(f"source[{name}]={path} sha256={PINNED_MODULES[name]}")

    with tempfile.TemporaryDirectory(prefix="t06-root-namespace-bridge-") as temp:
        work = Path(temp)
        package = work / "src" / "local_ai_hub"
        shutil.copytree(
            ROOT / "src" / "local_ai_hub",
            package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        subprocess.run(["git", "init", "--quiet", str(work)], check=True)
        if command_hash == PREIMAGE_SHA256:
            checked = subprocess.run(
                ["git", "apply", "--check", "--whitespace=nowarn", str(PATCH)],
                cwd=work,
                capture_output=True,
                text=True,
            )
            if checked.returncode:
                raise SystemExit(checked.stderr[:1200])
            subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(PATCH)],
                cwd=work,
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            print("bridge_patch_already_present_in_pinned_root_postimage=true")

        tests = work / "tests"
        tests.mkdir()
        test_file = tests / "test_t06_project_namespace_bridge.py"
        shutil.copy2(T06 / "tests" / test_file.name, test_file)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(work / "src")
        print(f"broker_source={package / 'commands.py'}")
        print(f"http_source={package / 'http_server.py'}")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                str(test_file),
            ],
            cwd=work,
            env=env,
            check=False,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
