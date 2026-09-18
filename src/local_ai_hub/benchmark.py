from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
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

        try:
            if hasattr(self.runtime, "generate_stream"):
                for _chunk in self.runtime.generate_stream(target_model, prompt, options={"num_predict": num_tokens}):
                    now = time.perf_counter()
                    if first_token_time is None:
                        first_token_time = now
                    tokens_count += 1
            elif hasattr(self.runtime, "generate"):
                res = self.runtime.generate(target_model, prompt, max_tokens=num_tokens)
                first_token_time = time.perf_counter()
                text = res.get("text", "")
                tokens_count = max(1, len(text.split()))
            else:
                return {"success": False, "error": "Runtime does not support generation"}
        except Exception as exc:
            return {"success": False, "error": f"Benchmark generation failed: {exc}", "model": target_model}

        t_end = time.perf_counter()

        ttft_ms = round((first_token_time - t0) * 1000, 2) if first_token_time else round((t_end - t0) * 1000, 2)
        gen_duration = max(0.001, t_end - (first_token_time or t0))
        tps = round(tokens_count / gen_duration, 2) if tokens_count > 0 else 0.0

        # Composite score 0..100 based on TTFT and TPS
        tps_part = min(60.0, (tps / 50.0) * 60.0)
        ttft_part = min(40.0, max(0.0, (500.0 - ttft_ms) / 500.0) * 40.0)
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
            "initial_vram": initial_vram,
            "final_vram": final_vram,
        }

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
