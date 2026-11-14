from __future__ import annotations

import tomllib


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]


def parse_gradle_catalog_manifest(name: str, raw: bytes) -> ManifestRows | None:
    """Parse library aliases from a Gradle version catalog."""
    if name.lower() not in {"libs.versions.toml", "gradle/libs.versions.toml"}:
        return None

    data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    versions = data.get("versions", {}) if isinstance(data, dict) else {}
    libraries = data.get("libraries", {}) if isinstance(data, dict) else {}
    dependencies: list[tuple[str, str, str]] = []
    if isinstance(libraries, dict):
        for alias, metadata in libraries.items():
            if isinstance(metadata, str):
                dependencies.append((str(alias), metadata, "gradle-catalog"))
                continue
            if not isinstance(metadata, dict):
                continue
            module = str(metadata.get("module") or "")
            if not module and metadata.get("group") and metadata.get("name"):
                module = f"{metadata['group']}:{metadata['name']}"
            version = str(metadata.get("version") or "")
            version_data = metadata.get("version")
            reference = version_data.get("ref") if isinstance(version_data, dict) else metadata.get("version.ref")
            if reference and isinstance(versions, dict):
                version = str(versions.get(str(reference), reference))
            if module:
                dependencies.append((module, version, "gradle-catalog"))
    return dependencies, []
