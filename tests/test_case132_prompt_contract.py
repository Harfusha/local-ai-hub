from pathlib import Path


def test_case132_full_run_preserves_gates_branches_and_final_schema():
    text = (Path(__file__).resolve().parents[1] / "docs/agent-evaluation/prompts.md").read_text(encoding="utf-8")
    case = text.split("### 132 —", 1)[1].split("### 133 —", 1)[0]

    assert '`capabilities.code_generation.available=true`' in case
    assert "Úplný manifest s oběma diffy znamená přesně dva cally" in case
    assert "Chybějící nebo neověřitelný diff označ `NOT_RUN/NOT_VERIFIED` bez náhrady" in case
    assert "MCP akci vůbec nevolej" in case
    assert "Používej živý action enum předaný harness, pokud je označený jako úplný" in case
    assert "Je-li enum neúplný nebo nezobrazený, nedovozuj `UNAVAILABLE`" in case
    assert "přesně předaná source-declared read-only větev s fixture-scoped argumenty" in case
    assert '"validate_patch":{"valid_patch":{},"invalid_patch":{}}' in case
    assert "pokračuj dalšími nezávislými povolenými větvemi" in case
    assert "Neodesílej žádnou průběžnou finální odpověď" in case
    assert case.rstrip().removesuffix("~~~").rstrip().endswith(
        "Po této jediné finální odpovědi okamžitě skonči; žádný další commentary, final ani nástroj."
    )
    assert "Doslovný `{{FIXTURE_ROOT}}` je placeholder, nikdy skutečný root" in case
    assert "Chybí-li skutečný vstup pro větev, označ ji `NOT_RUN/NOT_VERIFIED` a nevolej ji" in case
    assert "Před jedinou finální odpovědí dokonči všechny nezávislé povolené větve" in case
    assert "`validate_patch` volej jen s přesným neprázdným manifestovým diffem v `query`" in case
    assert "Seznam akcí delegate/solve/review_diff je podmíněný úplným live enumem" in case
    assert "Akci `generate_tests` nevolej při `available=false`" in case
    assert '`route` vyžaduje `path`' in case
    assert '`investigate` a `diagnose` používají `query`, ne `task`' in case
    assert '`diff` je Git diff' in case
    assert 'Syntetický patch patří do `validate_patch.query`' in case
    assert "`framework` je výstupní kritérium, ne argument volání" in case
