# T13 find_symbol include_body candidate handoff

Candidate branch HEAD: e9d6d82e535f5d5ca87018b89b33c2665084b77b

Candidate changes:
- src/local_ai_hub/http_server.py: shared parser; GET accepts absent/true/false (lowercase canonical); POST accepts JSON booleans only; malformed values send HTTP 400 and return before service call.
- tests/test_http_code_find_symbol_include_body.py: parser-only regression; it does not prove route 400/service-call behavior.
- handoff/t13-find-symbol-include-body.patch: two file paths only (source and one new test).

Root preimage pins supplied by T04:
- http_server.py: A8DF17496129DDA67BB74711A7D83568385FC301AB670AF3FB8F1659C7E3221D
- test_http_route_operation_acceptance.py: B314578642480CDD0B896D863EABFE1730637BC61D5C1C2A0D05DA0BA7D9FCAF

Candidate SHA-256:
- http_server.py: E498DA9007657A9288195840E74979E846106781FCBFC65EF6FD8439C0E134CA
- parser-only test: 535873EBEE9D5483B65E2A511D2C25DD80F06D05C8B7CD3A7DA18F7D1184F956
- patch: 10DFE96BC89C867F134A403FD76CF6B2DA519D11EF6EE4B5C491B4AD971D767C

Selector: tests/test_http_code_find_symbol_include_body.py::test_parse_include_body_accepts_only_strict_values
Tests: not run (awaiting T20 serial GO).
Root edits/apply/apply-check: not performed.
git diff --check: passed; Git emitted an LF-to-CRLF autocrlf warning for http_server.py.