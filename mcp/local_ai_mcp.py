"""Compatibility entrypoint for pre-1.5 Local AI Hub MCP installations.

The package-native server is the source of truth. New configurations launch
``python -m local_ai_hub.mcp_server``; this wrapper keeps older user configs
working while they are migrated.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.mcp_server import mcp  # noqa: E402


if __name__ == "__main__":
    mcp.run()
