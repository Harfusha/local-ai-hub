from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from local_ai_hub.manifest_xml import parse_xml_manifest


def test_dotnet_project_keeps_package_reference_attributes_and_child_version():
    raw = b'''<Project><ItemGroup><PackageReference Include="runtime" Version="1.2"/><PackageVersion Update="central"><Version>2.3</Version></PackageVersion></ItemGroup></Project>'''

    assert parse_xml_manifest("app.csproj", ".csproj", raw) == (
        [("runtime", "1.2", "PackageReference"), ("central", "2.3", "PackageVersion")],
        [],
    )


def test_maven_pom_uses_local_names_and_default_compile_scope():
    raw = b'''<project xmlns="urn:maven"><dependencies><dependency><groupId>org.example</groupId><artifactId>runtime</artifactId><version>1.2</version></dependency><dependency><artifactId>local</artifactId></dependency></dependencies></project>'''

    assert parse_xml_manifest("pom.xml", ".xml", raw) == (
        [("org.example:runtime", "1.2", "compile"), ("local", "", "compile")],
        [],
    )


def test_unsupported_manifest_names_are_not_handled():
    assert parse_xml_manifest("README.xml", ".xml", b"<root/>") is None


def test_malformed_xml_propagates_to_existing_error_boundary():
    with pytest.raises(ET.ParseError):
        parse_xml_manifest("pom.xml", ".xml", b"<project>")
