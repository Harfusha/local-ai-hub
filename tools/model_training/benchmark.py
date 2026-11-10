from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import gc
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .manifest import _read_jsonl, load_run_manifest, validate_dataset_pair
from .runtime import resolve_runtime
from .scoring import score_prediction


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_ids(tokenizer: Any, messages: list[dict[str, str]]) -> list[int]:
    value = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    if isinstance(value, dict):
        value = value["input_ids"]
    elif hasattr(value, "input_ids"):
        value = value.input_ids
    if hasattr(value, "tolist"):
        value = value.tolist()
    if len(value) and isinstance(value[0], list):
        value = value[0]
    return [int(item) for item in value]


def _generate_one(
    model: Any, tokenizer: Any, row: dict[str, Any], *, adapter_enabled: bool,
    device: str, max_new_tokens: int,
) -> dict[str, Any]:
    import torch

    input_ids = _input_ids(tokenizer, row["messages"])
    input_tensor = torch.tensor([input_ids], dtype=torch.long, device=device)
    adapter_context = nullcontext() if adapter_enabled or not hasattr(model, "disable_adapter") else model.disable_adapter()
    if device == "cuda":
        torch.cuda.synchronize()
    started = time.perf_counter()
    with adapter_context, torch.inference_mode():
        generated = model.generate(
            input_ids=input_tensor,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            num_beams=1,
            use_cache=True,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )[0]
    if device == "cuda":
        torch.cuda.synchronize()
    output_ids = generated[len(input_ids) :]
    text = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
    output_length = len(output_ids)
    last_token = int(output_ids[-1]) if output_length else None
    result = {
        "input_tokens": len(input_ids),
        "output_tokens": output_length,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "truncated": output_length >= max_new_tokens or (last_token is not None and last_token != tokenizer.eos_token_id),
        "raw_output": text,
    }
    result.update(score_prediction(text, row, row["_output_schema"]))
    return result


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"runs": 0}
    latencies = sorted(float(row["latency_ms"]) for row in rows)
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1)
    exact_rows = [row for row in rows if row["exact_match"] is not None]
    fact_rows = [row for row in rows if row["required_fact_recall"] is not None]
    return {
        "runs": len(rows),
        "schema_pass_rate": round(sum(bool(row["schema_pass"]) for row in rows) / len(rows), 4),
        "exact_match_rate": round(sum(bool(row["exact_match"]) for row in exact_rows) / len(exact_rows), 4) if exact_rows else None,
        "mean_required_fact_recall": round(statistics.mean(float(row["required_fact_recall"]) for row in fact_rows), 4) if fact_rows else None,
        "forbidden_claim_hits": sum(int(row["forbidden_claim_count"]) for row in rows),
        "mean_input_tokens": round(statistics.mean(int(row["input_tokens"]) for row in rows), 2),
        "mean_output_tokens": round(statistics.mean(int(row["output_tokens"]) for row in rows), 2),
        "mean_latency_ms": round(statistics.mean(latencies), 2),
        "median_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(latencies[p95_index], 2),
        "truncations": sum(bool(row["truncated"]) for row in rows),
    }


def benchmark_from_manifest(
    manifest_path: Path | str,
    *,
    adapter_path: Path | str | None,
    output_path: Path | str,
    baseline_report_path: Path | str | None = None,
    allow_model_download: bool = False,
) -> dict[str, Any]:
    config = load_run_manifest(manifest_path)
    if config.get("backend") == "laya":
        from .laya_backend import benchmark_laya_from_config

        return benchmark_laya_from_config(
            config,
            checkpoint_path=adapter_path,
            output_path=output_path,
            baseline_report_path=baseline_report_path,
            allow_model_download=allow_model_download,
        )
    dataset_summary = validate_dataset_pair(config["train_file"], config["evaluation_file"])
    evaluation_rows = _read_jsonl(Path(config["evaluation_file"]), split="evaluation")
    training = config.get("training", {})
    benchmark_config = config.get("benchmark", {})
    runtime = resolve_runtime(device=str(benchmark_config.get("device", training.get("device", "cuda"))))
    quantization = str(training.get("quantization", "none"))
    if quantization not in {"none", "4bit"}:
        raise ValueError("training.quantization must be none or 4bit")
    if quantization == "4bit" and runtime["device"] != "cuda":
        raise ValueError("4bit QLoRA benchmark requires CUDA")
    adapter_dir = Path(adapter_path).resolve() if adapter_path is not None else None
    if adapter_dir is not None and not adapter_dir.is_dir():
        raise ValueError(f"adapter directory does not exist: {adapter_dir}")
    output = Path(output_path)
    if output.exists():
        raise ValueError(f"benchmark output already exists: {output}")

    try:
        import torch
        import peft
        import transformers
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("benchmark needs torch, transformers, peft, and accelerate") from exc

    base_model = str(config["base_model"])
    local_files_only = not allow_model_download
    tokenizer = AutoTokenizer.from_pretrained(
        base_model, local_files_only=local_files_only, revision=config.get("revision"), trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    load_options: dict[str, Any] = {}
    if quantization == "4bit":
        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError("4bit QLoRA benchmark needs bitsandbytes and current transformers") from exc
        load_options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=runtime["dtype"],
        )
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        local_files_only=local_files_only,
        revision=config.get("revision"),
        trust_remote_code=False,
        dtype=runtime["dtype"],
        device_map={"": 0 if runtime["device"] == "cuda" else "cpu"},
        attn_implementation=runtime["attention"],
        use_safetensors=True,
        **load_options,
    )
    if adapter_dir is not None:
        model = PeftModel.from_pretrained(model, adapter_dir, is_trainable=False)
    model.eval()
    schema = config["output_schema"]
    for row in evaluation_rows:
        row["_output_schema"] = schema
    max_new_tokens = int(benchmark_config.get("max_new_tokens", 320))
    warmup_runs = int(benchmark_config.get("warmup_runs", 1))
    if not (1 <= max_new_tokens <= 8192 and 0 <= warmup_runs <= 5):
        raise ValueError("benchmark max_new_tokens or warmup_runs outside safe bounds")
    if warmup_runs and evaluation_rows:
        for enabled in ((False, True) if adapter_dir is not None else (False,)):
            for _ in range(warmup_runs):
                _generate_one(
                    model, tokenizer, evaluation_rows[0], adapter_enabled=enabled,
                    device=runtime["device"], max_new_tokens=max_new_tokens,
                )
    base_rows: list[dict[str, Any]] = []
    adapter_rows: list[dict[str, Any]] = []
    for case in evaluation_rows:
        base_result = _generate_one(
            model, tokenizer, case, adapter_enabled=False, device=runtime["device"], max_new_tokens=max_new_tokens
        )
        base_rows.append({"id": case["id"], "group_id": case["group_id"], **base_result})
        if adapter_dir is not None:
            adapter_result = _generate_one(
                model, tokenizer, case, adapter_enabled=True, device=runtime["device"], max_new_tokens=max_new_tokens
            )
            adapter_rows.append({"id": case["id"], "group_id": case["group_id"], **adapter_result})
            print(json.dumps({
                "id": case["id"],
                "base_schema": base_result["schema_pass"],
                "adapter_schema": adapter_result["schema_pass"],
                "base_latency_ms": base_result["latency_ms"],
                "adapter_latency_ms": adapter_result["latency_ms"],
            }), flush=True)
        else:
            print(json.dumps({"id": case["id"], "base_schema": base_result["schema_pass"], "base_latency_ms": base_result["latency_ms"]}), flush=True)
    base_summary = _summary(base_rows)
    adapter_summary = _summary(adapter_rows) if adapter_dir is not None else None
    delta = None
    if adapter_summary is not None:
        delta = {
            "schema_pass_rate": round(adapter_summary["schema_pass_rate"] - base_summary["schema_pass_rate"], 4),
            "exact_match_rate": round(adapter_summary["exact_match_rate"] - base_summary["exact_match_rate"], 4)
            if adapter_summary["exact_match_rate"] is not None and base_summary["exact_match_rate"] is not None else None,
            "mean_required_fact_recall": round(adapter_summary["mean_required_fact_recall"] - base_summary["mean_required_fact_recall"], 4)
            if adapter_summary["mean_required_fact_recall"] is not None and base_summary["mean_required_fact_recall"] is not None else None,
            "mean_latency_ms": round(adapter_summary["mean_latency_ms"] - base_summary["mean_latency_ms"], 2),
            "latency_speedup": round(base_summary["mean_latency_ms"] / adapter_summary["mean_latency_ms"], 4)
            if adapter_summary["mean_latency_ms"] else None,
        }
    try:
        gpu_name = torch.cuda.get_device_name(0) if runtime["device"] == "cuda" else None
    except Exception:
        gpu_name = None
    result = {
        "schema": "local-ai-hub-paired-model-benchmark-v1",
        "task": config["name"],
        "task_type": config["task_type"],
        "base_model": base_model,
        "base_revision": config.get("revision"),
        "resolved_model_revision": getattr(model.config, "_commit_hash", None),
        "run_manifest_sha256": _sha256(Path(config["_manifest_path"])),
        "phase": "before_training" if adapter_dir is None else "paired_after_training",
        "adapter_path": str(adapter_dir) if adapter_dir is not None else None,
        "evaluation_file": str(Path(config["evaluation_file"]).resolve()),
        "evaluation_sha256": _sha256(Path(config["evaluation_file"])),
        "dataset": dataset_summary,
        "runtime": {key: value for key, value in runtime.items() if key != "dtype"},
        "quantization": quantization,
        "gpu": gpu_name,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "peft": peft.__version__,
        "generation": {"do_sample": False, "num_beams": 1, "max_new_tokens": max_new_tokens, "warmup_runs": warmup_runs},
        "summary": {"base": base_summary, "adapter": adapter_summary, "delta_adapter_minus_base": delta},
        "manual_source_review_required": True,
        "rows": {"base": base_rows, "adapter": adapter_rows if adapter_dir is not None else None},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    del model, tokenizer
    gc.collect()
    if runtime["device"] == "cuda":
        torch.cuda.empty_cache()
    return result
