import ast
from pathlib import Path

from local_ai_hub import agent_events


def test_schema_catalog_does_not_override_existing_object_fingerprints():
    """Later catalog additions must not silently replace canonical definitions."""
    source = Path(agent_events.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    seen = set()
    for node in ast.walk(tree):
        catalogs = []
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_EXPECTED_OBJECT_SQL_HASHES"
            for target in node.targets
        ):
            catalogs.append(node.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "_EXPECTED_OBJECT_SQL_HASHES"):
            catalogs.extend(node.args)
        for catalog in catalogs:
            assert isinstance(catalog, ast.Dict)
            for key in catalog.keys:
                identity = ast.literal_eval(key)
                assert identity not in seen, f"duplicate schema authority: {identity}"
                seen.add(identity)
