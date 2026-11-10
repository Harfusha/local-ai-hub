from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .benchmark import benchmark_from_manifest
from .dataset import split_dataset, split_embedding_corpus
from .existing_cards import export_existing_cards, list_existing_card_candidates
from .manifest import load_run_manifest, validate_dataset_pair
from .laya_backend import split_laya_dataset
from .run_matrix import load_matrix_manifest, run_matrix
from .train import train_from_manifest


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Local, opt-in model fine-tuning and paired benchmark scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one run or matrix manifest and datasets")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--matrix", action="store_true")

    existing = subparsers.add_parser(
        "export-existing-cards", help="read existing indexed Hub cards without model calls"
    )
    existing.add_argument("--state-dir", required=True, type=Path)
    root_selector = existing.add_mutually_exclusive_group(required=True)
    root_selector.add_argument("--roots", type=Path, help="authorized roots file; roots must already be indexed")
    root_selector.add_argument("--all-indexed", action="store_true", help="use only roots already registered in the index")
    existing.add_argument("--output", required=True, type=Path,
                          help="JSONL path, absolute or relative to state-dir")
    existing.add_argument("--format", choices=("card-training", "embedding-corpus"), required=True)
    existing.add_argument("--resume", action="store_true")
    existing.add_argument("--benchmark-cases", type=Path,
                          help="existing manually judged retrieval cases for embedding-corpus metadata")
    existing.add_argument("--benchmark-root", type=Path,
                          help="repository root that anchors --benchmark-cases expected paths")

    list_existing = subparsers.add_parser(
        "list-existing-card-candidates", help="list eligible card IDs without exporting content"
    )
    list_existing.add_argument("--state-dir", required=True, type=Path)
    list_root_selector = list_existing.add_mutually_exclusive_group(required=True)
    list_root_selector.add_argument("--roots", type=Path, help="authorized roots file")
    list_root_selector.add_argument("--all-indexed", action="store_true")
    list_existing.add_argument("--format", choices=("card-training", "embedding-corpus"), required=True)

    split = subparsers.add_parser("split", help="create a deterministic group-held-out split")
    split.add_argument("--input", required=True, type=Path)
    split.add_argument("--train", required=True, type=Path)
    split.add_argument("--evaluation", required=True, type=Path)
    split.add_argument("--evaluation-fraction", type=float, default=0.2)
    split.add_argument("--seed", type=int, default=20261110)
    split.add_argument("--format", choices=("chat", "laya", "embedding-corpus"), default="chat",
                       help="row format; embedding corpus uses existing card text without relevance labels")

    matrix = subparsers.add_parser("run-matrix", help="benchmark before, train, then benchmark each model")
    matrix.add_argument("--manifest", required=True, type=Path)
    matrix.add_argument("--allow-model-download", action="store_true")

    train = subparsers.add_parser("train", help="fine-tune one configured model backend")
    train.add_argument("--manifest", required=True, type=Path)
    train.add_argument("--allow-model-download", action="store_true")

    benchmark = subparsers.add_parser("benchmark", help="run baseline or paired model evaluation")
    benchmark.add_argument("--manifest", required=True, type=Path)
    benchmark.add_argument("--output", required=True, type=Path)
    benchmark.add_argument("--adapter", "--checkpoint", dest="adapter", type=Path,
                           help="candidate adapter directory or native Laya checkpoint")
    benchmark.add_argument("--baseline", type=Path,
                           help="required before-report path for a paired Laya checkpoint benchmark")
    benchmark.add_argument("--allow-model-download", action="store_true")

    args = parser.parse_args()
    if args.command == "validate":
        if args.matrix:
            manifest = load_matrix_manifest(args.manifest)
        else:
            manifest = load_run_manifest(args.manifest)
        _print({"manifest": str(args.manifest.resolve()), "dataset": validate_dataset_pair(
            manifest["train_file"], manifest["evaluation_file"], backend=manifest.get("backend", "transformers_lora")
        )})
        return 0
    if args.command == "list-existing-card-candidates":
        _print(list_existing_card_candidates(
            state_dir=args.state_dir, roots_file=args.roots, format=args.format,
        ))
        return 0
    if args.command == "export-existing-cards":
        _print(export_existing_cards(
            state_dir=args.state_dir, roots_file=args.roots, output_path=args.output,
            format=args.format, resume=args.resume,
            benchmark_cases_file=args.benchmark_cases, benchmark_root=args.benchmark_root,
        ))
        return 0
    if args.command == "split":
        splitter = {
            "chat": split_dataset,
            "laya": split_laya_dataset,
            "embedding-corpus": split_embedding_corpus,
        }[args.format]
        _print(splitter(
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
            baseline_report_path=args.baseline, allow_model_download=args.allow_model_download,
        ))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
