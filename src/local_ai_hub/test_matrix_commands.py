"""Pure construction of per-file test commands for test-matrix rows."""

from __future__ import annotations

import re
from pathlib import Path


def build_test_file_command(test_file: Path, relative_path: str, framework: str) -> tuple[list[str], str]:
    """Return structured argv and a display form safe for simple shell tokens."""
    suffix = test_file.suffix.lower()
    if suffix == ".py" and framework == "pytest":
        argv = ["python", "-m", "pytest", "--", relative_path]
    elif suffix == ".cs" and framework == "dotnet":
        argv = ["dotnet", "test", "--filter", f"FullyQualifiedName~{test_file.stem}"]
    elif suffix in {".js", ".jsx", ".ts", ".tsx"} and framework == "npm":
        argv = ["npm", "test", "--", relative_path]
    elif suffix == ".go" and framework == "go":
        argv = ["go", "test", f"./{str(Path(relative_path).parent).replace(chr(92), '/')}"]
    elif suffix == ".rs" and framework == "cargo":
        argv = ["cargo", "test"]
    else:
        argv = []

    safe_tokens = all(re.fullmatch(r"[A-Za-z0-9_./\\:-]+", arg) for arg in argv)
    display = " ".join(argv) if safe_tokens else ""
    return argv, display
