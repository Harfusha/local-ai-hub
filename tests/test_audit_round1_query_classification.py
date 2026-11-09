from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.search_modes import classify_query, prefers_lexical_precision


def test_classify_query_exact_symbol():
    assert classify_query("repo_search") == "exact_symbol"
    assert classify_query("C++") == "exact_symbol"
    assert classify_query("MyClass::my_method") == "exact_symbol"
    assert classify_query("__init__") == "exact_symbol"


def test_classify_query_file_path():
    assert classify_query("src/local_ai_hub/services.py") == "file_path"
    assert classify_query("config.php") == "file_path"
    assert classify_query("docs/AUDIT.md") == "file_path"


def test_classify_query_natural_language():
    assert classify_query("Local AI Hub installation") == "natural_language"
    assert classify_query("how to configure database") == "natural_language"


def test_classify_query_mixed():
    assert classify_query("Python 3.13") == "mixed"
    assert classify_query("how to configure config.php") == "mixed"
    assert classify_query("test repo_search behavior") == "mixed"


def test_prefers_lexical_precision_does_not_bypass_semantic_for_mixed_or_paths():
    assert prefers_lexical_precision("repo_search") is True
    assert prefers_lexical_precision("C++") is True
    assert prefers_lexical_precision("Python 3.13") is False
    assert prefers_lexical_precision("config.php") is False
    assert prefers_lexical_precision("how to configure config.php") is False
    assert prefers_lexical_precision("Local AI Hub installation") is False
