from local_ai_hub.repo_tools import RepositoryTools, _intent_path_adjustment


def test_search_prioritizes_distinct_terms_across_file_over_repetition(tmp_path):
    (tmp_path / "a_noise.py").write_text("# retry retry retry\n", encoding="utf-8")
    (tmp_path / "z_target.py").write_text("def retry():\n    # transaction\n    pass\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    result = tools.search(str(tmp_path), "retry transaction", exact_count=True)

    assert result["success"] is True
    assert result["results"][0]["path"] == "z_target.py"
    assert {item["path"] for item in result["results"]} == {"a_noise.py", "z_target.py"}


def test_identifier_search_prioritizes_definition_over_import(tmp_path):
    (tmp_path / "a_import.py").write_text("from z_definition import pagination_bounds_error\n", encoding="utf-8")
    (tmp_path / "z_definition.py").write_text("def pagination_bounds_error(value):\n    return None\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    result = tools.search(str(tmp_path), "pagination_bounds_error", exact_count=True)

    assert result["success"] is True
    assert [item["path"] for item in result["results"]] == ["z_definition.py", "a_import.py"]


def test_installation_intent_prefers_user_documentation_over_tests(tmp_path):
    docs = tmp_path / "docs"
    tests = tmp_path / "tests"
    docs.mkdir()
    tests.mkdir()
    (docs / "INSTALLATION.md").write_text(
        "# Local AI Hub installation\n\nInstall and run the Hub on Windows.\n"
        "Jak nainstalovat a spustit Local AI Hub ve Windows.\n",
        encoding="utf-8",
    )
    (docs / "INSTALL_PROMPT.md").write_text(
        "\n".join("How to install the local AI Hub on Windows" for _ in range(8)) + "\n",
        encoding="utf-8",
    )
    (tests / "test_installation.py").write_text(
        "\n".join(
            f'def test_install_local_ai_hub_windows_{index}(): '
            'assert "how to install the local AI hub on windows"; '
            'assert "jak nainstalovat a spustit local ai hub ve windows"'
            for index in range(8)
        ) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "install.ps1").write_text(
        "\n".join("# How to install the local AI Hub on Windows" for _ in range(8)) + "\n",
        encoding="utf-8",
    )
    tools = RepositoryTools({"rag": {"extensions": [".md", ".py"]}})

    for query in (
        "How to install the local AI Hub on Windows",
        "How do I set up the local AI Hub on Windows without running Ollama?",
        "Which guide explains installing the local AI Hub on Windows?",
        "Jak nainstalovat a spustit Local AI Hub ve Windows",
    ):
        for exact_count in (False, True):
            result = tools.search(
                str(tmp_path), query, exact_count=exact_count,
                path_priority=lambda relative: (
                    1, 0 if relative.startswith(("tests/", "install.ps1")) else 1, 1,
                ),
            )

            assert result["success"] is True
            assert result["results"][0]["path"] == "docs/INSTALLATION.md"


def test_installation_intent_boost_targets_docs_not_install_scripts():
    query = "How to install the local AI Hub on Windows"

    assert _intent_path_adjustment(query, "docs/INSTALLATION.md") > 0
    assert _intent_path_adjustment(
        "Which guide explains installing the local AI Hub on Windows?",
        "docs/INSTALLATION.md",
    ) > 0
    assert _intent_path_adjustment(
        "How do I set up the local AI Hub on Windows without running Ollama?",
        "docs/INSTALLATION.md",
    ) > 0
    assert _intent_path_adjustment(query, "install.ps1") == 0
    assert _intent_path_adjustment(query, "docs/CONFIGURATION.md") == 0
    assert _intent_path_adjustment("How to configure the Hub", "docs/CONFIGURATION.md") > 0
    assert _intent_path_adjustment("INSTALL Local AI Hub", "docs/INSTALLATION.md") > 0
