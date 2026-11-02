"""Receipt classification must not weaken the completion gate."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from local_ai_hub import agent_verification as module


class ReceiptClassificationTests(unittest.TestCase):
    def setUp(self):
        self.receipt = module.VerificationReceipt(
            receipt_id="receipt-1", task_id="task-1", criterion="test", owner="owner-1",
            evidence_id="artifact-1", command_id="1" * 32, repository_revision="revision-1",
            mutation_generation=1, evidence_type="test", observed_at=1, passed=True,
        )

    def evaluate(self, receipt, *, generation=1, mapped=None, provenance=True):
        with patch.object(module, "_receipt_evidence_matches", return_value=provenance):
            return module.evaluate_completion_receipts(
                "task-1", ["test"], [receipt], owner="owner-1", repository_revision="revision-1",
                mutation_generation=generation, mapped_receipt_ids={} if mapped is None else mapped, now=2,
            )

    def test_rollback_unmapped_generation_is_stale(self):
        result = self.evaluate(self.receipt, generation=2)
        self.assertFalse(result.complete)
        self.assertEqual(result.stale_criteria, ("test",))

    def test_current_unmapped_remains_unsatisfied(self):
        result = self.evaluate(self.receipt)
        self.assertFalse(result.complete)
        self.assertEqual(result.unsatisfied_criteria, ("test",))

    def test_current_unmapped_skips_provenance_lookup(self):
        with patch.object(module, "_receipt_evidence_matches", return_value=True) as lookup:
            result = module.evaluate_completion_receipts(
                "task-1", ["test"], [self.receipt], owner="owner-1", repository_revision="revision-1",
                mutation_generation=1, mapped_receipt_ids={}, now=2,
            )
        self.assertFalse(result.complete)
        lookup.assert_not_called()

    def test_foreign_and_untrusted_remain_unsatisfied_even_if_stale(self):
        for receipt, provenance in (
            (replace(self.receipt, task_id="foreign"), True),
            (replace(self.receipt, owner="foreign"), True),
            (replace(self.receipt, passed=False), True),
            (self.receipt, False),
        ):
            with self.subTest(receipt=receipt, provenance=provenance):
                result = self.evaluate(receipt, generation=2, provenance=provenance)
                self.assertFalse(result.complete)
                self.assertEqual(result.unsatisfied_criteria, ("test",))

    def test_mapped_stale_receipt_remains_stale(self):
        result = self.evaluate(self.receipt, generation=2, mapped={"test": "receipt-1"})
        self.assertFalse(result.complete)
        self.assertEqual(result.stale_criteria, ("test",))

    def test_current_mapped_valid_receipt_completes(self):
        result = self.evaluate(self.receipt, mapped={"test": "receipt-1"})
        self.assertTrue(result.complete)

    def test_project_rule_valid_evidence_at_old_revision_is_stale(self):
        with patch.object(module, "_receipt_evidence_matches", return_value=True):
            result = module.evaluate_completion_receipts(
                "task-1", ["test"], [self.receipt], owner="owner-1", repository_revision="revision-2",
                mutation_generation=1, mapped_receipt_ids={"test": "receipt-1"}, now=2,
                verification_rules={"test": ("test",)}, configured_criteria=("test",),
            )
        self.assertFalse(result.complete)
        self.assertEqual(result.stale_criteria, ("test",))

    def test_project_rule_missing_current_revision_is_unsatisfied(self):
        with patch.object(module, "_receipt_evidence_matches", return_value=True):
            result = module.evaluate_completion_receipts(
                "task-1", ["test"], [self.receipt], owner="owner-1", repository_revision="",
                mutation_generation=1, mapped_receipt_ids={"test": "receipt-1"}, now=2,
                verification_rules={"test": ("test",)}, configured_criteria=("test",),
            )
        self.assertFalse(result.complete)
        self.assertEqual(result.unsatisfied_criteria, ("test",))
