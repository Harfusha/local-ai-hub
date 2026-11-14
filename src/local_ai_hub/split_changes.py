from __future__ import annotations

from typing import Any


def run_split_changes(
    engine: Any,
    root: str,
    changed_files: list[str] | None,
    *,
    path_type: Any,
    subprocess_module: Any,
    hidden_run_kwargs_fn: Any,
) -> dict[str, Any]:
    resolved_root = path_type(engine._root(root))
    files = list(changed_files or [])
    if not files:
        try:
            cp = subprocess_module.run(
                ["git", "status", "--porcelain"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=engine.git_status_timeout,
                **hidden_run_kwargs_fn(),
            )
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        files.append(parts[1].replace("\\", "/"))
        except Exception:
            pass

    if not files:
        return {"success": True, "clusters": [], "total_files": 0, "message": "No changed files detected"}

    categories: dict[str, list[str]] = {
        "docs": [],
        "config": [],
        "core": [],
        "api_or_services": [],
        "models_or_schemas": [],
        "tests": [],
        "other": [],
    }

    for f in files:
        norm = f.lower().replace("\\", "/")
        if norm.startswith("docs/") or norm.endswith((".md", ".rst", ".txt")):
            categories["docs"].append(f)
        elif norm.endswith((".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock")) or "config" in norm:
            categories["config"].append(f)
        elif "test" in norm or norm.startswith("tests/"):
            categories["tests"].append(f)
        elif any(k in norm for k in ("model", "schema", "entity", "dto")):
            categories["models_or_schemas"].append(f)
        elif any(k in norm for k in ("api", "service", "route", "controller", "endpoint")):
            categories["api_or_services"].append(f)
        elif any(k in norm for k in ("core", "engine", "util", "helper", "lib")):
            categories["core"].append(f)
        else:
            categories["other"].append(f)

    clusters = []
    cluster_id = 1
    order = ["models_or_schemas", "core", "api_or_services", "tests", "config", "docs", "other"]
    for cat in order:
        cat_files = categories[cat]
        if cat_files:
            clusters.append({
                "cluster_id": cluster_id,
                "name": cat.replace("_", " ").title(),
                "category": cat,
                "suggested_commit_message": f"feat({cat}): update {cat.replace('_', ' ')} components",
                "files": sorted(cat_files),
            })
            cluster_id += 1

    return {
        "success": True,
        "root": str(resolved_root),
        "total_files": len(files),
        "cluster_count": len(clusters),
        "clusters": clusters,
    }

