"""Interactive, repeatable choices for the deterministic setup command."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

PREFERENCE_VERSION = 1
PROFILES = ("auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max")
BOOLEAN_CHOICES = (
    "pull_ollama_models",
    "download_hf_models",
    "local_nlp",
    "openvino",
    "laya_runtime",
    "ast_index",
    "performance",
    "profiling",
    "serena",
    "token_economy",
    "agent_config",
    "service",
    "companion_skills",
    "agent_codex",
    "agent_claude",
    "agent_gemini",
    "agent_cursor",
    "agent_windsurf",
    "agent_copilot",
)
AGENT_CHOICE_KEYS = {
    "agent_codex": "codex",
    "agent_claude": "claude",
    "agent_gemini": "gemini",
    "agent_cursor": "cursor",
    "agent_windsurf": "windsurf",
    "agent_copilot": "copilot",
}
AGENT_COMPONENTS = ("mcp", "skills", "instructions")
AGENT_COMPONENT_CHOICE_KEYS = {
    f"agent_{agent}_{component}": (agent, component)
    for agent in AGENT_CHOICE_KEYS.values()
    for component in AGENT_COMPONENTS
}
BOOLEAN_CHOICES = (*BOOLEAN_CHOICES, *AGENT_COMPONENT_CHOICE_KEYS)


def preferences_path(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)
    if os.name == "nt":
        base = Path(env.get("LOCALAPPDATA") or env.get("APPDATA") or user_home)
        return base / "Local AI Hub" / "installer-preferences.json"
    return user_home / ".config" / "local-ai-hub" / "installer-preferences.json"


def _valid_preferences(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("version") != PREFERENCE_VERSION:
        return {}
    choices = data.get("choices")
    if not isinstance(choices, dict):
        return {}
    result: dict[str, Any] = {}
    profile = choices.get("profile")
    if profile in PROFILES:
        result["profile"] = profile
    for key in BOOLEAN_CHOICES:
        if type(choices.get(key)) is bool:
            result[key] = choices[key]
    return result


def load_preferences(path: Path | None = None) -> dict[str, Any]:
    target = preferences_path() if path is None else Path(path)
    try:
        if target.is_symlink() or not target.is_file():
            return {}
        return _valid_preferences(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return {}


def save_preferences(choices: dict[str, Any], path: Path | None = None) -> None:
    target = preferences_path() if path is None else Path(path)
    selected = _valid_preferences({"version": PREFERENCE_VERSION, "choices": choices})
    if not selected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise OSError(f"installer preferences path is a symlink: {target}")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump({"version": PREFERENCE_VERSION, "choices": selected}, stream, indent=2)
            stream.write("\n")
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def defaults_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    setup = cfg.get("setup", {})
    features = cfg.get("features", {})
    models = cfg.get("models", {})
    server = cfg.get("server", {})
    ollama = cfg.get("ollama", {})
    llama_cpp = cfg.get("llama_cpp", {})
    code_intelligence = cfg.get("code_intelligence", {})
    laya = cfg.get("laya", {})
    laya_runtime = laya.get("runtime", {}) if isinstance(laya, dict) else {}
    agents = cfg.get("agents", {})
    tool_policy = cfg.get("tool_policy", {})
    hardware = cfg.get("hardware", {})
    detected = cfg.get("_hardware", {})
    profile = str(detected.get("profile") or hardware.get("profile") or "auto").lower()
    if profile not in PROFILES:
        profile = "auto"
    return {
        "profile": profile,
        "pull_ollama_models": bool(
            features.get("pull_models_during_setup", True)
            and isinstance(ollama, dict) and ollama.get("enabled") is True
            and isinstance(server, dict) and server.get("auto_start_ollama") is True
            and isinstance(llama_cpp, dict) and llama_cpp.get("fallback_to_ollama") is True
        ),
        "download_hf_models": bool(
            isinstance(models, dict) and models.get("allow_hf_downloads", False) is True
        ),
        "local_nlp": bool(features.get("install_local_nlp_dependencies", True)),
        "openvino": bool(features.get("install_openvino_dependencies", True)),
        "laya_runtime": bool(
            isinstance(laya_runtime, dict) and str(laya_runtime.get("checkpoint_path", "")).strip()
        ),
        "ast_index": True,
        "performance": True,
        "profiling": False,
        "serena": bool(setup.get("install_optional_tools", True) and code_intelligence.get("serena_enabled", True)),
        "token_economy": True,
        "agent_config": bool(setup.get("install_agent_configs", True)),
        "service": bool(setup.get("install_service", True) and cfg.get("headless", {}).get("enabled", True)),
        "companion_skills": bool(setup.get("install_companion_skills", True)),
        **{
            choice: bool(agents.get(agent, True))
            for choice, agent in AGENT_CHOICE_KEYS.items()
        },
        **{
            f"agent_{agent}_{component}": bool(
                agents.get(agent, True)
                and (tool_policy.get("install_global_instructions", True) if component == "instructions" else True)
            )
            for agent in AGENT_CHOICE_KEYS.values()
            for component in AGENT_COMPONENTS
        },
    }


def _ask_yes_no(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{label} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes", "ano", "a"}:
            return True
        if answer in {"n", "no", "ne"}:
            return False
        print("Zadej ano nebo ne.")


def _ask_profile(default: str) -> str:
    print("Hardwarový profil:")
    for index, profile in enumerate(PROFILES, 1):
        marker = " (doporučeno)" if profile == default else ""
        print(f"  {index}. {profile}{marker}")
    while True:
        answer = input(f"Volba [{PROFILES.index(default) + 1}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(PROFILES):
            return PROFILES[int(answer) - 1]
        if answer.lower() in PROFILES:
            return answer.lower()
        print("Zadej číslo volby nebo název profilu.")


def collect_choices(cfg: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    configured_defaults = defaults_from_config(cfg)
    print("\nLocal AI Hub — instalace / aktualizace")
    if saved and _ask_yes_no("Použít uložené volby", True):
        return {**configured_defaults, **saved}
    choices = dict(configured_defaults)
    choices["profile"] = _ask_profile(str(configured_defaults["profile"]))
    prompts = {
        "pull_ollama_models": "Stáhnout všechny nakonfigurované modely Ollama (jen když je Ollama zapnutá)",
        "download_hf_models": "Stáhnout chybějící Hugging Face modely pro embeddingy a reranker",
        "local_nlp": "Instalovat lokální NLP závislosti pro embeddingy a reranker",
        "openvino": "Povolit automatickou instalaci OpenVINO při potřebě Intel akcelerace",
        "laya_runtime": "Instalovat volitelné runtime balíčky Laya",
        "ast_index": "Instalovat Tree-sitter jazykové balíčky pro širší AST podporu",
        "performance": "Instalovat volitelné výkonové balíčky a Cython",
        "profiling": "Instalovat diagnostické nástroje py-spy a Scalene",
        "serena": "Instalovat volitelný Serena nástroj",
        "token_economy": "Instalovat nástroje Token Economy",
        "agent_config": "Nastavit MCP, skills a instrukce pro vybrané agenty",
        "service": "Nainstalovat službu spouštěnou při přihlášení",
        "companion_skills": "Instalovat doprovodné skills a podporované Superpowers součásti",
        "agent_codex": "Nastavit Codex",
        "agent_claude": "Nastavit Claude Code",
        "agent_gemini": "Nastavit Gemini CLI",
        "agent_cursor": "Nastavit Cursor",
        "agent_windsurf": "Nastavit Windsurf",
        "agent_copilot": "Nastavit VS Code / Copilot",
    }
    prompts.update({
        key: f"{agent}: nastavit {component}"
        for key, (agent, component) in AGENT_COMPONENT_CHOICE_KEYS.items()
    })
    for key in BOOLEAN_CHOICES:
        if key.startswith("agent_") and not choices.get("agent_config", True):
            continue
        if key in AGENT_COMPONENT_CHOICE_KEYS:
            agent, _component = AGENT_COMPONENT_CHOICE_KEYS[key]
            if not choices.get(f"agent_{agent}", False):
                continue
        choices[key] = _ask_yes_no(prompts[key], bool(configured_defaults[key]))
    if not choices.get("agent_config", True):
        for key in (*AGENT_CHOICE_KEYS, *AGENT_COMPONENT_CHOICE_KEYS):
            if key in saved:
                choices[key] = saved[key]
    return choices


def apply_choices(args: Any, cfg: dict[str, Any], choices: dict[str, Any]) -> None:
    if args.profile is None:
        args.profile = choices.get("profile")
    flag_choices = {
        "skip_model_pull": "pull_ollama_models",
        "skip_tools": "serena",
        "skip_token_economy": "token_economy",
        "skip_agent_config": "agent_config",
        "skip_service": "service",
        "skip_companion_skills": "companion_skills",
        "skip_laya_runtime": "laya_runtime",
        "skip_ast_index": "ast_index",
        "skip_performance": "performance",
        "skip_profiling": "profiling",
    }
    for arg_name, choice_name in flag_choices.items():
        explicit_value = getattr(args, arg_name)
        if explicit_value is None:
            setattr(args, arg_name, not bool(choices.get(choice_name, True)))
        else:
            choices[choice_name] = not bool(explicit_value)
    features = cfg.setdefault("features", {})
    models = cfg.setdefault("models", {})
    setup = cfg.setdefault("setup", {})
    code_intelligence = cfg.setdefault("code_intelligence", {})
    agents = cfg.setdefault("agents", {})
    tool_policy = cfg.setdefault("tool_policy", {})
    if "pull_ollama_models" in choices:
        features["pull_models_during_setup"] = bool(choices["pull_ollama_models"])
    if "download_hf_models" in choices:
        models["allow_hf_downloads"] = bool(choices["download_hf_models"])
    if "local_nlp" in choices:
        features["install_local_nlp_dependencies"] = bool(choices["local_nlp"])
    if "openvino" in choices:
        features["install_openvino_dependencies"] = bool(choices["openvino"])
    if "serena" in choices:
        setup["install_optional_tools"] = bool(choices["serena"])
        code_intelligence["serena_enabled"] = bool(choices["serena"])
    if "agent_config" in choices:
        setup["install_agent_configs"] = bool(choices["agent_config"])
    for choice, agent in AGENT_CHOICE_KEYS.items():
        if choice in choices:
            selected = bool(choices[choice]) and bool(choices.get("agent_config", True))
            has_components = any(
                bool(choices.get(f"agent_{agent}_{component}", True))
                for component in AGENT_COMPONENTS
            )
            agents[agent] = selected and has_components
    if any(f"agent_{agent}_instructions" in choices for agent in AGENT_CHOICE_KEYS.values()):
        tool_policy["install_global_instructions"] = any(
            bool(choices.get(f"agent_{agent}_instructions", False))
            for agent in AGENT_CHOICE_KEYS.values()
        )
    if "service" in choices:
        setup["install_service"] = bool(choices["service"])
    if "companion_skills" in choices:
        setup["install_companion_skills"] = bool(choices["companion_skills"])


def configure(args: Any, cfg: dict[str, Any], install_dir: Path, *, argv: list[str]) -> dict[str, Any]:
    """Load remembered choices, optionally prompt, then apply explicit CLI overrides."""
    saved = load_preferences()
    explicit_flags = {
        "--profile", "--skip-model-pull", "--skip-tools", "--skip-agent-config",
        "--skip-service", "--skip-ollama-install", "--skip-token-economy",
        "--skip-companion-skills", "--skip-local-nlp-preload", "--skip-laya-runtime",
        "--skip-ast-index", "--skip-performance", "--skip-profiling",
    }
    explicit = any(item.split("=", 1)[0] in explicit_flags for item in argv)
    interactive = args.interactive is True or (
        args.interactive is None and not explicit and os.isatty(0)
    )
    if args.non_interactive:
        interactive = False
    if interactive:
        choices = collect_choices(cfg, saved)
        save_preferences(choices)
    else:
        choices = {**defaults_from_config(cfg), **saved}
    if interactive and install_dir.exists() and not args.full_reinstall:
        args.full_reinstall = _ask_yes_no("Provést úplnou reinstalaci a smazat data Hubu", False)
    apply_choices(args, cfg, choices)
    return choices
