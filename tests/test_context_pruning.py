"""Tests for Laya Dynamic Context Pruning and AST Skeletonization."""

from src.local_ai_hub.context_pruning import prune_source_context


def test_prune_python_ast_skeletonization():
    code = '''
class PaymentProcessor:
    """Payment processing engine."""

    def __init__(self, api_key: str):
        """Initialize processor."""
        self.api_key = api_key
        self.session = None
        self.retries = 3

    def process_transaction(self, amount: float) -> bool:
        """Process charge."""
        if amount <= 0:
            return False
        # complex logic
        x = 100
        y = 200
        z = x + y
        return True

    def _internal_utility(self, a: int, b: int) -> int:
        """Internal helper."""
        res = 0
        for i in range(100):
            res += i * a
        return res
'''

    # Keep only process_transaction
    res = prune_source_context(code, relevant_symbols={"process_transaction"})
    assert res.saved_lines > 0
    assert "def process_transaction(self, amount: float) -> bool:" in res.text
    assert "z = x + y" in res.text  # Implementation preserved!
    assert "def _internal_utility(self, a: int, b: int) -> int:" in res.text  # Signature preserved!
    assert "Internal helper." in res.text  # Docstring preserved!
    assert "for i in range(100):" not in res.text  # Utility body pruned!
    assert "...  # [pruned" in res.text
