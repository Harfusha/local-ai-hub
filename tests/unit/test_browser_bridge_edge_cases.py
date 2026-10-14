from __future__ import annotations

import pytest
from local_ai_hub import browser_bridge


def test_safe_origin_canonicalizes_default_ports() -> None:
    # HTTP port 80 should be normalized to omit port
    assert browser_bridge._safe_origin("http://example.com:80/path") == "http://example.com"
    assert browser_bridge._safe_origin("http://example.com/path") == "http://example.com"

    # HTTPS port 443 should be normalized to omit port
    assert browser_bridge._safe_origin("https://example.com:443/secure") == "https://example.com"
    assert browser_bridge._safe_origin("https://example.com/secure") == "https://example.com"

    # Non-standard ports remain preserved
    assert browser_bridge._safe_origin("http://example.com:8080/path") == "http://example.com:8080"
    assert browser_bridge._safe_origin("https://example.com:8443/path") == "https://example.com:8443"


def test_validate_capture_payload_detects_extended_sensitive_keys() -> None:
    cfg = {"browser_bridge": {"enabled": True, "max_payload_bytes": 1000000}}

    for sensitive_key in ["api_key", "access_token", "refresh_token", "private_key", "secret_key"]:
        bad_payload = {
            "tab_id": 1,
            "url": "https://example.com",
            "screenshot": "data:image/png;base64,iVBORw0KGgo=",
            "dom": {"redaction": "none", "html": "<div></div>", "elements": []},
            sensitive_key: "super_secret_value",
        }
        res = browser_bridge.validate_capture_payload(bad_payload, config=cfg)
        assert res["success"] is False
        assert res["error_code"] == "credential_bearing_capture_fields"
