"""Reproducible synthetic benchmark of graph coverage (not model defect recall)."""
from __future__ import annotations

import argparse
import json
import random
import time
from typing import Any

from local_ai_hub.token_accounting import json_tokens
from local_ai_hub.verified_execution import execution_projection, execution_resume_summary


def run_benchmark(*, seed: int = 17, trials: int = 32, obligations: int = 128) -> dict[str, Any]:
    if not 1 <= trials <= 256 or not 4 <= obligations <= 512:
        raise ValueError("trials must be 1..256 and obligations 4..512")
    rng = random.Random(seed)
    metrics = {name: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
               for name in ("graph", "receipt_only")}
    full_tokens = compact_tokens = 0
    elapsed = 0.0
    for _ in range(trials):
        criteria = tuple(f"review resource {index:04d}" for index in range(obligations))
        parents: dict[str, list[str]] = {}
        for index, name in enumerate(criteria):
            parents[name] = rng.sample(criteria[:index], k=min(index, rng.randrange(4)))
        config = {"units": {name: {"depends_on": deps} for name, deps in parents.items()}}
        missing = set(rng.sample(criteria, k=max(1, obligations // 16)))
        observed = {name: float(index + 1) for index, name in enumerate(criteria)}
        for name in rng.sample(criteria, k=max(1, obligations // 20)):
            observed[name] += obligations
        # Independent reference oracle walks each prerequisite chain recursively;
        # memoization bounds its cost, and generated graphs are acyclic.
        oracle: dict[str, bool] = {}

        def valid(name: str) -> bool:
            if name not in oracle:
                oracle[name] = name not in missing and all(
                    valid(dep) and observed[name] >= observed[dep] for dep in parents[name]
                )
            return oracle[name]

        expected = {name for name in criteria if not valid(name)}
        satisfied = tuple(name for name in criteria if name not in missing)
        started = time.perf_counter()
        projection = execution_projection(
            criteria, config, satisfied=satisfied, unsatisfied=tuple(sorted(missing)), stale=(),
            receipt_ids={name: name for name in satisfied}, receipt_gate_complete=not missing,
            receipt_observed_at=observed, include_verified_criteria=True,
        )
        elapsed += time.perf_counter() - started
        predictions = {"graph": set(criteria) - set(projection.pop("verified_criteria")),
                       "receipt_only": missing}
        for name, predicted in predictions.items():
            metrics[name]["true_positive"] += len(expected & predicted)
            metrics[name]["false_positive"] += len(predicted - expected)
            metrics[name]["false_negative"] += len(expected - predicted)
        full_tokens += json_tokens({"criteria": criteria, "units": config["units"]})
        compact_tokens += json_tokens(execution_resume_summary(projection))
    for counts in metrics.values():
        tp, fp, fn = (counts[key] for key in ("true_positive", "false_positive", "false_negative"))
        counts["precision_ppm"] = round(1_000_000 * tp / (tp + fp)) if tp + fp else 0
        counts["recall_ppm"] = round(1_000_000 * tp / (tp + fn)) if tp + fn else 0
    return {
        "benchmark": "synthetic_graph_invalidity_v1", "seed": seed, "trials": trials,
        "obligations_per_trial": obligations, "metrics": metrics,
        "graph_projection_seconds": round(elapsed, 6),
        "full_contract_estimated_tokens": full_tokens,
        "compact_resume_estimated_tokens": compact_tokens,
        "limitations": "Synthetic receipt invalidity only; not semantic defect recall, end-to-end agent tokens or runtime.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--trials", type=int, default=32)
    parser.add_argument("--obligations", type=int, default=128)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(seed=args.seed, trials=args.trials, obligations=args.obligations),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
