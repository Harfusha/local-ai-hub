from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub.rag import RAGStore


def test_python_ast_chunking_with_parent_headers(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"chunk_chars": 200, "chunk_overlap_chars": 20},
    }
    engine = RAGStore(config=config)

    code = (
        "import os\nimport sys\n\n"
        "class HeavyService:\n"
        "    def method_one(self):\n"
        "        x = 1\n"
        "        y = 2\n"
        "        return x + y\n\n"
        "    def method_two(self):\n"
        "        a = 'alpha'\n"
        "        b = 'beta'\n"
        "        return a + b\n"
    )

    chunks = engine._chunks(code, path="service.py")
    assert len(chunks) >= 2
    # Check that method chunks contain class context header
    assert any("class HeavyService" in c and "method_one" in c for c in chunks)
    assert any("class HeavyService" in c and "method_two" in c for c in chunks)


def test_python_ast_chunking_large_function_has_enclosing_header(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"chunk_chars": 150, "chunk_overlap_chars": 10},
    }
    engine = RAGStore(config=config)

    long_func = (
        "def compute_heavy_pipeline(data: list[int]) -> int:\n"
        + "".join([f"    step_{i} = data[{i % 5}] * {i}\n" for i in range(25)])
        + "    return sum(data)\n"
    )

    chunks = engine._chunks(long_func, path="pipeline.py")
    assert len(chunks) > 1
    # Subsequent sub-slices of the large function should contain the enclosing signature header
    for c in chunks[1:]:
        assert "[Enclosing:" in c or "def compute_heavy_pipeline" in c


def test_brace_language_chunking_with_context(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"chunk_chars": 200, "chunk_overlap_chars": 20},
    }
    engine = RAGStore(config=config)

    ts_code = (
        "import { Router } from 'express';\n\n"
        "export class OrderController {\n"
        "    async getOrder(id: string) {\n"
        "        const order = await db.find(id);\n"
        "        return order;\n"
        "    }\n"
        "    async cancelOrder(id: string) {\n"
        "        await db.cancel(id);\n"
        "        return true;\n"
        "    }\n"
    )

    chunks = engine._chunks(ts_code, path="order.ts")
    assert len(chunks) >= 1
    assert any("OrderController" in c for c in chunks)
