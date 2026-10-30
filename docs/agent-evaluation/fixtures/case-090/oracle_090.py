import json
import inspect
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import adapter
import sdk
import server

VALID = {'phase': 'implement', 'next_action': 'validate', 'affected_paths': [], 'evidence_ids': [], 'blockers': [], 'state_data': {}}

class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=3)
        cls.server.server_close()

    def post(self, payload):
        req = Request(self.url + '/checkpoint', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_nested_checkpoint_through_adapter_sdk_and_http(self):
        self.assertIn('checkpoint', inspect.signature(adapter.checkpoint_task).parameters)
        self.assertIn('checkpoint', inspect.signature(sdk.checkpoint).parameters)
        status, result = adapter.checkpoint_task(self.url, checkpoint=VALID)
        self.assertEqual(status, 200)
        self.assertEqual(result['checkpoint'], VALID)

    def test_flat_contract_rejected(self):
        self.assertEqual(self.post(VALID)[0], 400)

    def test_missing_and_falsey_wrong_types_rejected(self):
        for field, invalid in [('phase', ''), ('next_action', None), ('affected_paths', False), ('evidence_ids', ''), ('blockers', 0), ('state_data', [])]:
            with self.subTest(field=field):
                self.assertEqual(self.post({'checkpoint': {**VALID, field: invalid}})[0], 400)
        for field in VALID:
            with self.subTest(missing=field):
                self.assertEqual(self.post({'checkpoint': {k: v for k, v in VALID.items() if k != field}})[0], 400)
        for field in ('affected_paths', 'evidence_ids', 'blockers'):
            with self.subTest(nonstring_item=field):
                self.assertEqual(self.post({'checkpoint': {**VALID, field: [False]}})[0], 400)
        self.assertEqual(self.post({'checkpoint': {**VALID, 'retired_field': 1}})[0], 400)
        self.assertEqual(self.post({'checkpoint': VALID, 'phase': 'legacy'})[0], 400)

    def test_prompt_contract_synchronized(self):
        for name in ('INSTALL_PROMPT.md', 'UPDATE_PROMPT.md'):
            with self.subTest(name=name):
                content = Path(name).read_text(encoding='utf-8')
                for field in ('checkpoint', *VALID):
                    self.assertIn(field, content)

if __name__ == '__main__':
    unittest.main()
