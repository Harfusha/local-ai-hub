from __future__ import annotations

import ast
from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine


def test_ast_rename_multi_language(tmp_path: Path) -> None:
    # Python file
    py_file = tmp_path / "calc.py"
    py_file.write_text("def add(a, b):\n    return a + b\n\nres = add(1, 2)\n", encoding="utf-8")

    # TypeScript file referencing add
    ts_file = tmp_path / "service.ts"
    ts_file.write_text("import { add } from './calc';\nconst val = add(10, 20);\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})

    # Dry run
    res = engine.ast_rename(str(tmp_path), "calc.py", "add", "sum_numbers", apply_changes=False)
    assert res["success"] is True
    assert res["applied"] is False
    assert "calc.py" in res["affected_files"]
    assert "service.ts" in res["affected_files"]
    assert "sum_numbers" in res["diffs"]["calc.py"]
    assert "sum_numbers" in res["diffs"]["service.ts"]

    # File contents should still be unchanged
    assert "def add" in py_file.read_text(encoding="utf-8")

    # Apply changes
    res_apply = engine.ast_rename(str(tmp_path), "calc.py", "add", "sum_numbers", apply_changes=True)
    assert res_apply["success"] is True
    assert res_apply["applied"] is True
    assert "def sum_numbers" in py_file.read_text(encoding="utf-8")
    assert "const val = sum_numbers(10, 20);" in ts_file.read_text(encoding="utf-8")


def test_generate_mocks_python_class(tmp_path: Path) -> None:
    code = (
        "class UserService:\n"
        "    def get_user(self, user_id: str):\n"
        "        pass\n"
        "    def delete_user(self, user_id: str):\n"
        "        pass\n"
    )
    p = tmp_path / "user_service.py"
    p.write_text(code, encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.generate_mocks(str(tmp_path), "user_service.py", "UserService")
    assert res["success"] is True
    assert res["kind"] == "class"
    assert res["language"] == "python"
    assert "get_user" in res["methods"]
    assert "delete_user" in res["methods"]
    assert "class MockUserService:" in res["mock_code"]
    assert "@pytest.fixture" in res["fixture_code"]
    assert "create_autospec(UserService" in res["fixture_code"]


def test_generate_mocks_python_unknown_symbol_emits_valid_fixture(tmp_path: Path) -> None:
    p = tmp_path / "module.py"
    p.write_text("value = 1\n", encoding="utf-8")

    res = DeterministicEngine({"server": {"state_dir": str(tmp_path)}}).generate_mocks(
        str(tmp_path), "module.py", "MissingSymbol"
    )

    assert res["success"] is True
    ast.parse(res["fixture_code"])
    assert "return unittest.mock.MagicMock" in res["fixture_code"]
    assert "return mock_MissingSymbol =" not in res["fixture_code"]


def test_generate_mocks_python_rejects_invalid_symbol(tmp_path: Path) -> None:
    p = tmp_path / "module.py"
    p.write_text("value = 1\n", encoding="utf-8")

    res = DeterministicEngine({"server": {"state_dir": str(tmp_path)}}).generate_mocks(
        str(tmp_path), "module.py", "Missing-Symbol"
    )

    assert res == {
        "success": False,
        "error": "Python mock symbols must be valid identifiers",
    }


def test_generate_mocks_python_rejects_keyword_symbol(tmp_path: Path) -> None:
    p = tmp_path / "module.py"
    p.write_text("value = 1\n", encoding="utf-8")

    res = DeterministicEngine({"server": {"state_dir": str(tmp_path)}}).generate_mocks(
        str(tmp_path), "module.py", "class"
    )

    assert res == {
        "success": False,
        "error": "Python mock symbols must be valid identifiers",
    }


def test_generate_mocks_python_function_uses_nested_module_path(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "service.py").write_text("def fetch():\n    return 1\n", encoding="utf-8")

    res = DeterministicEngine({"server": {"state_dir": str(tmp_path)}}).generate_mocks(
        str(tmp_path), "pkg/service.py", "fetch"
    )

    assert res["success"] is True
    assert "patch('pkg.service.fetch')" in res["fixture_code"]


def test_generate_mocks_typescript(tmp_path: Path) -> None:
    p = tmp_path / "payment.ts"
    p.write_text("export interface PaymentGateway { process(): void; }", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.generate_mocks(str(tmp_path), "payment.ts", "PaymentGateway")
    assert res["success"] is True
    assert res["language"] == "typescript"
    assert "mockPaymentGateway" in res["mock_code"]
    assert "jest.mock" in res["fixture_code"]
