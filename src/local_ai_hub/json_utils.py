from __future__ import annotations

import json
from typing import Any


def dumps(value: Any, **kwargs: Any) -> str:
    """Serialize JSON compactly while preserving caller-specific options."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("separators", (",", ":"))
    return json.dumps(value, **kwargs)
