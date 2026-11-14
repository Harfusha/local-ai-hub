from __future__ import annotations

import re


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_text_lock_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse Yarn selectors and Ruby lockfile spec rows."""
    normalized_name = name.lower()
    if normalized_name not in {"yarn.lock", "gemfile.lock"}:
        return None

    text = raw.decode("utf-8", errors="replace")
    dependencies: list[tuple[str, str, str]] = []
    if normalized_name == "yarn.lock":
        current: list[str] = []
        for line in text.splitlines():
            if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
                current = [item.strip().strip("\"'") for item in line[:-1].split(",")]
            elif current and line.strip().startswith("version "):
                version = line.strip()[len("version "):].strip().strip("\"'")
                for spec in current[:8]:
                    package = spec
                    if spec.startswith("@"):
                        slash = spec.find("/")
                        at = spec.find("@", slash + 1) if slash >= 0 else -1
                        if at > 0:
                            package = spec[:at]
                    elif "@" in spec:
                        package = spec.split("@", 1)[0]
                    if package:
                        dependencies.append((package, version, "lock"))
                current = []
    else:
        in_specs = False
        for line in text.splitlines():
            if line.strip() == "specs:":
                in_specs = True
                continue
            if in_specs and line and not line.startswith(" "):
                in_specs = False
            if in_specs:
                match = re.match(r"^\s{4}([^\s(]+)\s+\(([^)]+)\)", line)
                if match:
                    dependencies.append((match.group(1), match.group(2), "lock"))
    return dependencies, []
