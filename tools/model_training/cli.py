from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .benchmark import benchmark_from_manifest
from .dataset import split_dataset
from .manifest import load_run_manifest, validate_dataset_pair
from .run_matrix import load_matrix_manifest, run_matrix
from .teacher_cards import generate_cards, load_roots
from .train import train_from_manifest


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Local, opt-in model fine-tuning and paired benchmark scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one run or matrix manifest and datasets")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--matrix", action="store_true")

    collect = subparsers.add_parser("collect-cards", help="generate semantic cards through a local Ollama teacher")
    collect.add_argument("--roots", required=True, type=Path)
    collect.add_argument("--output", required=True, type=Path)
    collect.add_argument("--model", default="qwen2.5-coder:3b")
    collect.add_argument("--endpoint", default="http://127.0.0.1:11434/api/generate")
    collect.add_argument("--resume", action="store_true")
    collect.add_argument("--limit", type=int)
    collect.add_argument("--max-bytes", type=int, default=180_000)
    collect.add_argument("--max-chars", type=int, default=16_000)

    split = subparsers.add_parser("split", help="create a deterministic group-held-out split")
    split.add_argument("--input", required=True, type=Path)
    split.add_argument("--train", required=True, type=Path)
    split.add_argument("--evaluation", required=True, type=Path)
    split.add_argument("--evaluation-fraction", type=float, default=0.2)
    split.add_argument("--seed", type=int, default=20261110)

    matrix = subparsers.add_parser("run-matrix", help="benchmark before, train, then benchmark each model")
    matrix.add_argument("--manifest", required=True, type=Path)
    matrix.add_argument("--allow-model-download", action="store_true")

    train = subparsers.add_parser("train", help="fine-tune one configured LoRA adapter")
    train.add_argument("--manifest", required=True, type=Path)
    train.add_argument("--allow-model-download", action="store_true")

    benchmark = subparsers.add_parser("benchmark", help="run baseline or paired base/adapter evaluation")
    benchmark.add_argument("--manifest", required=True, type=Path)
    benchmark.add_argument("--output", required=True, type=Path)
    benchmark.add_argument("--adapter", type=Path)
    benchmark.add_argument("--allow-model-download", action="store_true")

    args = parser.parse_args()
    if args.command == "validate":
        if args.matrix:
            manifest = load_matrix_manifest(args.manifest)
        else:
            manifest = load_run_manifest(args.manifest)
        _print({"manifest": str(args.manifest.resolve()), "dataset": validate_dataset_pair(manifest["train_file"], manifest["evaluation_file"])})
        return 0
    if args.command == "collect-cards":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")
        roots = load_roots(args.roots)
        _print(generate_cards(
            roots, args.output, model=args.model, endpoint=args.endpoint, resume=args.resume,
            limit=args.limit, max_bytes=args.max_bytes, max_chars=args.max_chars,
        ))
        return 0
    if args.command == "split":
        _print(split_dataset(
            args.input, args.train, args.evaluation,
            evaluation_fraction=args.evaluation_fraction, seed=args.seed,
        ))
        return 0
    if args.command == "run-matrix":
        _print(run_matrix(args.manifest, allow_model_download=args.allow_model_download))
        return 0
    if args.command == "train":
        _print(train_from_manifest(args.manifest, allow_model_download=args.allow_model_download))
        return 0
    if args.command == "benchmark":
        _print(benchmark_from_manifest(
            args.manifest, adapter_path=args.adapter, output_path=args.output,
            allow_model_download=args.allow_model_download,
        ))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
