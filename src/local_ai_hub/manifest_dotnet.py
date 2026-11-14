from __future__ import annotations

import json


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_dotnet_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse NuGet lock dependencies and the pinned .NET SDK version."""
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if name == "packages.lock.json":
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            dependencies = data.get("dependencies", {})
            if isinstance(dependencies, dict):
                for framework, items in dependencies.items():
                    if not isinstance(items, dict):
                        continue
                    for package, meta in items.items():
                        version = str(meta.get("resolved") or meta.get("requested") or "") if isinstance(meta, dict) else ""
                        deps.append((str(package), version, f"nuget-lock:{framework}"))
        return deps, scripts

    if name == "global.json":
        data = json.loads(raw.decode("utf-8", errors="replace"))
        sdk = data.get("sdk", {}) if isinstance(data, dict) else {}
        if isinstance(sdk, dict) and sdk.get("version"):
            deps.append(("dotnet-sdk", str(sdk.get("version")), "toolchain"))
        return deps, scripts

    return None
