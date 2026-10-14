from __future__ import annotations

from pathlib import Path
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_python_symbol_signatures_contain_types_and_defaults(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "code_index": {"enabled": True}}
    repo_tools = RepositoryTools(config)
    idx = CodeIndex(config, repo_tools=repo_tools)

    py_file = tmp_path / "service.py"
    py_file.write_text(
        "def process_data(data: list[str], count: int = 10) -> bool:\n"
        "    return True\n\n"
        "class Handler:\n"
        "    def handle_request(self, req: Request, retry: bool = False) -> Response:\n"
        "        pass\n\n"
        "    async def async_dispatch(self, payload: dict[str, Any]) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )

    idx.update_file(str(tmp_path), "service.py")

    # 1. Check top-level function signature
    res_func = idx.find_symbol(str(tmp_path), "process_data")
    assert res_func["success"] is True
    assert len(res_func["symbols"]) == 1
    sig_func = res_func["symbols"][0]["signature"]
    assert "data: list[str]" in sig_func
    assert "count: int" in sig_func and "10" in sig_func
    assert "-> bool" in sig_func

    # 2. Check method signature
    res_method = idx.find_symbol(str(tmp_path), "handle_request")
    assert res_method["success"] is True
    assert len(res_method["symbols"]) == 1
    sig_method = res_method["symbols"][0]["signature"]
    assert "self" in sig_method
    assert "req: Request" in sig_method
    assert "retry: bool" in sig_method and "False" in sig_method
    assert "-> Response" in sig_method

    # 3. Check async method signature
    res_async = idx.find_symbol(str(tmp_path), "async_dispatch")
    assert res_async["success"] is True
    assert len(res_async["symbols"]) == 1
    sig_async = res_async["symbols"][0]["signature"]
    assert sig_async.startswith("async def")
    assert "payload: dict[str, Any]" in sig_async
    assert "-> None" in sig_async


def test_typescript_symbol_signatures_contain_types_and_return(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}, "code_index": {"enabled": True}}
    repo_tools = RepositoryTools(config)
    idx = CodeIndex(config, repo_tools=repo_tools)

    ts_file = tmp_path / "calculator.ts"
    ts_file.write_text(
        "export function computeScore(points: number[], factor: number = 1.0): number {\n"
        "    return 100;\n"
        "}\n\n"
        "export class ScoringService {\n"
        "    public evaluateCandidate(candidate: Candidate, strict: boolean): boolean {\n"
        "        return true;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    idx.update_file(str(tmp_path), "calculator.ts")

    # Check function signature
    res_func = idx.find_symbol(str(tmp_path), "computeScore")
    assert res_func["success"] is True
    assert len(res_func["symbols"]) == 1
    sig_func = res_func["symbols"][0]["signature"]
    assert "computeScore" in sig_func
    assert "points: number[]" in sig_func
    assert "number" in sig_func
    assert not sig_func.endswith("{")
