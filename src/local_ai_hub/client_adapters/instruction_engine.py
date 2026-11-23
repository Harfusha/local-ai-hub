"""InstructionEngine — atomic multi-file instruction management for AI clients."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from .base import InstructionTarget
from .registry import ClientRegistry


class InstructionEngine:
    """Manages transactional injection and removal of Hub instructions in client configuration files."""

    def __init__(self, client_id: str | None = None, repo_root: str | Path | None = None):
        self.adapter = ClientRegistry.get(client_id)
        self.repo_root = Path(repo_root).resolve() if repo_root else None

    def target_paths(self) -> list[tuple[InstructionTarget, Path]]:
        """Return list of (target, absolute_path) pairs for the active adapter."""
        if not self.repo_root:
            return []
        results = []
        for target in self.adapter.capabilities.instruction_targets:
            if target in {InstructionTarget.SYSTEM_PROMPT, InstructionTarget.NONE}:
                continue
            results.append((target, self.repo_root / target.value))
        return results

    def inject(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Inject or update managed instructions in all supported client configuration files."""
        from local_ai_hub.repo_plan.host_adapters import inject_managed_instructions

        results: dict[str, Any] = {}
        for target, path in self.target_paths():
            instructions = self.adapter.get_instructions(target)
            try:
                existing = path.read_text(encoding="utf-8") if path.exists() else ""
                updated = inject_managed_instructions(existing, block=instructions)
                changed = updated != existing
                if not dry_run and changed:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(updated, encoding="utf-8")
                results[str(path)] = {"success": True, "changed": changed, "dry_run": dry_run}
            except (OSError, ValueError) as exc:
                results[str(path)] = {"success": False, "error": str(exc), "dry_run": dry_run}
        return results

    def remove(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Remove managed instructions from all target files, preserving user content."""
        from local_ai_hub.repo_plan.host_adapters import remove_managed_instructions

        results: dict[str, Any] = {}
        for target, path in self.target_paths():
            if not path.exists():
                continue
            try:
                existing = path.read_text(encoding="utf-8")
                updated = remove_managed_instructions(existing)
                changed = updated != existing
                if not dry_run and changed:
                    path.write_text(updated, encoding="utf-8")
                results[str(path)] = {"success": True, "changed": changed, "dry_run": dry_run}
            except (OSError, ValueError) as exc:
                results[str(path)] = {"success": False, "error": str(exc), "dry_run": dry_run}
        return results
