"""Synchronize canonical repository prompts with generated Hub policies."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import setup as setup_tools  # noqa: E402


CANONICAL_PROMPT_PATHS = (
    ROOT / "AGENTS.md",
    ROOT / "docs" / "INSTALL_PROMPT.md",
    ROOT / "docs" / "UPDATE_PROMPT.md",
)


def expected_prompt_policies() -> tuple[tuple[str, str, str], ...]:
    return (
        (setup_tools.GLOBAL_POLICY_BEGIN, setup_tools.GLOBAL_POLICY_END, setup_tools.GLOBAL_POLICY),
        (
            setup_tools.TOKEN_ECONOMY_POLICY_BEGIN,
            setup_tools.TOKEN_ECONOMY_POLICY_END,
            setup_tools.generate_token_economy_policy(setup_tools._DEFAULT_POLICY_CFG),
        ),
    )


def check_prompt_policies(paths: tuple[Path, ...] | None = None) -> tuple[bool, list[Path]]:
    """Check whether canonical prompt files contain current generated policies."""
    target_paths = CANONICAL_PROMPT_PATHS if paths is None else tuple(paths)
    expected = expected_prompt_policies()
    stale: list[Path] = []
    for path in target_paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            stale.append(Path(path))
            continue
        for begin, end, policy in expected:
            matches = list(re.finditer(re.escape(begin) + r".*?" + re.escape(end), text, re.DOTALL))
            if len(matches) != 1 or matches[0].group(0) != policy:
                stale.append(Path(path))
                break
    return (len(stale) == 0, stale)


def main() -> int:
    """Refresh or check managed policy blocks in canonical prompt files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any canonical policy block is stale")
    args = parser.parse_args()

    if args.check:
        ok, stale = check_prompt_policies()
        if not ok:
            for path in stale:
                print(f"stale: {path}")
            return 1
        print("canonical tool and token policy blocks match generated sources")
        return 0

    for path in CANONICAL_PROMPT_PATHS:
        setup_tools.merge_global_policy(path, backup_enabled=False)
        setup_tools.merge_token_economy_policy(path, backup_enabled=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
