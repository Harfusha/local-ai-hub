from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OllamaSubagentProfile:
    name: str
    role: str
    model: str
    tools: tuple[str, ...]
    max_steps: int
    max_tool_calls: int
    max_tokens: int
    temperature: float
    advisory_only: bool = True
    model_fallback: bool = False


class OllamaSubagentCatalog:
    """Configuration and safety policy for named local advisory agents."""

    PROFILE_NAMES = ("qwen-explorer", "qwen-drafter", "qwen-critic")
    PROFILE_ALIASES = {
        "explorer": "qwen-explorer",
        "drafter": "qwen-drafter",
        "critic": "qwen-critic",
    }
    READ_ONLY_TOOLS = (
        "preprocessed_context",
        "deterministic_facts",
        "code_index",
        "semantic_symbols",
        "code_graph",
        "repo_search",
        "rag_search",
        "evidence_get",
        "file_slice",
    )

    def __init__(self, config: dict[str, Any]):
        self.config = config
        section = config.get("ollama_subagents", {})
        if not isinstance(section, dict):
            section = {}
        self.enabled = bool(section.get("enabled", True))
        self.default_profile = str(section.get("default_profile", "qwen-explorer"))
        self.language = str(section.get("language", "match_input"))
        raw_profiles = section.get("profiles", {})
        self.raw_profiles = raw_profiles if isinstance(raw_profiles, dict) else {}

    def resolve(self, name: str, available_models: set[str] | None = None) -> OllamaSubagentProfile:
        requested = str(name or self.default_profile).strip().lower()
        canonical = self.PROFILE_ALIASES.get(requested, requested)
        if canonical not in self.PROFILE_NAMES:
            valid = ", ".join(self.PROFILE_NAMES)
            raise ValueError(f"unknown Ollama subagent profile; valid profiles: {valid}")

        raw = self.raw_profiles.get(canonical, {})
        if not isinstance(raw, dict):
            raw = {}
        models = self.config.get("models", {})
        models = models if isinstance(models, dict) else {}
        default_model = str(models.get("fast_code", "qwen2.5-coder:7b"))
        requested_model = str(raw.get("model", default_model))
        model = requested_model
        model_fallback = False
        if available_models is not None and requested_model not in available_models:
            if default_model in available_models:
                model = default_model
                model_fallback = model != requested_model

        role = str(raw.get("role", canonical.removeprefix("qwen-")))
        return OllamaSubagentProfile(
            name=canonical,
            role=role,
            model=model,
            tools=self.READ_ONLY_TOOLS,
            max_steps=max(1, min(int(raw.get("max_steps", 3)), 8)),
            max_tool_calls=max(1, min(int(raw.get("max_tool_calls", 6)), 16)),
            max_tokens=max(64, min(int(raw.get("max_tokens", 800)), 2400)),
            temperature=max(0.0, min(float(raw.get("temperature", 0.05)), 1.0)),
            model_fallback=model_fallback,
        )

    @staticmethod
    def detect_language(task: str) -> str:
        text = str(task or "").lower()
        markers = {
            "cs": ("najdi", "navrhni", "chybu", "opravu", "soubor", "repozitář"),
            "sk": ("nájdi", "navrhni", "chybu", "súbor", "repozitár"),
            "de": ("finde", "fehler", "datei", "vorschlag", "warum"),
            "pl": ("znajdź", "błąd", "plik", "zaproponuj"),
            "es": ("encuentra", "error", "archivo", "propón"),
            "fr": ("trouve", "erreur", "fichier", "propose"),
            "en": ("find", "error", "file", "propose", "why"),
        }
        scores = {language: sum(marker in text for marker in terms) for language, terms in markers.items()}
        language, score = max(scores.items(), key=lambda item: item[1])
        return language if score else "und"

    def system_contract(self, profile: OllamaSubagentProfile, task: str) -> str:
        language = self.detect_language(task) if self.language == "match_input" else self.language
        return (
            f"You are {profile.name}, a local Ollama {profile.role} subagent inside Local AI Hub. "
            "ADVISORY_ONLY: never edit files, execute commands, create worktrees, or claim that a proposal was applied. "
            "Use Local AI Hub read-only tooling directly: preprocessed context, deterministic facts, code index, "
            "semantic symbols, code graph, repository search, RAG, evidence IDs, and bounded file slices. "
            "Start with the cheapest evidence path. Respond in the same language as TASK while preserving paths, "
            "identifiers, code, line numbers, errors, numbers, and uncertainty exactly. "
            f"Detected task language: {language}. Return compact structured output with profile={profile.name}, "
            "advisory_only=true."
        )
