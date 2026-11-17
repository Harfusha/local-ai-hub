from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "install_ownership_under_test",
    Path(__file__).resolve().parents[2] / "tools" / "install_ownership.py",
)
if _spec is None or _spec.loader is None:
    raise ImportError("could not load install_ownership.py")
install_ownership = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_ownership)
_setup_spec = importlib.util.spec_from_file_location(
    "setup_adoption_under_test", Path(__file__).resolve().parents[2] / "tools" / "setup.py"
)
if _setup_spec is None or _setup_spec.loader is None:
    raise ImportError("could not load setup.py")
setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(setup)


class ExternalBlockAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "install"
        self.root.mkdir()
        install_ownership.write_install_manifest(self.root, [])
        self.target = Path(self.temp.name) / "profile" / "AGENTS.md"
        self.target.parent.mkdir()
        self.marker = {"begin": "<!-- BEGIN LOCAL AI HUB POLICY -->", "end": "<!-- END LOCAL AI HUB POLICY -->"}
        self.block = f"{self.marker['begin']}\r\nOld policy\r\n{self.marker['end']}"
        self.target.write_bytes(f"User text\r\n{self.block}\r\nMore user text\r\n".encode("utf-8"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_adopts_exact_block_with_rollback_and_idempotent_record(self) -> None:
        adopted = install_ownership.adopt_external_block(
            self.root, self.target, owner_marker=self.marker,
            expected_block=self.block.replace("\r\n", "\n"), consent=True,
            audit_reason="operator requested profile installation",
        )

        self.assertTrue(adopted)
        install_ownership.assert_external_block_writable(
            self.root, self.target, owner_marker=self.marker,
            current_block=self.block.replace("\r\n", "\n"),
        )
        manifest = json.loads((self.root / install_ownership.MANIFEST_NAME).read_text(encoding="utf-8"))
        record = manifest["external_ownership"][0]
        self.assertFalse(record["created_by_hub"])
        self.assertIsNotNone(record["preimage_digest"])
        self.assertEqual(record["adoption_reason"], "operator requested profile installation")
        rollback = self.root / record["rollback_reference"]
        self.assertEqual(rollback.read_bytes().decode("utf-8"), self.block)
        self.assertEqual(install_ownership.adopt_external_block(
            self.root, self.target, owner_marker=self.marker,
            expected_block=self.block.replace("\r\n", "\n"), consent=True,
            audit_reason="operator requested profile installation",
        ), False)

    def test_requires_consent_and_refuses_changed_adopted_block(self) -> None:
        with self.assertRaisesRegex(ValueError, "consent"):
            install_ownership.adopt_external_block(
                self.root, self.target, owner_marker=self.marker, expected_block=self.block, consent=False,
                audit_reason="operator requested profile installation",
            )

        install_ownership.adopt_external_block(
            self.root, self.target, owner_marker=self.marker, expected_block=self.block, consent=True,
            audit_reason="operator requested profile installation",
        )
        current = self.target.read_bytes().decode("utf-8")
        self.target.write_bytes(current.replace("Old policy", "edited policy").encode("utf-8"))
        with self.assertRaisesRegex(ValueError, "changed"):
            install_ownership.adopt_external_block(
                self.root, self.target, owner_marker=self.marker, expected_block=self.block, consent=True,
                audit_reason="operator requested profile installation",
            )

    def test_setup_adopts_only_when_explicit_switch_is_enabled(self) -> None:
        prior_root = setup._ACTIVE_INSTALL_ROOT
        prior_adoption = setup._ADOPT_UNOWNED_HUB_BLOCKS
        try:
            setup._ACTIVE_INSTALL_ROOT = self.root
            setup._ADOPT_UNOWNED_HUB_BLOCKS = False
            with self.assertRaisesRegex(ValueError, "no ownership record"):
                setup._assert_or_adopt_external_block(self.target, self.marker, self.block)

            setup._ADOPT_UNOWNED_HUB_BLOCKS = True
            setup._assert_or_adopt_external_block(self.target, self.marker, self.block)
            install_ownership.assert_external_block_writable(
                self.root, self.target, owner_marker=self.marker, current_block=self.block,
            )
        finally:
            setup._ACTIVE_INSTALL_ROOT = prior_root
            setup._ADOPT_UNOWNED_HUB_BLOCKS = prior_adoption

    def test_refuses_ambiguous_marker_pairs_without_recording_ownership(self) -> None:
        self.target.write_bytes(f"{self.block}\r\n{self.block}\r\n".encode("utf-8"))

        with self.assertRaisesRegex(ValueError, "exactly one ordered marker pair"):
            install_ownership.adopt_external_block(
                self.root, self.target, owner_marker=self.marker, expected_block=self.block,
                consent=True, audit_reason="operator requested profile installation",
            )

        manifest = json.loads((self.root / install_ownership.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["external_ownership"], [])


if __name__ == "__main__":
    unittest.main()
