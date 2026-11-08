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
    def test_explicitly_disabled_model_backend_is_off(self):
        fs = FeatureSet({"ollama": {"enabled": False}})
        assert fs.serena is True
        assert not hasattr(fs, "codegraph")
        assert fs.rag is True
        assert fs.ollama is False
        assert fs.subagents is False

    def test_default_model_names(self):
        fs = FeatureSet({})
        assert fs.fast_model == "qwen2.5-coder:1.5b"

    def test_codegraph_is_not_a_feature_toggle(self):
        fs = FeatureSet({"code_intelligence": {"codegraph_enabled": True}})
        assert not hasattr(fs, "codegraph")
        assert not hasattr(fs, "graph")

    def test_has_semantic_true_when_serena_on(self):
        assert FeatureSet({}).has_semantic() is True

    def test_has_any_model_true_when_ollama_on(self):
        assert FeatureSet({"ollama": {"enabled": True}}).has_any_model() is True


@pytest.mark.parametrize(
    ("profile", "can_submit"),
    [("cpu", False), ("integrated", False), ("low", False), ("balanced", False), ("high", True), ("max", True)],
)
def test_bounded_work_submit_action_respects_hardware_profile(profile, can_submit):
    fs = FeatureSet({"features": {"bounded_local_work": True}, "hardware": {"profile": profile}})

    assert ("submit" in fs.supported_work_actions()) is can_submit


def test_hardware_capabilities_use_detected_effective_profile():
    fs = FeatureSet({"features": {"bounded_local_work": True}, "hardware": {"profile": "auto"}, "_hardware": {"profile": "high"}})

    assert fs.hardware_profile == "high"
    assert "submit" in fs.supported_work_actions()


def test_search_summary_capability_starts_at_balanced():
    low = FeatureSet({"features": {"search_summaries": True}, "hardware": {"profile": "low"}})
    balanced = FeatureSet({"features": {"search_summaries": True}, "hardware": {"profile": "balanced"}})
    opt_out = FeatureSet({"hardware": {"profile": "balanced"}})

    assert low.search_summaries is False
    assert balanced.search_summaries is True
    assert opt_out.search_summaries is False
    assert not any("summarize_results" in line for line in low.specialized_trigger_lines())
    assert any("summarize_results" in line for line in balanced.specialized_trigger_lines())


def test_local_task_actions_follow_hardware_tiers_and_unknown_fails_closed():
    low = FeatureSet({"hardware": {"profile": "low"}}).supported_task_actions()
    balanced = FeatureSet({"features": {"local_semantic_analysis": True}, "hardware": {"profile": "balanced"}}).supported_task_actions()
    high = FeatureSet({"features": {"local_semantic_analysis": True, "local_vision": True, "local_code_generation": True, "local_automation": True}, "hardware": {"profile": "high"}}).supported_task_actions()
    unknown = FeatureSet({"hardware": {"profile": "mystery"}})

    assert "compress" in low
    assert {"reason", "review", "second_opinion"}.isdisjoint(low)
    assert {"reason", "review", "second_opinion"}.issubset(balanced)
    assert "vision" not in balanced and "vision" in high
    assert "automation" in high
    assert "scaffold" not in balanced and "scaffold" in high
    assert unknown.hardware_profile == "low"


def test_capability_status_reports_profile_ceiling_and_non_quality_gates():
    low = FeatureSet({"features": {"search_summaries": True}, "hardware": {"profile": "low"}}).capability_status()
    balanced = FeatureSet({"features": {"search_summaries": True, "local_semantic_analysis": True}, "hardware": {"profile": "balanced"}}).capability_status()
    high = FeatureSet({"features": {"bounded_local_work": True}, "hardware": {"profile": "high"}}).capability_status()

    assert low["search_summaries"]["available"] is False
    assert low["search_summaries"]["minimum_profile"] == "balanced"
    assert low["search_summaries"]["reason"] == "requires_balanced_profile"
    assert low["search_summaries"]["state"] == "profile_blocked"
    assert low["search_summaries"]["authority"] == "advisory"
    assert low["search_summaries"]["quality_gate"] == "not_qualified_by_default"
    assert balanced["search_summaries"]["available"] is True
    assert balanced["semantic_analysis"]["available"] is True
    assert balanced["semantic_analysis"]["state"] == "enabled_by_operator"
    assert balanced["semantic_analysis"]["provider_readiness"] == "not_checked"
    assert balanced["semantic_analysis"]["feature_gate"] == "local_semantic_analysis"
    assert balanced["bounded_local_work"]["reason"] == "requires_high_profile"
    assert high["bounded_local_work"]["available"] is True
    assert high["bounded_local_work"]["reason"] == "task_quality_and_explicit_permissions_required"


def test_repository_semantic_actions_use_shared_tier_registry():
    low = FeatureSet({"hardware": {"profile": "low"}}).supported_repo_actions()
    balanced = FeatureSet({"features": {"local_semantic_analysis": True}, "hardware": {"profile": "balanced"}}).supported_repo_actions()
    high = FeatureSet({"features": {"local_semantic_analysis": True}, "hardware": {"profile": "high"}}).supported_repo_actions()

    assert {"investigate", "diagnose"}.issubset(low)
    assert {"delegate", "review_diff", "solve"}.isdisjoint(low)
    assert "review_diff" in balanced
    assert "delegate" in balanced
    assert "solve" not in balanced
    assert "solve" in high


def test_high_profile_does_not_promote_unqualified_capabilities():
    fs = FeatureSet({"hardware": {"profile": "high"}})

    assert {"reason", "review", "vision", "complete_code", "scaffold", "automation"}.isdisjoint(fs.supported_task_actions())
    assert {"review_diff", "solve"}.isdisjoint(fs.supported_repo_actions())
    assert "submit" not in fs.supported_work_actions()
    assert fs.capability_status()["semantic_analysis"]["state"] == "feature_disabled"


class TestVisionConfig:
    @pytest.mark.parametrize("vision_model", [None, 17, ["qwen3-vl:4b"], {"name": "qwen3-vl:4b"}, " qwen3-vl:4b", "qwen3-vl:4b\x00"])
    def test_malformed_vision_model_fails_closed(self, vision_model):
        fs = FeatureSet({"models": {"vision": vision_model}})

        assert fs.vision is False
        assert fs.vision_model == ""

    def test_valid_vision_model_enables_vision(self):
        fs = FeatureSet({"ollama": {"enabled": True}, "models": {"vision": "qwen3-vl:8b"}})

        assert fs.vision is True
        assert fs.vision_model == "qwen3-vl:8b"


class TestSerenaDisabled:
    def test_serena_disabled(self):
        cfg = {"code_intelligence": {"serena_enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.serena is False
        assert not hasattr(fs, "codegraph")
        assert fs.has_semantic() is False

    def test_stale_codegraph_flag_does_not_enable_semantics(self):
        cfg = {"code_intelligence": {"serena_enabled": False, "codegraph_enabled": True}}
        fs = FeatureSet(cfg)
        assert fs.has_semantic() is False
        assert fs.semantic_hint() == ""

    def test_code_intelligence_master_off(self):
        cfg = {"code_intelligence": {"enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.serena is False
        assert not hasattr(fs, "codegraph")

    def test_semantic_hint_reports_serena_when_stale_flag_is_set(self):
        cfg = {"code_intelligence": {"codegraph_enabled": True}}
        fs = FeatureSet(cfg)
        assert fs.semantic_hint() == "semantic"

    def test_semantic_hint_reports_only_serena(self):
        assert FeatureSet({}).semantic_hint() == "semantic"


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
        cfg = {"ollama": {"enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.ollama is False
        assert fs.has_any_model() is False
        assert fs.subagents is False

    def test_trigger_map_no_task_when_ollama_off(self):
        cfg = {"ollama": {"enabled": False}}
        lines = FeatureSet(cfg).trigger_map_lines()
        assert not any("local_ai_task" in line for line in lines)

    def test_cheapest_path_no_model_when_ollama_off(self):
        cfg = {"ollama": {"enabled": False}}
        fs = FeatureSet(cfg)
        assert fs.fast_model not in fs.cheapest_path_hint()

    def test_llama_cpp_backend_keeps_local_tasks_available_when_ollama_is_off(self):
        cfg = {
            "ollama": {"enabled": False},
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
        cfg = {"ollama": {"enabled": True}, "models": {"fast_code": "custom-coder:7b"}}
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
        cfg = {"code_intelligence": {"serena_enabled": False, "codegraph_enabled": True}}
        assert "semantic/graph" not in self.build(cfg)
    def test_semantic_route_absent_without_serena(self):
        cfg = {"code_intelligence": {"serena_enabled": False}}
        assert "-> semantic" not in self.build(cfg)

    def test_model_name_custom(self):
        policy = self.build({"ollama": {"enabled": True}, "models": {"fast_code": "awesome-coder:7b"}})
        assert "active hardware profile and user overrides" in policy
        assert "check installed models before inference" in policy

    def test_task_absent_when_ollama_off(self):
        cfg = {"ollama": {"enabled": False}, "server": {"auto_start_ollama": False}}
        assert "Semantic delegation is on-demand and optional" not in self.build(cfg)

    def test_work_submission_guidance_is_high_tier_only(self):
        base = {
            "ollama": {"enabled": True},
            "commands": {"enabled": True},
            "coord": {"enabled": True},
            "work_orchestrator": {"enabled": True},
        }
        low = self.build({**base, "hardware": {"profile": "balanced"}})
        high = self.build({**base, "features": {"bounded_local_work": True}, "hardware": {"profile": "high"}})

        assert 'local_ai_work(action="submit"' not in low
        assert 'local_ai_work(action="submit"' in high

    def test_search_summary_guidance_is_profile_aware(self):
        low = self.build({"hardware": {"profile": "low"}})
        balanced = self.build({"features": {"search_summaries": True}, "hardware": {"profile": "balanced"}})

        assert "summarize_results" not in low
        assert "summarize_results" in balanced


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
        from local_ai_hub.resilience import RecoveryJournal

        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("[features]\ncommands = true\n", encoding="utf-8")
        journal = RecoveryJournal(tmp_path)
        old_app = http_server.APP

        class DummyApp:
            config = {"_config_path": str(cfg_file), "features": {"commands": True}}
            recovery = journal

        try:
            http_server.APP = DummyApp()
            handler = Handler.__new__(Handler)
            handler.client_address = ("127.0.0.1", 12345)
            handler.path = "/api/config/update"
            handler.headers = {}
            handler._read_json = lambda limit=None: {"action": "update", "settings": {"features.commands": False}}
            handler._require_authorized = lambda: True
            handler._begin_trace = lambda path: setattr(handler, "_trace_request_id", "config-toggle-test")
            handler._agent = lambda: "test-agent"
            sent = []

            def send(status, body):
                if getattr(handler, "_journal_request_id", None) and not getattr(handler, "_journal_finished", False):
                    journal.finish(handler._journal_request_id, status < 400, status_code=status, response=body)
                    handler._journal_finished = True
                sent.append((status, body))

            handler._send = send

            handler.do_POST()
            assert len(sent) == 1
            assert sent[0][0] == 200
            assert sent[0][1]["success"] is True
            assert sent[0][1]["restart_required"] is True
        finally:
            http_server.APP = old_app


def test_nvidia_hardware_metrics_include_total_and_free_vram(monkeypatch):
    from types import SimpleNamespace

    from local_ai_hub import hardware

    monkeypatch.setattr(hardware.shutil, "which", lambda _: "nvidia-smi")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA RTX 5070 Ti, 16376, 12000, 560.00\n",
        )

    monkeypatch.setattr(hardware, "_run", run)

    assert hardware._nvidia() == [
        {
            "vendor": "nvidia",
            "name": "NVIDIA RTX 5070 Ti",
            "vram_mb": 16376,
            "vram_free_mb": 12000,
            "driver": "560.00",
            "backend": "cuda",
            "compute_cap": None,
            "has_fp4": False,
        }
    ]
    assert calls[0][1] == "--query-gpu=name,memory.total,memory.free,driver_version,compute_cap"


def test_nvidia_hardware_metrics_keep_total_when_free_vram_query_fails(monkeypatch):
    from types import SimpleNamespace

    from local_ai_hub import hardware

    monkeypatch.setattr(hardware.shutil, "which", lambda _: "nvidia-smi")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA RTX 5070 Ti, 16376, 560.00\n",
        )

    monkeypatch.setattr(hardware, "_run", run)

    assert hardware._nvidia() == [
        {
            "vendor": "nvidia",
            "name": "NVIDIA RTX 5070 Ti",
            "vram_mb": 16376,
            "vram_free_mb": None,
            "driver": "560.00",
            "backend": "cuda",
            "compute_cap": None,
            "has_fp4": False,
        }
    ]
    assert calls[0][1] == "--query-gpu=name,memory.total,memory.free,driver_version,compute_cap"
    assert calls[1][1] == "--query-gpu=name,memory.total,driver_version,compute_cap"

