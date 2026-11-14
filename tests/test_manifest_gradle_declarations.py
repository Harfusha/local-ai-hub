from __future__ import annotations

from local_ai_hub.manifest_gradle_declarations import parse_gradle_declarations_manifest


def test_declarations_preserve_configuration_coordinates_and_missing_versions():
    raw = b'''dependencies {
    implementation("org.example:core:1.2.3")
    api 'org.example:api:4.5'
    runtimeOnly("org.example:runtime")
    testImplementation("org.example:test:2.0:classifier")
    // implementation("org.example:ignored:9.9")
}
'''

    assert parse_gradle_declarations_manifest("build.gradle", raw) == (
        [
            ("org.example:core", "1.2.3", "implementation"),
            ("org.example:api", "4.5", "api"),
            ("org.example:runtime", "", "runtimeOnly"),
            ("org.example:test", "2.0", "testImplementation"),
        ],
        [],
    )


def test_declarations_accept_kts_and_ignore_other_files():
    raw = b'''dependencies {
    compileOnly("org.example:compile:7")
}'''
    expected = ([ ("org.example:compile", "7", "compileOnly") ], [])

    assert parse_gradle_declarations_manifest("build.gradle.kts", raw) == expected
    assert parse_gradle_declarations_manifest("settings.gradle", raw) is None
