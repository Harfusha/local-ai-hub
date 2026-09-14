"""tests/test_features.py - unit tests for FeatureSet and config-aware builders."""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from local_ai_hub.features import FeatureSet


class TestFeatureSetDefaults:
    def test_all_on_by_default(self):
        fs = FeatureSet({})
        assert fs.serena is True
        assert fs.codegraph is True
        assert fs.rag is True
        assert fs.ollama is True
        assert fs.subagents is True

    def test_default_model_names(self):
        fs = FeatureSet({})
        assert fs.fast_model == "qwen2.5-coder:1.5b"

    def test_has_semantic_true_when_either_backend_on(self):
        assert FeatureSet({}).has_semantic() is True

    def test_has_any_model_true_when_ollama_on(self):
        assert FeatureSet({}).has_any_model() is True


class TestCodeIntelligenceDisabled:
    def test_serena_disabled(self):
        cfg = {"code_intelligence": {"serena_enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.serena is False
        assert fs.codegraph is True
        assert fs.has_semantic() is True

    def test_both_disabled(self):
        cfg = {"code_intelligence": {"serena_enabled": False, "codegraph_enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.has_semantic() is False
        assert fs.semantic_hint() == ""

    def test_code_intelligence_master_off(self):
        cfg = {"code_intelligence": {"enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.serena is False
        assert fs.codegraph is False

    def test_semantic_hint_serena_only(self):
        cfg = {"code_intelligence": {"codegraph_enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.semantic_hint() == "semantic"

    def test_semantic_hint_codegraph_only(self):
        cfg = {"code_intelligence": {"serena_enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.semantic_hint() == "graph"

    def test_semantic_hint_both(self):
        assert FeatureSet({}).semantic_hint() == "semantic/graph"


class TestRagDisabled:
    def test_rag_off(self):
        cfg = {"features": {"rag": False}}
        fs = FeatureSet(cfg)
        assert fs.rag is False

    def test_trigger_map_no_rag(self):
        cfg = {"features": {"rag": False}}
        fs = FeatureSet(cfg)
        lines = fs.trigger_map_lines()
        assert not any("local_ai_rag" in line for line in lines)

    def test_trigger_map_has_rag_when_enabled(self):
        lines = FeatureSet({}).trigger_map_lines()
        assert any("local_ai_rag" in line for line in lines)

    def test_cheapest_path_no_rag(self):
        fs = FeatureSet({"features": {"rag": False}})
        assert "RAG" not in fs.cheapest_path_hint()

    def test_cheapest_path_with_rag(self):
        assert "RAG" in FeatureSet({}).cheapest_path_hint()


class TestOllamaDisabled:
    def test_ollama_off(self):
        cfg = {"server": {"auto_start_ollama": False}}
        fs = FeatureSet(cfg)
        assert fs.ollama is False
        assert fs.has_any_model() is False
        assert fs.subagents is False

    def test_trigger_map_no_task_when_ollama_off(self):
        cfg = {"server": {"auto_start_ollama": False}}
        lines = FeatureSet(cfg).trigger_map_lines()
        assert not any("local_ai_task" in line for line in lines)

    def test_cheapest_path_no_model_when_ollama_off(self):
        cfg = {"server": {"auto_start_ollama": False}}
        fs = FeatureSet(cfg)
        assert fs.fast_model not in fs.cheapest_path_hint()

    def test_llama_cpp_backend_keeps_local_tasks_available_when_ollama_is_off(self):
        cfg = {
            "server": {"auto_start_ollama": False},
            "llama_cpp": {
                "mode": "on",
                "models": {"qwen2.5-coder:3b": {"url": "http://127.0.0.1:12438"}},
            },
        }

        fs = FeatureSet(cfg)

        assert fs.ollama is False
        assert fs.llama_cpp is True
        assert fs.tasks is True
        assert fs.has_any_model() is True


class TestCustomModelNames:
    def test_custom_fast_model(self):
        cfg = {"models": {"fast_code": "my-model:latest"}}
        assert FeatureSet(cfg).fast_model == "my-model:latest"

    def test_custom_model_in_cheapest_path(self):
        cfg = {"models": {"fast_code": "custom-coder:7b"}}
        assert "custom-coder:7b" in FeatureSet(cfg).cheapest_path_hint()


class TestBuildGlobalPolicy:
    @pytest.fixture(autouse=True)
    def _import_setup(self):
        tools = Path(__file__).resolve().parents[1] / "tools" / "setup.py"
        spec = importlib.util.spec_from_file_location("setup_module", tools)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.build = mod.build_global_policy

    def test_policy_has_markers(self):
        policy = self.build({})
        assert "<!-- BEGIN LOCAL AI HUB TOOL POLICY -->" in policy
        assert "<!-- END LOCAL AI HUB TOOL POLICY -->" in policy

    def test_rag_absent_when_disabled(self):
        assert "local_ai_rag" not in self.build({"features": {"rag": False}})

    def test_rag_present_when_enabled(self):
        assert "local_ai_rag" in self.build({})

    def test_semantic_absent_when_no_backend(self):
        cfg = {"code_intelligence": {"serena_enabled": False, "codegraph_enabled": False}}
        assert "semantic/graph" not in self.build(cfg)

    def test_model_name_custom(self):
        assert "awesome-coder:7b" in self.build({"models": {"fast_code": "awesome-coder:7b"}})

    def test_task_absent_when_ollama_off(self):
        cfg = {"server": {"auto_start_ollama": False}}
        assert "local_ai_task" not in self.build(cfg)


class TestRoutingEngineConfigModel:
    def test_app_passes_config_and_agent_state_to_router(self, tmp_path: Path):
        from local_ai_hub.app import LocalAIApp
        from local_ai_hub.agent_routing import RouteRequest

        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            f'''[server]
state_dir = "{(tmp_path / "state").as_posix()}"

[models]
fast_code = "configured-router:7b"

[agent_state]
enabled = true
''',
            encoding="utf-8",
        )
        app = LocalAIApp(str(cfg_path))
        try:
            assert app.agent_routing.state_store is app.agent_state
            assert app.agent_routing.select(RouteRequest(needs_model=True)).target == "configured-router:7b"
        finally:
            app.close()

    def test_default_model(self):
        from local_ai_hub.agent_routing import RoutingEngine, RouteRequest
        engine = RoutingEngine()
        dec = engine.select(RouteRequest(needs_model=True))
        assert dec.target == "qwen2.5-coder:1.5b"

    def test_custom_model_from_cfg(self):
        from local_ai_hub.agent_routing import RoutingEngine, RouteRequest
        engine = RoutingEngine(cfg={"models": {"fast_code": "custom:3b"}})
        dec = engine.select(RouteRequest(needs_model=True))
        assert dec.target == "custom:3b"

    def test_cfg_does_not_affect_cache_decision(self):
        from local_ai_hub.agent_routing import RoutingEngine, RouteRequest
        engine = RoutingEngine(cfg={"models": {"fast_code": "custom:3b"}})
        dec = engine.select(RouteRequest(has_fresh_cache=True, needs_model=True))
        assert dec.kind == "cache"

    def test_dashboard_toggle(self):
        assert FeatureSet({}).dashboard is True
        assert FeatureSet({"features": {"dashboard": False}}).dashboard is False
        assert FeatureSet({"monitoring": {"dashboard_enabled": False}}).dashboard is False

    def test_config_update_allows_feature_toggles(self, tmp_path):
        from local_ai_hub.http_server import Handler
        from local_ai_hub import http_server

        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("[features]\ncommands = true\n", encoding="utf-8")
        old_app = http_server.APP

        class DummyApp:
            config = {"_config_path": str(cfg_file), "features": {"commands": True}}

        try:
            http_server.APP = DummyApp()
            handler = Handler.__new__(Handler)
            handler.client_address = ("127.0.0.1", 12345)
            handler.path = "/api/config/update"
            handler.headers = {}
            handler._read_json = lambda limit=None: {"action": "update", "settings": {"features.commands": False}}
            handler._require_authorized = lambda: True
            handler._begin_trace = lambda path: None
            handler._tenant = lambda: "test"
            sent = []
            handler._send = lambda status, body: sent.append((status, body))

            handler.do_POST()
            assert len(sent) == 1
            assert sent[0][0] == 200
            assert sent[0][1]["success"] is True
            assert sent[0][1]["restart_required"] is True
        finally:
            http_server.APP = old_app

