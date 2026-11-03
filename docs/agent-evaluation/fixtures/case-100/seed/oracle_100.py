import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from exporter import export, ExportCancelled

class LifecycleTests(unittest.TestCase):
    def test_unicode_export(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'export.csv'
            export(path, [{'id':'1', 'name':'Příliš žluťoučký'}])
            with path.open(encoding='utf-8', newline='') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [{'id':'1', 'name':'Příliš žluťoučký'}])

    def test_cancel_preserves_previous_and_creates_no_duplicate(self):
        for cancel_at in (1, 2):
            with self.subTest(cancel_at=cancel_at), TemporaryDirectory() as folder:
                path = Path(folder) / 'export.csv'
                path.write_bytes(b'original')
                calls = 0
                def cancelled():
                    nonlocal calls
                    calls += 1
                    return calls >= cancel_at
                with self.assertRaises(ExportCancelled):
                    export(path, [{'id':'1', 'name':'test'}], cancelled=cancelled)
                self.assertEqual(path.read_bytes(), b'original')
                self.assertEqual(set(path.parent.iterdir()), {path})

if __name__ == '__main__':
    unittest.main()
