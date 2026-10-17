"""Deferred static scan contracts; fixtures contain invented credentials only."""
from types import SimpleNamespace

from local_ai_hub.deterministic import DeterministicEngine


def _scan(root, paths, limit=50):
    engine = SimpleNamespace(
        _root=lambda value: str(root),
        repo_tools=SimpleNamespace(iter_files=lambda value: iter(paths), max_file_bytes=2_000_000),
    )
    return DeterministicEngine.security_audit(engine, str(root), limit=limit)


def test_credential_like_test_value_is_not_automatically_safe(tmp_path):
    source = tmp_path / "tests" / "test_fixture.py"
    source.parent.mkdir()
    source.write_text('api_key = "invented_untrusted_value_f72Xa91"\n', encoding="utf-8")
    result = _scan(tmp_path, [source])
    assert result["is_clean"] is False
    assert result["release_blocking_findings"] == 1
    assert result["triage_complete"] is False
    assert result["findings"][0]["is_test"] is True
    assert result["findings"][0]["classification"] == "untriaged"
    assert "invented_untrusted_value" not in result["findings"][0]["snippet"]


def test_medium_finding_remains_visible_without_clean_verdict(tmp_path):
    source = tmp_path / "unsafe.py"
    source.write_text("pickle.loads(payload)\n", encoding="utf-8")
    result = _scan(tmp_path, [source])
    assert result["medium_severity_count"] == 1
    assert result["findings_present"] is True
    assert result["release_blocking_findings"] == 0
    assert result["is_clean"] is False
    assert result["scan_complete"] is True


def test_findings_limit_is_incomplete_even_if_later_production_file_unseen(tmp_path):
    first = tmp_path / "test_many.py"
    later = tmp_path / "production.py"
    first.write_text('password = "invented_first_value"\n', encoding="utf-8")
    later.write_text('password = "invented_later_value"\n', encoding="utf-8")
    result = _scan(tmp_path, [first, later], limit=1)
    assert result["limit_reached"] is True
    assert result["scan_complete"] is False
    assert result["is_clean"] is False
    assert result["scanned_files"] == 1
    assert result["eligible_files_total"] is None


def test_unreadable_source_prevents_clean_verdict(tmp_path):
    result = _scan(tmp_path, [tmp_path / "missing.py"])
    assert result["scan_complete"] is False
    assert result["is_clean"] is False
    assert result["skipped_files"] == 1
    assert result["scan_errors"][0]["error_type"] == "FileNotFoundError"
    assert "error" in result["scan_errors"][0]
    assert len(result["scan_errors"][0]["error"]) > 0


def test_shell_injection_finding_belongs_to_call_with_shell_enabled(tmp_path):
    source = tmp_path / "unsafe.py"
    source.write_text(
        "import subprocess\n"
        "subprocess.run([\"git\", \"status\"], check=True)\n"
        "subprocess.run(\n"
        "    command,\n"
        "    shell=True,\n"
        ")\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (3, "MEDIUM"),
    ]


def test_shell_injection_finding_supports_subprocess_import_aliases(tmp_path):
    source = tmp_path / "unsafe_alias.py"
    source.write_text(
        "import subprocess as process\n"
        "from subprocess import run as execute\n"
        "process.run(command, shell=True)\n"
        "execute(command, shell=True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (3, "MEDIUM"),
        (4, "MEDIUM"),
    ]


def test_shell_injection_finding_detects_literal_expanded_shell_keyword(tmp_path):
    source = tmp_path / "unsafe_expanded_keyword.py"
    source.write_text(
        "import subprocess\n"
        "subprocess.run(command, **{\"shell\": True})\n"
        "subprocess.run(command, **{\"shell\": False})\n"
        "subprocess.run(command, **{\"shell\": True, \"shell\": False})\n"
        "subprocess.run(command, **{\"shell\": True, **{\"shell\": False}})\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (2, "MEDIUM"),
    ]


def test_shell_injection_finding_detects_positional_popen_shell_argument(tmp_path):
    source = tmp_path / "unsafe_positional.py"
    source.write_text(
        "import subprocess\n"
        "from subprocess import Popen as spawn\n"
        "subprocess.Popen(command, -1, None, None, None, None, None, True, True)\n"
        "spawn(command, -1, None, None, None, None, None, True, True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (3, "MEDIUM"),
        (4, "MEDIUM"),
    ]


def test_shell_injection_finding_ignores_shadowed_subprocess_name(tmp_path):
    source = tmp_path / "shadowed.py"
    source.write_text(
        "def run_with_local_object(subprocess):\n"
        "    subprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    assert not any(
        finding["title"] == "Shell Injection Risk" for finding in result["findings"]
    )


def test_shell_injection_finding_ignores_function_shadowing_import(tmp_path):
    source = tmp_path / "function_shadow.py"
    source.write_text(
        "import subprocess\n"
        "def subprocess():\n"
        "    return None\n"
        "subprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    assert not any(
        finding["title"] == "Shell Injection Risk" for finding in result["findings"]
    )


def test_shell_injection_finding_skips_class_scope_when_resolving_method_name(tmp_path):
    source = tmp_path / "class_scope.py"
    source.write_text(
        "import subprocess\n"
        "class Runner:\n"
        "    subprocess = object()\n"
        "    def run(self):\n"
        "        subprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (5, "MEDIUM"),
    ]


def test_shell_injection_finding_supports_dotted_subprocess_import(tmp_path):
    source = tmp_path / "unsafe_dotted_import.py"
    source.write_text(
        "import subprocess.tools\n"
        "subprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )

    result = _scan(tmp_path, [source])

    shell_findings = [
        finding for finding in result["findings"]
        if finding["title"] == "Shell Injection Risk"
    ]
    assert [(finding["line"], finding["severity"]) for finding in shell_findings] == [
        (2, "MEDIUM"),
    ]

