from __future__ import annotations


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_go_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse Go module requirements and workspace modules."""
    if name not in {"go.mod", "go.work"}:
        return None

    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    text = raw.decode("utf-8", errors="replace")
    if name == "go.mod":
        in_require = False
        for line in text.splitlines():
            item = line.strip()
            if item.startswith("require ("):
                in_require = True
                continue
            if in_require and item == ")":
                in_require = False
                continue
            if item.startswith("require "):
                item = item[len("require "):].strip()
            elif not in_require:
                continue
            parts = item.split()
            if len(parts) >= 2:
                deps.append((parts[0], parts[1], "require"))
    else:
        in_use = False
        for line in text.splitlines():
            item = line.strip()
            if item.startswith("use ("):
                in_use = True
                continue
            if in_use and item == ")":
                in_use = False
                continue
            if item.startswith("use "):
                item = item[4:].strip()
            elif not in_use:
                continue
            if item and not item.startswith("//"):
                deps.append((item, "", "workspace-module"))
    return deps, scripts


def parse_go_sum_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse Go checksums while excluding go.mod-only rows."""
    if name.lower() != "go.sum":
        return None

    dependencies: list[tuple[str, str, str]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[1].endswith("/go.mod"):
            dependencies.append((parts[0], parts[1], "sum"))
    return dependencies, []
