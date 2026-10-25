"""App-owned automation lifetime; backend installation is always explicit."""
from pathlib import Path

from .automation import AutomationBroker


def create_automation_broker(config, artifacts):
    def persist(data, mime):
        identity = (artifacts.put_file_bytes(data, kind="automation-output") if mime == "application/octet-stream"
                    else artifacts.put_bytes(data, kind="automation-output", mime_type=mime))
        return {"artifact_id": identity, "mime_type": mime, "size_bytes": len(data)}

    def backend(mode, settings, request, policy):
        from .automation_adapters import BrowserMCPAdapter, WinAppAdapter
        state_dir = Path(config["server"]["state_dir"]) / "automation"
        state_dir.mkdir(parents=True, exist_ok=True)
        if state_dir.is_symlink():
            raise ValueError("automation state directory must not be a symlink")
        if mode in {"isolated", "extension"}:
            return BrowserMCPAdapter(mode, settings, request, policy, state_dir, persist_binary=persist)
        return WinAppAdapter(mode, settings, request, state_dir, persist_binary=persist)

    return AutomationBroker(config.get("automation", {}), backend_factory=backend)
