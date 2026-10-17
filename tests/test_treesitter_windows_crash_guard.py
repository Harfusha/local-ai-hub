from types import SimpleNamespace
import builtins

from local_ai_hub import treesitter_parser as module


def test_windows_313_does_not_import_native_pack_after_verified_access_violation(monkeypatch):
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=(3, 13, 2)))
    monkeypatch.setattr(module, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(module, "_PARSERS", {})
    monkeypatch.setattr(module, "_LANGUAGES", {})
    monkeypatch.setattr(module, "_WORKER_DISABLED_CAUSE", "verified_access_violation")
    monkeypatch.setattr(module, "_WORKER_POOL", None)
    imports = []
    original_import = builtins.__import__

    def capture_import(name, *args, **kwargs):
        if name.startswith("tree_sitter"):
            imports.append(name)
            raise ImportError("native backend must not be loaded")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", capture_import)
    assert module._init_treesitter() is False
    result = module.parse_treesitter_with_status("def example():\n    return 42\n", "python")
    assert result["result"] is None
    assert result["status"] == "unavailable"
    assert imports == []


def test_python_symbols_and_calls_survive_native_backend_guard(monkeypatch):
    from local_ai_hub.code_index import CodeIndex

    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=(3, 13, 2)))
    monkeypatch.setattr(module, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(module, "_PARSERS", {})
    monkeypatch.setattr(module, "_WORKER_DISABLED_CAUSE", "verified_access_violation")
    monkeypatch.setattr(module, "_WORKER_POOL", None)
    index = object.__new__(CodeIndex)
    index.repo_tools = SimpleNamespace(max_file_bytes=2_000_000)
    symbols, references, edges, diagnostic = index._parse_file_content_report(
        "def callee():\n    return 42\ndef caller():\n    return callee()\n", "python"
    )
    assert {item["name"] for item in symbols} >= {"caller", "callee"}
    assert any(item["name"] == "callee" for item in references)
    assert any(item["kind"] == "calls" and item["dst"] == "callee" for item in edges)
    assert diagnostic["fallback_used"] is True
