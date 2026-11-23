"""Unit tests for Import Path Canonicalizer."""

from local_ai_hub.import_path_optimizer import canonicalize_imports, resolve_relative_module


def test_resolve_relative_module() -> None:
    # In src/local_ai_hub/storage/engine.py
    # from ..core import config (level=2) -> local_ai_hub.core.config
    res = resolve_relative_module("src/local_ai_hub/storage/engine.py", "config", level=2)
    assert res == "local_ai_hub.config"

    # from .utils import helper (level=1) -> local_ai_hub.storage.utils
    res_sibling = resolve_relative_module("src/local_ai_hub/storage/engine.py", "utils", level=1)
    assert res_sibling == "local_ai_hub.storage.utils"


def test_canonicalize_imports_ast() -> None:
    code = """from ..core import settings
from .helpers import validate_payload
import os

def run():
    return settings.DEBUG
"""
    res = canonicalize_imports(code, current_file_path="src/local_ai_hub/api/views.py")
    assert res.resolved_count == 2
    assert "from local_ai_hub.settings import settings" in res.optimized_code or "from local_ai_hub.core import settings" in res.optimized_code
    assert "from local_ai_hub.api.helpers import validate_payload" in res.optimized_code
    assert "from ." not in res.optimized_code
    assert "from .." not in res.optimized_code
