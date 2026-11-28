from __future__ import annotations

from local_ai_hub.dashboard_contracts import (
    RESIDENT_INVENTORY_JS,
    WORKSPACE_INVENTORY_JS,
    memory_kind_options,
    memory_scope_options,
)
from local_ai_hub.dashboard_html import DASHBOARD_HTML_TEMPLATE

DASHBOARD_HTML: str = (
    DASHBOARD_HTML_TEMPLATE.replace("__MEMORY_SCOPE_OPTIONS__", memory_scope_options())
    .replace("__MEMORY_KIND_OPTIONS__", memory_kind_options())
    .replace("__MEMORY_CREATE_SCOPE_OPTIONS__", memory_scope_options(include_all=False, selected="task"))
    .replace("__MEMORY_CREATE_KIND_OPTIONS__", memory_kind_options(include_all=False, selected="fact"))
    .replace("<script>", "<script>\n" + RESIDENT_INVENTORY_JS + WORKSPACE_INVENTORY_JS, 1)
)

__all__ = ["DASHBOARD_HTML", "DASHBOARD_HTML_TEMPLATE"]
