from __future__ import annotations

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


def test_generate_mocks_typescript(tmp_path: Path) -> None:
    p = tmp_path / "payment.ts"
    p.write_text("export interface PaymentGateway { process(): void; }", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.generate_mocks(str(tmp_path), "payment.ts", "PaymentGateway")
    assert res["success"] is True
    assert res["language"] == "typescript"
    assert "mockPaymentGateway" in res["mock_code"]
    assert "jest.mock" in res["fixture_code"]
