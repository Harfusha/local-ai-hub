from pathlib import Path


def test_case132_full_run_preserves_gates_branches_and_action_arguments():
    text = (Path(__file__).resolve().parents[1] / "docs/agent-evaluation/prompts.md").read_text(encoding="utf-8")
    case = text.split("### 132 —", 1)[1].split("### 133 —", 1)[0]

    assert '`capabilities.code_generation.available=true`' in case
    assert "Pokud manifest výslovně neurčí `execution_scope=\"generation-only\"`, spusť celý CASE132" in case
    assert "`security_audit`, `dead_code`, `reachability_dead_code`, `complexity`, `api_spec`, `test_matrix`" in case
    assert "`generate_tests` volej jen při JSON boolean" in case
    assert "Gated nebo chybná větev neukončuje ostatní povolené větve" in case
    assert "Po prvním completed nebo failed call markeru" in case
    assert '"validate_patch":{"valid_patch":{},"invalid_patch":{}}' in case
    assert "Používej úplný live enum předaný harnesssem" in case
    assert "`route` vyžaduje `path`" in case
    assert "`investigate` a `diagnose` používají `query`, ne `task`" in case
    assert "`diff` je Git diff, ne patch vstup" in case
    assert "syntetický diff patří jen do `validate_patch.query`" in case
    assert "`framework` je výstupní kritérium, ne argument" in case
