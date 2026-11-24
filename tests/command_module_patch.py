"""Patch the implementation module that owns a split command symbol."""
from __future__ import annotations

import importlib


_IMPLEMENTATION_MODULES = (
    "command_jobs", "command_rollback", "command_rollback_windows",
    "command_daemon_process", "command_daemon_registry", "command_daemon_lifecycle",
    "command_run", "command_patch", "command_repair", "command_execute",
    "command_transaction_journal", "command_transaction_execute",
    "command_verification", "command_authorization", "command_classification",
    "command_cache", "command_diagnostics", "command_output",
)


def patch_split_command_module(patcher, name: str, value, **kwargs) -> None:
    """Patch split implementation bindings by their current module ownership."""
    importlib.import_module("local_ai_hub.command_broker")
    modules = [
        importlib.import_module(f"local_ai_hub.{module_name}")
        for module_name in _IMPLEMENTATION_MODULES
    ]
    patched = False
    for module in modules:
        if hasattr(module, name):
            patcher.setattr(module, name, value, **kwargs)
            patched = True
        if name.startswith("_") and hasattr(module, name[1:]):
            patcher.setattr(module, name[1:], value, **kwargs)
            patched = True
        elif not name.startswith("_") and hasattr(module, "_" + name):
            patcher.setattr(module, "_" + name, value, **kwargs)
            patched = True
    if not patched:
        raise AttributeError(f"no command implementation owns {name!r}")
