from __future__ import annotations

import importlib.resources
from pathlib import Path

_STATIC_PATH = Path(__file__).resolve().parent / "ui_static" / "dashboard.html"


def _read_dashboard_template() -> str:
    if _STATIC_PATH.is_file():
        return _STATIC_PATH.read_text(encoding="utf-8")
    try:
        return (
            importlib.resources.files("local_ai_hub")
            .joinpath("ui_static/dashboard.html")
            .read_text(encoding="utf-8")
        )
    except Exception:
        return ""


DASHBOARD_HTML_TEMPLATE: str = _read_dashboard_template()

__all__ = ["DASHBOARD_HTML_TEMPLATE"]
