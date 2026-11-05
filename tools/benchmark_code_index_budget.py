"""Measure bounded code-index eviction on a temporary synthetic repository."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def run() -> dict[str, object]:
    with TemporaryDirectory(prefix="lah-code-index-budget-") as temp:
        base = Path(temp)
        root = base / "repo"
        root.mkdir()
        index = CodeIndex(
            {
                "server": {"state_dir": str(base / "state")},
                "code_index": {"max_index_bytes": 64 * 1024 * 1024},
            },
            RepositoryTools({}),
        )
        try:
            for number in range(16):
                path = f"module_{number}.py"
                source = "\n".join(
                    f"def item_{number}_{row}(): return {row}" for row in range(160)
                ) + "\n"
                (root / path).write_text(source, encoding="utf-8")
                index.update_file(str(root), path)
            index.record_usage(
                str(root), [{"path": "module_0.py", "uses": 100, "last_used_at": 100.0}]
            )
            before = index.measure_storage()
            limit = max(1, int(before["physical_bytes"] * 0.7))
            result = index.enforce_size_limit(max_bytes=limit, max_files=128)
            after = index.measure_storage()
            cold_root = base / "cold-repository"
            cold_root.mkdir()
            for number in range(6):
                path = f"cold_{number}.py"
                (cold_root / path).write_text("\n".join(
                    f"def cold_{number}_{row}(): return {row}" for row in range(160)
                ) + "\n", encoding="utf-8")
                index.update_file(str(cold_root), path)
            admission_before = index.measure_storage()
            admission_limit = admission_before["physical_bytes"] + 65535
            index.max_index_bytes = admission_limit
            (root / "admitted_after_eviction.py").write_text(
                "def admitted_after_eviction(): return True\n", encoding="utf-8"
            )
            admission = index.update_file(str(root), "admitted_after_eviction.py")
            admission_after = index.measure_storage()
            return {
                "kind": "synthetic_code_index_storage",
                "indexed_files_before": 16,
                "max_bytes": limit,
                "before_physical_bytes": before["physical_bytes"],
                "after_physical_bytes": after["physical_bytes"],
                "physical_bytes_released": max(
                    0, before["physical_bytes"] - after["physical_bytes"]
                ),
                "before_pages": before["page_count"],
                "after_pages": after["page_count"],
                "evicted_file_count": len(result.get("evicted_paths", [])),
                "retained_hot_file": (str(root), "module_0.py")
                not in result.get("evicted_paths", []),
                "within_budget": result.get("within_budget") is True,
                "write_admission": {
                    "budget_limited": admission.get("budget_limited") is True,
                    "success": admission.get("success") is True,
                    "estimated_growth_bytes": admission.get("budget", {}).get("estimated_growth_bytes"),
                    "evicted_file_count": len(
                        (admission.get("budget", {}).get("eviction") or {}).get("evicted_paths", [])
                    ),
                    "max_bytes": admission_limit,
                    "before_physical_bytes": admission_before["physical_bytes"],
                    "after_physical_bytes": admission_after["physical_bytes"],
                    "within_budget": admission_after["physical_bytes"] <= admission_limit,
                },
            }
        finally:
            index.close()


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
