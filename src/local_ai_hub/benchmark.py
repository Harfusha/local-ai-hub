from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import math
import time
from pathlib import Path
from typing import Any


class HardwareBenchmarkRunner:
    """Hardware capability and inference latency benchmark harness.

    Measures Time-To-First-Token (TTFT), token generation throughput (TPS),
    VRAM footprint, and computes composite hardware performance ratings.
    """

    def __init__(
        self,
        benchmarks_path: Path | str,
        runtime: Any = None,
        vram_balancer: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.benchmarks_path = Path(benchmarks_path)
        self.runtime = runtime
        self.vram_balancer = vram_balancer
        self.config = config or {}

    def _default_model(self) -> str:
        return str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))

    def run(
        self,
        model: str = "",
        prompt: str = "def fibonacci(n: int) -> int:\n    \"\"\"Compute fibonacci recursively.\"\"\"\n",
        num_tokens: int = 40,
    ) -> dict[str, Any]:
        target_model = model.strip() or self._default_model()
        if not self.runtime:
            return {"success": False, "error": "Runtime not configured for benchmark"}

        initial_vram = {}
        if self.vram_balancer and hasattr(self.vram_balancer, "sample_vram"):
            try:
                initial_vram = self.vram_balancer.sample_vram()
            except Exception:
                pass

        t0 = time.perf_counter()
        first_token_time: float | None = None
        tokens_count = 0
        response_text = ""
        thinking_chars = 0
        generation_duration_ns: int | None = None
        streaming = False

        try:
            if callable(getattr(self.runtime, "generate_stream", None)):
                streaming = True
                # Qwen reasoning models can spend the whole small benchmark budget
                # in a hidden thinking stream.  Hardware routing needs visible
                # generation latency, so explicitly disable thinking here.
                for chunk in self.runtime.generate_stream(
                    target_model,
                    prompt,
                    options={"num_predict": num_tokens, "think": False},
                ):
                    if isinstance(chunk, dict) and chunk.get("error"):
                        return {"success": False, "model": target_model, "error": str(chunk["error"])}
                    now = time.perf_counter()
                    if first_token_time is None:
                        first_token_time = now
                    if isinstance(chunk, dict):
                        visible = str(chunk.get("response", chunk.get("text", "")) or "")
                        response_text += visible
                        thinking_chars += len(str(chunk.get("thinking", "") or ""))
                        if visible:
                            tokens_count += 1
                    else:
                        visible = str(chunk or "")
                        response_text += visible
                        if visible:
                            tokens_count += 1
                if not response_text and thinking_chars:
                    return {
                        "success": False,
                        "model": target_model,
                        "error": "benchmark produced thinking-only output",
                        "measurement_warning": "thinking_only_output",
                        "thinking_chars": thinking_chars,
                    }
            elif callable(getattr(self.runtime, "generate", None)):
                res = self.runtime.generate(
                    target_model,
                    prompt,
                    options={"num_predict": max(1, int(num_tokens)), "think": False},
                )
                if not isinstance(res, dict):
                    return {"success": False, "model": target_model, "error": "benchmark runtime returned a non-object response"}
                if res.get("error"):
                    return {"success": False, "model": target_model, "error": str(res["error"])}
                response_text = str(res.get("response", res.get("text", "")) or "")
                thinking_chars = len(str(res.get("thinking", "") or ""))
                tokens_count = int(res.get("eval_count", 0) or 0)
                if tokens_count <= 0:
                    tokens_count = len(response_text.split())
                generation_duration_ns = int(res.get("eval_duration", 0) or 0) or None
                if not response_text:
                    return {
                        "success": False,
                        "model": target_model,
                        "error": "benchmark produced no visible output",
                        "measurement_warning": "thinking_only_output" if thinking_chars else "empty_visible_output",
                        "thinking_chars": thinking_chars,
                    }
            else:
                return {"success": False, "error": "Runtime does not support generation"}
        except Exception as exc:
            return {"success": False, "error": f"Benchmark generation failed: {exc}", "model": target_model}

        if not response_text:
            return {
                "success": False,
                "model": target_model,
                "error": "benchmark produced no visible output",
                "measurement_warning": "thinking_only_output" if thinking_chars else "empty_visible_output",
                "thinking_chars": thinking_chars,
            }

        t_end = time.perf_counter()

        ttft_ms = round((first_token_time - t0) * 1000, 2) if first_token_time else round((t_end - t0) * 1000, 2)
        gen_duration = max(0.001, (generation_duration_ns / 1e9) if generation_duration_ns else t_end - (first_token_time or t0) if streaming else t_end - t0)
        tps = round(tokens_count / gen_duration, 2) if tokens_count > 0 else 0.0

        # Composite score 0..100 based on TTFT and TPS
        score: float | None
        measurement_warning = ""
        if tokens_count < 2:
            score = None
            measurement_warning = "insufficient_output_tokens"
        else:
            # Use a smooth score: the previous hard 500 ms TTFT cutoff made
            # every realistic Windows model score the same 60/100 once TTFT was
            # above the cutoff.  This keeps 0..100 bounded while preserving
            # meaningful separation for routing and benchmark history.
            tps_part = min(60.0, (tps / 100.0) * 60.0)
            ttft_part = min(40.0, 40.0 * math.exp(-max(0.0, ttft_ms) / 3000.0))
            score = round(tps_part + ttft_part, 1)

        final_vram = {}
        if self.vram_balancer and hasattr(self.vram_balancer, "sample_vram"):
            try:
                final_vram = self.vram_balancer.sample_vram()
            except Exception:
                pass

        record: dict[str, Any] = {
            "timestamp": time.time(),
            "model": target_model,
            "tokens_generated": tokens_count,
            "ttft_ms": ttft_ms,
            "tokens_per_second": tps,
            "hardware_score": score,
            "generation_duration_ms": round(gen_duration * 1000, 2),
            "output_chars": len(response_text),
            "streaming": streaming,
            "initial_vram": initial_vram,
            "final_vram": final_vram,
        }
        if measurement_warning:
            record["measurement_warning"] = measurement_warning

        self._persist_record(record)
        return {"success": True, **record}

    def _persist_record(self, record: dict[str, Any]) -> None:
        try:
            self.benchmarks_path.parent.mkdir(parents=True, exist_ok=True)
            history: list[dict[str, Any]] = []
            if self.benchmarks_path.exists():
                try:
                    history = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
                    if not isinstance(history, list):
                        history = []
                except Exception:
                    history = []
            history.append(record)
            if len(history) > 50:
                history = history[-50:]
            self.benchmarks_path.write_text(json_dumps(history, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_latest_summary(self) -> dict[str, Any]:
        if not self.benchmarks_path.exists():
            return {"available": False}
        try:
            history = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
            if not history or not isinstance(history, list):
                return {"available": False}
            latest = history[-1]
            return {
                "available": True,
                "model": latest.get("model", ""),
                "ttft_ms": latest.get("ttft_ms", 0.0),
                "tokens_per_second": latest.get("tokens_per_second", 0.0),
                "hardware_score": latest.get("hardware_score", 0.0),
                "timestamp": latest.get("timestamp", 0.0),
            }
        except Exception:
            return {"available": False}

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self.benchmarks_path.exists():
            return []
        try:
            data = json.loads(self.benchmarks_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-limit:]
            return []
        except Exception:
            return []
