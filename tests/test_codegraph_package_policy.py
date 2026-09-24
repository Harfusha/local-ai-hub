import importlib.util
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup_policy", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_codegraph_package_default_matches_both_default_configs():
    expected = setup.CODEGRAPH_PACKAGE_DEFAULT
    assert expected == "codegraphcontext[gcf]==0.6.13"
    assert setup.configured_codegraph_package({}) == expected
    for path in (ROOT / "defaults.toml", ROOT / "src" / "local_ai_hub" / "defaults.toml"):
        with path.open("rb") as config_file:
            assert tomllib.load(config_file)["tools"]["codegraph_package"] == expected
