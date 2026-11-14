from __future__ import annotations

import json
import re


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]
_PNPM_LOCK_KEY = re.compile(
    r"^\s{2,}[\"']?/?((?:@[^/\s:]+/)?[^@:/\s\"']+)@([^:\s(\"']+)(?:\([^)]*\))?[\"']?\s*:\s*$"
)


def parse_npm_lock_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse npm package locks and pnpm lock keys without filesystem access."""
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if name == "package-lock.json":
        data = json.loads(raw.decode("utf-8", errors="replace"))
        packages = data.get("packages", {}) if isinstance(data, dict) else {}
        if isinstance(packages, dict) and packages:
            for key, meta in packages.items():
                if not key.startswith("node_modules/") or not isinstance(meta, dict):
                    continue
                package = key[len("node_modules/"):]
                if package:
                    deps.append((package, str(meta.get("version", "")), "lock"))
        elif isinstance(data, dict) and isinstance(data.get("dependencies"), dict):
            for package, meta in data["dependencies"].items():
                version = str(meta.get("version", "")) if isinstance(meta, dict) else ""
                deps.append((str(package), version, "lock"))
        return deps, scripts

    if name == "pnpm-lock.yaml":
        text = raw.decode("utf-8", errors="replace")
        # pnpm v6-v9 lock keys are deterministic enough to recover package + version
        # without a YAML dependency. We intentionally ignore peer suffix metadata.
        for line in text.splitlines():
            match = _PNPM_LOCK_KEY.match(line)
            if match:
                deps.append((match.group(1), match.group(2), "lock"))
        return deps, scripts

    return None
