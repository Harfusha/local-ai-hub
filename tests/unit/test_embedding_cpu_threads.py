from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import local_ai_hub.embeddings as embeddings


def test_embedding_cpu_route_caps_torch_threads(monkeypatch):
    calls = []
    fake_torch = SimpleNamespace(
        get_num_threads=lambda: 96,
        set_num_threads=calls.append,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(embeddings.os, "cpu_count", lambda: 8)

    embeddings._limit_embedding_cpu_threads("sentence-transformers", "cpu")

    assert calls == [4]


def test_embedding_gpu_route_does_not_change_torch_threads(monkeypatch):
    original_import = builtins.__import__

    def tracked_import(name, *args, **kwargs):
        if name == "torch":
            raise AssertionError("GPU route must not configure CPU thread count")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)

    embeddings._limit_embedding_cpu_threads("sentence-transformers", "cuda:0")


def test_embedding_cpu_thread_cap_is_best_effort(monkeypatch):
    fake_torch = SimpleNamespace(
        get_num_threads=lambda: 96,
        set_num_threads=lambda _count: (_ for _ in ()).throw(RuntimeError("thread pool locked")),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(embeddings.os, "cpu_count", lambda: 8)

    embeddings._limit_embedding_cpu_threads("sentence-transformers", "cpu")
