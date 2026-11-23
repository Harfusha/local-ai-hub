"""Generate DPO (Direct Preference Optimization) paired dataset for file card training.

Creates (prompt, chosen, rejected) triplets where:
- chosen: 100% grounded file card with strict verbatim source code quotes
- rejected: perturbed card exhibiting hallucinations or subtle code antipatterns
  (invented symbols, unverified quotes, off-by-one errors, inverted logic, dropped facts)

Enables DPO / ORPO training to actively penalize model hallucinations and reasoning bugs.
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import re
from typing import Any

from .manifest import _read_jsonl


def _detect_language(source_text: str) -> str:
    """Detect programming language family from syntax tokens."""
    st = source_text[:2000]
    if "fn " in st or "impl " in st or "pub struct " in st or ("::" in st and "use " in st):
        return "rust"
    if "func " in st or "package " in st:
        return "go"
    if "<?php" in st or ("namespace " in st and "$" in st):
        return "php"
    if "namespace " in st or "public class " in st or "fun " in st or "suspend fun " in st:
        return "csharp_or_jvm"
    if "export " in st or "interface " in st or "const " in st or "=>" in st:
        return "typescript"
    return "python"


def _mutate_in_domain_symbol(symbol: str) -> str:
    """Universally synthesize plausible hallucinated symbol in any human or programming language."""
    if any(c.isupper() for c in symbol) and "_" not in symbol:
        return symbol + random.choice(["Helper", "Handler", "Proxy", "V2", "Internal", "Factory"])
    return symbol + random.choice(["_async", "_handler", "_v2", "_proxy", "_internal", "_helper"])


def _mutate_verbatim_quote(quote: str, source_text: str) -> str:
    """Subtly corrupt verbatim quote so it is no longer strictly grounded in source."""
    words = [w for w in re.findall(r"[A-Za-z0-9_\u00C0-\u017F]+", quote) if len(w) > 3]
    if words:
        target = random.choice(words)
        corrupted = re.sub(r"\b" + re.escape(target) + r"\b", target + "_unverified", quote, count=1)
        if corrupted not in source_text:
            return corrupted
    return quote + " /* unverified claim */"


def _inject_antipattern(quote: str) -> str:
    """Inject realistic semantic bugs into code quote (off-by-one, inverted condition, unhandled unwrap)."""
    # 1. Off-by-one boundary perturbation
    if "<" in quote and "<=" not in quote:
        return quote.replace("<", "<=", 1)
    if ">" in quote and ">=" not in quote:
        return quote.replace(">", ">=", 1)
    if " + 1" in quote:
        return quote.replace(" + 1", " - 1", 1)

    # 2. Inverted boolean condition
    if " == " in quote:
        return quote.replace(" == ", " != ", 1)
    if "!= " in quote:
        return quote.replace("!= ", "== ", 1)
    if " if " in quote and " if not " not in quote:
        return quote.replace(" if ", " if not ", 1)

    # 3. Risky unwrap / unchecked call
    if "Ok(" in quote:
        return quote.replace("Ok(", "Err(", 1)
    if ".map(" in quote:
        return quote.replace(".map(", ".unwrap().map(", 1)

    return quote + " // antipattern injected"


def create_rejected_card(chosen_card: dict[str, Any], source_text: str) -> dict[str, Any]:
    rejected = json.loads(json.dumps(chosen_card))
    perturbations = [
        "hallucinate_symbol",
        "corrupt_quote",
        "inject_antipattern",
        "drop_purpose",
        "hallucinate_dependency",
    ]
    chosen_perturbation = random.choice(perturbations)
    lang = _detect_language(source_text)

    # Universal in-domain mutation first; language-specific templates as fallback
    if chosen_perturbation == "hallucinate_symbol":
        symbols = rejected.get("symbols", [])
        if symbols:
            target_sym = random.choice(symbols)
            rejected["symbols"] = symbols + [_mutate_in_domain_symbol(target_sym)]
        else:
            polyglot_defaults = {
                "rust": "into_inner_unchecked",
                "go": "ServeHTTPWithContext",
                "typescript": "useMemoizedHandler",
                "csharp_or_jvm": "ResolveSessionHandlerAsync",
                "php": "handleIncomingPayload",
                "python": "get_internal_state_proxy",
            }
            rejected["symbols"] = [polyglot_defaults.get(lang, "process_unregistered_event")]

    elif chosen_perturbation == "corrupt_quote":
        evidence = rejected.get("evidence", [])
        if evidence and any(e.get("quote") for e in evidence):
            ev = random.choice([e for e in evidence if e.get("quote")])
            ev["quote"] = _mutate_verbatim_quote(ev["quote"], source_text)
        else:
            fallback_quotes = {
                "rust": "let mut guard = self.inner.lock().unwrap();",
                "go": "if err := s.listener.Close(); err != nil { return err }",
                "typescript": "const [state, setState] = useState<AsyncState>(initialState);",
                "csharp_or_jvm": "await _channel.Writer.WriteAsync(message, cancellationToken);",
                "php": "$this->connectionPool->releaseConnection($connectionId);",
                "python": "result = await asyncio.wait_for(task, timeout=self.timeout)",
            }
            rejected["evidence"] = [{
                "field": "purpose",
                "value": "Generic file",
                "quote": fallback_quotes.get(lang, "unsupported source claim not present in file"),
            }]

    elif chosen_perturbation == "inject_antipattern":
        evidence = rejected.get("evidence", [])
        if evidence and any(e.get("quote") for e in evidence):
            ev = random.choice([e for e in evidence if e.get("quote")])
            ev["quote"] = _inject_antipattern(ev["quote"])
        else:
            rejected["purpose"] = rejected.get("purpose", "") + " with known race conditions and missing bounds checks"

    elif chosen_perturbation == "drop_purpose":
        rejected["purpose"] = "source module"

    elif chosen_perturbation == "hallucinate_dependency":
        deps = rejected.get("dependencies", [])
        if deps:
            target_dep = random.choice(deps)
            mutated_dep = target_dep + ("_ext" if "::" in target_dep or "." in target_dep else "-internal")
            rejected["dependencies"] = deps + [mutated_dep]
        else:
            fallback_deps = {
                "rust": "tokio::sync::mpsc",
                "go": "golang.org/x/sync/errgroup",
                "typescript": "@tanstack/react-query",
                "csharp_or_jvm": "System.Threading.Channels",
                "php": "Symfony\\Component\\HttpFoundation\\Response",
                "python": "urllib3.util.retry",
            }
            rejected["dependencies"] = [fallback_deps.get(lang, "external-unregistered-library")]

    return rejected


def generate_dpo_dataset(
    sft_train_path: Path,
    out_dpo_path: Path,
    max_pairs: int = 1500,
    seed: int = 20261110,
) -> int:
    random.seed(seed)
    rows = _read_jsonl(sft_train_path, split="train")
    dpo_rows: list[dict[str, Any]] = []

    for row in rows[:max_pairs]:
        msgs = row.get("messages", [])
        if len(msgs) < 3:
            continue
        system_msg = msgs[0]["content"]
        user_msg = msgs[1]["content"]
        assistant_content = msgs[2]["content"]

        try:
            chosen_card = json.loads(assistant_content)
        except Exception:
            continue

        # Extract source excerpt from user message
        source_marker = "CURRENT SOURCE (authority):\n"
        source_text = user_msg.partition(source_marker)[2]

        rejected_card = create_rejected_card(chosen_card, source_text)

        dpo_rows.append({
            "id": row["id"],
            "group_id": row["group_id"],
            "source_sha256": row["source_sha256"],
            "system": system_msg,
            "prompt": user_msg,
            "chosen": json.dumps(chosen_card, ensure_ascii=False, separators=(",", ":")),
            "rejected": json.dumps(rejected_card, ensure_ascii=False, separators=(",", ":")),
            "provenance": row.get("provenance", {}),
        })

    out_dpo_path.parent.mkdir(parents=True, exist_ok=True)
    with out_dpo_path.open("w", encoding="utf-8") as f:
        for r in dpo_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Generated {len(dpo_rows)} DPO preference pairs to {out_dpo_path}")
    return len(dpo_rows)


if __name__ == "__main__":
    train_src = Path("state/experiments/model-training/data/preprocess-gold-massive-train.jsonl")
    dpo_target = Path("state/experiments/model-training/data/preprocess-gold-massive-dpo.jsonl")
    generate_dpo_dataset(train_src, dpo_target)
