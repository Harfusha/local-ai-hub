import pytest

from local_ai_hub.features import FeatureSet
from local_ai_hub.llama_cpp import LlamaCppRouter


@pytest.mark.parametrize("auto_start", [False, True])
def test_external_ollama_remains_available_independently_of_autostart(auto_start):
    features = FeatureSet({"ollama": {"enabled": True}, "server": {"auto_start_ollama": auto_start},
                           "llama_cpp": {"mode": "off"}})
    assert features.ollama is True
    assert features.tasks is True
    assert features.work_orchestrator is True


@pytest.mark.parametrize("auto_start", [False, True])
def test_disabled_ollama_is_not_enabled_by_autostart(auto_start):
    features = FeatureSet({"ollama": {"enabled": False}, "server": {"auto_start_ollama": auto_start},
                           "llama_cpp": {"mode": "off"}})
    assert features.ollama is False
    assert features.tasks is False
    assert features.work_orchestrator is False


@pytest.mark.parametrize("enabled", [None, 1, "true"])
def test_non_boolean_ollama_enablement_does_not_expose_model_tools(enabled):
    features = FeatureSet({"ollama": {"enabled": enabled}, "llama_cpp": {"mode": "off"}})
    assert features.ollama is False
    assert features.tasks is False


@pytest.mark.parametrize("gpus", [[], [{"vendor": "nvidia", "integrated": False}], [{"vendor": "intel"}]])
def test_external_llama_auto_routes_are_available_independently_of_hardware(gpus):
    cfg = {"ollama": {"enabled": False}, "_hardware": {"gpus": gpus},
           "llama_cpp": {"mode": "auto", "models": {"example": {"url": "http://127.0.0.1:12438"}}}}
    features = FeatureSet(cfg)
    assert features.llama_cpp is True
    assert features.tasks is True
    assert features.work_orchestrator is True


@pytest.mark.parametrize("llama", [{"mode": "off", "models": {"example": {}}},
                                     {"mode": "auto", "models": {}}])
def test_llama_off_or_without_models_does_not_expose_model_tools(llama):
    features = FeatureSet({"ollama": {"enabled": False}, "llama_cpp": llama})
    assert features.llama_cpp is False
    assert features.tasks is False


@pytest.mark.parametrize("url, allowed", [("http://127.0.0.1:12438", True),
                                          ("http://example.com:12438", False)])
def test_external_llama_router_still_requires_loopback(url, allowed):
    cfg = {"llama_cpp": {"mode": "auto", "models": {"example": {"url": url}}}}
    assert (LlamaCppRouter(cfg)._entry("example") is not None) is allowed
