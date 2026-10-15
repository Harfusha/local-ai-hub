"""Offline code counting with explicit encoding/estimate provenance."""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

# Encoding hashes and pre-tokenization rules from OpenAI tiktoken's openai_public.py:
# https://github.com/openai/tiktoken/blob/main/tiktoken_ext/openai_public.py
_ENCODINGS = {
    "cl100k_base": (
        "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s",
    ),
    "o200k_base": (
        "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
        "|".join((
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*", r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
        )),
    ),
}
_CODE_PIECES = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|\d{1,3}|_+|[^\w\s]|[^\W\d_]+", re.UNICODE)


@lru_cache(maxsize=2)
def offline_encoding(name: str) -> Any | None:
    """Read verified existing ranks; never calls any downloader or get_encoding."""
    if name not in _ENCODINGS:
        raise ValueError("supported encodings: cl100k_base, o200k_base")
    cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", os.environ.get("DATA_GYM_CACHE_DIR",
                               str(Path(tempfile.gettempdir()) / "data-gym-cache")))
    if not cache_dir:
        return None
    url = f"https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken"
    cache_key = hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()
    try:
        with (Path(cache_dir) / cache_key).open("rb") as handle:
            data = handle.read(8_000_001)
        expected_hash, pattern = _ENCODINGS[name]
        if len(data) > 8_000_000 or hashlib.sha256(data).hexdigest() != expected_hash:
            return None
        ranks = {}
        for line in data.splitlines():
            encoded, rank = line.split()
            ranks[base64.b64decode(encoded, validate=True)] = int(rank)
        import tiktoken

        # Treat special-token-looking source as ordinary source text. Encoding
        # requires only merge ranks and its pre-tokenizer for that behavior.
        return tiktoken.Encoding(name=name, pat_str=pattern, mergeable_ranks=ranks, special_tokens={})
    except (OSError, ImportError, ValueError, TypeError, RuntimeError):
        return None


def estimate_code_tokens(text: str) -> int:
    """Subword-aware fallback; no numeric accuracy guarantee without calibration."""
    if not text:
        return 0
    pieces = sum(max(1, math.ceil(len(match.group().encode("utf-8")) / 4))
                 for match in _CODE_PIECES.finditer(text))
    return max(1, pieces, math.ceil(len(text.encode("utf-8")) / 3.4))


def count_code_tokens(text: str, *, encoding: str = "o200k_base") -> dict[str, Any]:
    if encoding not in _ENCODINGS:
        raise ValueError("supported encodings: cl100k_base, o200k_base")
    tokenizer = offline_encoding(encoding) if text else None
    if tokenizer is not None:
        try:
            return {"tokens": len(tokenizer.encode(text, disallowed_special=())), "encoding": encoding,
                    "exact": True, "method": "offline_verified_bpe", "reference_sha256": _ENCODINGS[encoding][0]}
        except (ValueError, TypeError, RuntimeError):
            pass
    return {"tokens": estimate_code_tokens(text), "encoding": encoding, "exact": not text,
            "method": "empty" if not text else "code_subword_estimate_v1", "accuracy_bound_verified": False}
