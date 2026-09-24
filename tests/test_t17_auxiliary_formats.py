from __future__ import annotations

import ast
import cProfile
import csv
import io
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine


def _engine(tmp_path: Path) -> DeterministicEngine:
    return DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}, "rag": {}, "search": {}}
    )


def test_synthesized_rules_are_stable_and_have_parseable_contract(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    engine = _engine(tmp_path)

    first = engine.synthesize_rules(str(tmp_path), limit=20)
    second = engine.synthesize_rules(str(tmp_path), limit=20)

    assert first == second
    parsed = json.loads(json.dumps(first))
    assert parsed["success"] is True
    assert parsed["rule_count"] == len(parsed["rules"])
    assert len({rule["rule_id"] for rule in parsed["rules"]}) == parsed["rule_count"]
    assert all(
        {"rule_id", "title", "context", "guidance", "confidence"} <= rule.keys()
        and 0.0 <= rule["confidence"] <= 1.0
        for rule in parsed["rules"]
    )


def test_generated_datasets_are_deterministic_and_parse_as_declared_formats(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    schema = {"id": "uuid", "name": "str", "age": "int", "is_admin": "bool"}
    other_root = tmp_path / "other-project"
    other_root.mkdir()
    other_engine = _engine(other_root)

    for output_format in ("json", "csv", "sql"):
        first = engine.generate_dataset(str(tmp_path), schema, count=4, format=output_format)
        second = engine.generate_dataset(str(tmp_path), schema, count=4, format=output_format)
        from_other_root = other_engine.generate_dataset(
            str(other_root), schema, count=4, format=output_format
        )

        assert first["success"] is True
        assert first["count"] == 4
        assert first["data"] == second["data"]
        assert first["data"] == from_other_root["data"]

        if output_format == "json":
            rows = json.loads(first["data"])
            assert len(rows) == 4
            assert len({row["id"] for row in rows}) == 4
            assert all(set(row) == set(schema) for row in rows)
        elif output_format == "csv":
            rows = list(csv.DictReader(io.StringIO(first["data"])))
            assert len(rows) == 4
            assert set(rows[0]) == set(schema)
        else:
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute(
                    "CREATE TABLE test_dataset (id TEXT, name TEXT, age INTEGER, is_admin INTEGER)"
                )
                connection.executescript(first["data"])
                assert connection.execute("SELECT COUNT(*) FROM test_dataset").fetchone() == (4,)
            finally:
                connection.close()


def test_profile_digest_is_repeatable_and_json_compatible(tmp_path: Path) -> None:
    profile_path = tmp_path / "stable.pstats"
    profiler = cProfile.Profile()
    profiler.enable()
    sum(range(10000))
    profiler.disable()
    profiler.dump_stats(str(profile_path))
    engine = _engine(tmp_path)

    first = engine.profile_digest(str(profile_path), top_n=8)
    second = engine.profile_digest(str(profile_path), top_n=8)

    assert first == second
    parsed = json.loads(json.dumps(first))
    assert parsed["success"] is True
    assert parsed["format"] == "cProfile_pstats"
    assert parsed["top_functions"]
    assert all("function" in item and "cumulative_time_seconds" in item for item in parsed["top_functions"])


def test_profile_digest_parses_chrome_trace_and_text_profiles(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "traceEvents": [
                    {"name": "render", "dur": 30},
                    {"name": "render", "dur": 10},
                    {"name": "network", "dur": 25},
                ]
            }
        ),
        encoding="utf-8",
    )
    text_path = tmp_path / "profile.txt"
    text_path.write_text("1.25 3 0.1 0.2 render checkout\n", encoding="utf-8")
    engine = _engine(tmp_path)

    trace = engine.profile_digest(str(trace_path), top_n=8)
    text = engine.profile_digest(str(text_path), top_n=8)

    assert trace["success"] is True
    assert trace["format"] == "chrome_trace"
    assert trace["top_functions"][0] == {
        "function": "render",
        "cumulative_time_microseconds": 40.0,
        "calls": 2,
    }
    assert text["success"] is True
    assert text["format"] == "text_profile"
    assert text["top_functions"] == [{"summary": "1.25 3 0.1 0.2 render checkout"}]


def test_profile_digest_rejects_unrecognized_text_instead_of_empty_success(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "not-a-profile.txt"
    profile_path.write_text("this file has no profile records\n", encoding="utf-8")

    result = _engine(tmp_path).profile_digest(str(profile_path))

    assert result["success"] is False
    assert "failed to parse profile" in result["error"]


def test_generated_python_mocks_and_type_stubs_parse(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "class UserService:\n"
        "    def get_user(self, user_id: str) -> str:\n"
        "        return user_id\n",
        encoding="utf-8",
    )
    engine = _engine(tmp_path)

    mocks = engine.generate_mocks(str(tmp_path), "service.py", "UserService")
    second_mocks = engine.generate_mocks(str(tmp_path), "service.py", "UserService")
    first_stub = engine.generate_types(str(tmp_path), "service.py")
    second_stub = engine.generate_types(str(tmp_path), "service.py")

    assert mocks["success"] is True
    assert mocks["mock_code"] == second_mocks["mock_code"]
    assert mocks["fixture_code"] == second_mocks["fixture_code"]
    ast.parse(mocks["mock_code"])
    ast.parse(mocks["fixture_code"])
    assert first_stub["success"] is True
    assert first_stub["stub_content"] == second_stub["stub_content"]
    ast.parse(first_stub["stub_content"])


def test_generated_typescript_mocks_parse_as_esm(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js parser is unavailable")

    source = tmp_path / "payment.ts"
    source.write_text(
        "export interface PaymentGateway { process(): void; }\n",
        encoding="utf-8",
    )
    result = _engine(tmp_path).generate_mocks(str(tmp_path), "payment.ts", "PaymentGateway")

    assert result["success"] is True
    assert result["language"] == "typescript"
    for generated in (result["mock_code"], result["fixture_code"]):
        parsed = subprocess.run(
            [node, "--check", "--input-type=module"],
            input=generated,
            capture_output=True,
            text=True,
            check=False,
        )
        assert parsed.returncode == 0, parsed.stderr
