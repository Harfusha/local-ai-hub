from __future__ import annotations

import xml.etree.ElementTree as ET


ManifestRows = tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]
_DOTNET_PROJECT_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}
_DOTNET_SHARED_MANIFESTS = {
    "directory.packages.props",
    "directory.build.props",
    "directory.build.targets",
}


def parse_xml_manifest(name: str, suffix: str, raw: bytes) -> ManifestRows | None:
    """Parse .NET project/shared manifests and Maven POM dependency rows."""
    deps: list[tuple[str, str, str]] = []
    scripts: list[tuple[str, str, str]] = []
    if suffix in _DOTNET_PROJECT_SUFFIXES or name in _DOTNET_SHARED_MANIFESTS:
        root = ET.fromstring(raw)
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag in {"PackageReference", "PackageVersion"}:
                package = node.attrib.get("Include") or node.attrib.get("Update") or ""
                version = node.attrib.get("Version") or next(
                    (child.text or "" for child in node if child.tag.split("}")[-1] == "Version"),
                    "",
                )
                if package:
                    deps.append((package, version, tag))
        return deps, scripts

    if name == "pom.xml":
        root = ET.fromstring(raw)
        for dependency in (node for node in root.iter() if node.tag.split("}")[-1] == "dependency"):
            values = {child.tag.split("}")[-1]: (child.text or "").strip() for child in dependency}
            artifact = values.get("artifactId", "")
            group = values.get("groupId", "")
            if artifact:
                deps.append((
                    f"{group}:{artifact}" if group else artifact,
                    values.get("version", ""),
                    values.get("scope", "compile"),
                ))
        return deps, scripts

    return None
