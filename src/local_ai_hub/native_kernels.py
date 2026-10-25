"""Native performance kernels for Local AI Hub with strict Python fallbacks.

Provides bitwise-identical SimHash calculation using an optional compiled
Cython extension, with automatic graceful fallback when the compiled binary
is absent or fails.
"""

from __future__ import annotations

import array
import hashlib
import os
import re
import sys
from functools import lru_cache
from typing import Any

# Optional import of compiled Cython extension
_NATIVE_SIMHASH_MODULE: Any | None = None
_NATIVE_IMPORT_ERROR: str | None = None

for _mod_name in ("cython_simhash_votes", "local_ai_hub._simhash_native", "_simhash_native"):
    try:
        _NATIVE_SIMHASH_MODULE = __import__(_mod_name, fromlist=["simhash_votes"])
        break
    except (ImportError, ModuleNotFoundError) as _err:
        _NATIVE_IMPORT_ERROR = str(_err)
    except Exception as _err:
        _NATIVE_IMPORT_ERROR = str(_err)
        break

# Enablement flag: can be toggled at runtime or controlled via LOCAL_AI_SIMHASH_NATIVE
# Defaults to True on Windows when native module is available, False if unavailable or disabled.
_DEFAULT_ENABLED = (
    _NATIVE_SIMHASH_MODULE is not None
    and os.environ.get("LOCAL_AI_SIMHASH_NATIVE", "1" if sys.platform == "win32" else "1").strip().lower()
    in ("1", "true", "yes", "on")
)
_NATIVE_ENABLED: bool = _DEFAULT_ENABLED


def is_native_available() -> bool:
    """Return True if the native SimHash extension was successfully loaded."""
    return _NATIVE_SIMHASH_MODULE is not None


def is_native_enabled() -> bool:
    """Return True if native acceleration is enabled."""
    return _NATIVE_ENABLED and is_native_available()


def set_native_enabled(enabled: bool) -> None:
    """Explicitly enable or disable native acceleration at runtime."""
    global _NATIVE_ENABLED
    _NATIVE_ENABLED = bool(enabled)


def get_native_import_error() -> str | None:
    """Return the import error message if the native module failed to load."""
    return _NATIVE_IMPORT_ERROR


def _python_simhash_votes(hashes: Any) -> int:
    """Mathematical reference for 64-bit SimHash voting."""
    count = len(hashes)
    if count == 0:
        return 0
    # Start at -N, then add 2 for each set bit
    v = [-count] * 64
    for h in hashes:
        while h:
            lsb = h & -h
            v[lsb.bit_length() - 1] += 2
            h ^= lsb
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= (1 << i)
    return fp


def _validate_uint64_buffer(values: Any) -> Any:
    """Validate that the input is a contiguous 1D uint64 buffer. Raise ValueError/TypeError otherwise."""
    if isinstance(values, array.array):
        if values.typecode != "Q":
            raise TypeError(f"array typecode must be 'Q' (unsigned 64-bit int), got {values.typecode!r}")
        return values
    try:
        mem = memoryview(values)
    except TypeError as exc:
        raise TypeError(f"expected a buffer object, got {type(values).__name__}") from exc

    if mem.ndim != 1:
        raise ValueError(f"expected 1D buffer, got {mem.ndim} dimensions")
    if not mem.contiguous:
        raise ValueError("buffer must be contiguous")
    if mem.format not in ("Q", "B", "=Q", "<Q", ">Q") or (mem.format != "Q" and mem.itemsize != 8):
        if mem.itemsize != 8:
            raise TypeError(f"expected 8-byte uint64 elements, got itemsize {mem.itemsize}")
    return mem


def simhash_votes(values: Any) -> int:
    """Compute 64-bit SimHash fingerprint from a contiguous uint64 buffer of shingle hashes.

    Rejects malformed buffer format or shape explicitly.
    Uses the compiled native kernel if enabled and available, falling back
    to the exact Python reference implementation.
    """
    validated = _validate_uint64_buffer(values)
    if len(validated) == 0:
        return 0

    if is_native_enabled():
        try:
            return int(_NATIVE_SIMHASH_MODULE.simhash_votes(validated))
        except Exception:
            # Fallback to Python if native call fails
            pass

    return _python_simhash_votes(validated)


@lru_cache(maxsize=131_072)
def _shingle_hash(shingle: str) -> int:
    """16-hex MD5 shingle hash (64-bit integer), identical to rag._simhash_shingle_hash."""
    return int(
        hashlib.md5(shingle.encode("utf-8"), usedforsecurity=False).hexdigest()[:16],
        16,
    )


def simhash_text(text: str) -> int:
    """Compute 64-bit SimHash of text based on character 4-grams.

    Bitwise identical to rag._simhash.
    Uses the native kernel if enabled and available, with graceful Python fallback.
    """
    clean = re.sub(r"\s+", " ", text.lower().strip())
    if len(clean) < 4:
        shingles = [clean] if clean else []
    else:
        shingles = [clean[i : i + 4] for i in range(len(clean) - 3)]
    if not shingles:
        return 0

    hashes = array.array("Q", (_shingle_hash(s) for s in shingles))
    return simhash_votes(hashes)
