from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
TEST = Path(__file__).with_name("T21_root_current_verification_rules_annotation_test.py")
ANCHOR = "from .agent_verification import CompletionResult"
IMPORT = "from .project_config import ProjectSettings"


with tempfile.TemporaryDirectory(prefix="t21-verification-overlay-") as temporary:
    overlay = Path(temporary)
    source = overlay / "src"
    shutil.copytree(ROOT / "src/local_ai_hub", source / "local_ai_hub")
    shutil.copy2(ROOT / "pyproject.toml", overlay / "pyproject.toml")
    tests = overlay / "tests"
    tests.mkdir()
    test_path = tests / "test_t21_verification_rules_settings_type.py"
    shutil.copy2(TEST, test_path)

    module = source / "local_ai_hub/verification_rules.py"
    content = module.read_text(encoding="utf-8")
    if content.count(ANCHOR) != 1 or content.count(IMPORT) > 1:
        raise SystemExit("root-current verification_rules import anchor changed")
    if IMPORT not in content:
        content = content.replace(ANCHOR, ANCHOR + "\n" + IMPORT)
        module.write_text(content, encoding="utf-8")

    pyflakes = subprocess.run(
        [sys.executable, "-m", "pyflakes", str(module)],
        text=True,
        capture_output=True,
        check=False,
    )
    print("pyflakes:", pyflakes.stdout.strip() or "clean")
    if pyflakes.returncode != 0:
        print(pyflakes.stderr, file=sys.stderr)
        raise SystemExit(pyflakes.returncode)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source)
    pytest = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short",
         "-c", str(overlay / "pyproject.toml"), str(test_path)],
        cwd=overlay,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    print(pytest.stdout.strip())
    if pytest.returncode != 0:
        print(pytest.stderr, file=sys.stderr)
        raise SystemExit(pytest.returncode)
