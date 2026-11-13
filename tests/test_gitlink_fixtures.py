from __future__ import annotations

import subprocess
from pathlib import Path


def test_tracked_gitlinks_require_a_submodule_manifest():
    result = subprocess.run(
        ["git", "ls-files", "--stage"],
        check=True,
        capture_output=True,
        text=True,
    )
    gitlinks = [line for line in result.stdout.splitlines() if line.startswith("160000 ")]

    assert not gitlinks or Path(".gitmodules").is_file(), (
        "tracked Git links require a corresponding .gitmodules manifest: "
        + ", ".join(line.split("\t", 1)[-1] for line in gitlinks)
    )
