from __future__ import annotations

from local_ai_hub.manifest_dispatch import parse_manifest_dispatch


def test_dispatch_routes_gradle_declarations_and_rejects_unknown_names():
    assert parse_manifest_dispatch(
        "build.gradle",
        ".gradle",
        b'dependencies {\n    implementation("org.example:core:1.2.3")\n}',
        "default",
    ) == ([ ("org.example:core", "1.2.3", "implementation") ], [])
    assert parse_manifest_dispatch("unknown.lock", ".lock", b"", "default") == ([], [])


def test_dispatch_routes_xml_project_by_filename_and_suffix():
    raw = b'''<Project><ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.1" /></ItemGroup></Project>'''
    assert parse_manifest_dispatch("app.csproj", ".csproj", raw, "default") == (
        [("Newtonsoft.Json", "13.0.1", "PackageReference")],
        [],
    )
    assert parse_manifest_dispatch("directory.build.props", ".props", b"<Project />", "default") == ([], [])
