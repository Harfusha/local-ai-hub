"""Export Laya ModernBERT router encoder to ONNX Runtime for ultra-low latency inference."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

logger = logging.getLogger(__name__)


def export_laya_to_onnx(
    checkpoint_dir: str | Path,
    output_path: str | Path,
    opset_version: int = 17,
) -> Path:
    """Export ModernBERT encoder from Laya checkpoint to ONNX."""
    ckpt = Path(checkpoint_dir)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    from transformers import AutoModel, AutoTokenizer

    encoder_path = ckpt / "encoder" if (ckpt / "encoder").exists() else ckpt
    tokenizer_path = ckpt / "tokenizer" if (ckpt / "tokenizer").exists() else ckpt

    logger.info("Loading tokenizer from %s", tokenizer_path)
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path))

    logger.info("Loading PyTorch model from %s", encoder_path)
    model = AutoModel.from_pretrained(str(encoder_path))
    model.eval()

    dummy_text = "Task: analyze repository architecture context source"
    inputs = tokenizer(dummy_text, return_tensors="pt")
    input_ids = inputs["input_ids"]
    attention_mask = inputs.get("attention_mask", torch.ones_like(input_ids))

    logger.info("Exporting to ONNX at %s (opset %d)...", out, opset_version)
    torch.onnx.export(
        model,
        (input_ids, attention_mask),
        str(out),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "last_hidden_state": {0: "batch_size", 1: "sequence_length"},
        },
        opset_version=opset_version,
        do_constant_folding=True,
    )

    logger.info("ONNX export completed successfully: %s", out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Laya checkpoint to ONNX")
    parser.add_argument("--checkpoint", required=True, help="Path to Laya checkpoint directory")
    parser.add_argument("--output", default="state/models/laya/laya_encoder.onnx", help="Output .onnx path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    export_laya_to_onnx(args.checkpoint, args.output)
