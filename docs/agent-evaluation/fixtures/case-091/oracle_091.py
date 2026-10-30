import csv
import io
import json
import subprocess
import unittest
import backend

ROWS = [{'id':'1','name':'Alfa, β','status':'ready'}, {'id':'2','name':'skipped','status':'pending'}, {'id':'3','name':'A "quote"','status':'ready'}]
EXPECTED = [{'id':'1','name':'Alfa, β'}, {'id':'3','name':'A "quote"'}]

def frontend(rows):
    result = subprocess.run(['node', '--experimental-strip-types', 'frontend.ts'], input=json.dumps(rows, ensure_ascii=False), text=True, encoding='utf-8', capture_output=True, timeout=10, check=True)
    return result.stdout

class IntegrationTests(unittest.TestCase):
    def test_backend(self):
        self.assertEqual(backend.select_ready(ROWS), EXPECTED)

    def test_frontend(self):
        out = frontend(EXPECTED)
        self.assertEqual(out, 'id,name\n"1","Alfa, β"\n"3","A ""quote"""\n')

    def test_integrated_export(self):
        parsed = list(csv.DictReader(io.StringIO(frontend(backend.select_ready(ROWS)))))
        self.assertEqual(parsed, EXPECTED)

if __name__ == '__main__':
    unittest.main()
