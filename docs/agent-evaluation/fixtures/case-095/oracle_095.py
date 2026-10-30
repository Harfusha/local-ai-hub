from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from writer import replace_bytes

class AtomicTests(unittest.TestCase):
    def test_failure_preserves_original_and_cleans_temporary(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'target.bin'
            original = b"\x00original\xff"
            path.write_bytes(original)
            def fail():
                raise RuntimeError('injected before replace')
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                replace_bytes(path, b'new', before_replace=fail)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(set(root.iterdir()), {path})

    def test_success_replaces_bytes(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'target.bin'
            path.write_bytes(b'old')
            replace_bytes(path, b'new\x00bytes')
            self.assertEqual(path.read_bytes(), b'new\x00bytes')
            self.assertEqual(set(path.parent.iterdir()), {path})

if __name__ == '__main__':
    unittest.main()
