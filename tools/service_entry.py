from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def resolve_service_config(
    argv: list[str] | None = None,
    root: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    """Resolve configuration file path from argv or environment/root fallback."""
    args = sys.argv if argv is None else argv
    base_root = ROOT if root is None else root

    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 < len(args):
            raw_path = args[idx + 1]
            if "\0" not in raw_path:
                try:
                    candidate = Path(raw_path).resolve()
                    if candidate.is_file():
                        return candidate
                except (ValueError, OSError):
                    pass
        return None

    env_map = os.environ if env is None else env
    env_config = env_map.get("LOCAL_AI_CONFIG")
    if env_config and "\0" not in env_config:
        try:
            candidate = Path(env_config).resolve()
            if candidate.is_file():
                return candidate
        except (ValueError, OSError):
            pass

    try:
        root_config = (base_root / "config.toml").resolve()
        if root_config.is_file():
            return root_config
    except (ValueError, OSError):
        pass

    return None


def main(argv: list[str] | None = None) -> int:
    resolved = resolve_service_config(argv)
    if resolved is not None:
        os.environ["LOCAL_AI_CONFIG"] = str(resolved)
    os.chdir(str(ROOT))
    from local_ai_hub.supervisor import main as supervisor_main

    return int(supervisor_main())


if __name__ == "__main__":
    raise SystemExit(main())
