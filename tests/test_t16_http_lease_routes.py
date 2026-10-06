from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.process_utils import run_hidden


def _linked_worktrees(parent: Path, name: str) -> tuple[Path, Path]:
    primary = parent / name / "primary"
    linked = parent / name / "linked"
    (primary / "src").mkdir(parents=True)
    (primary / "src" / "shared.py").write_text("baseline\n", encoding="utf-8")
    (primary / ".local-ai.toml").write_text('shared_namespace = "team"\n', encoding="utf-8")
    run_hidden(["git", "init", "--quiet", str(primary)], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(["git", "-C", str(primary), "add", ".local-ai.toml", "src/shared.py"], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(
        ["git", "-C", str(primary), "-c", "user.name=Lease Fixture", "-c", "user.email=lease-fixture@example.invalid", "commit", "--quiet", "-m", "lease fixture"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    run_hidden(
        ["git", "-C", str(primary), "worktree", "add", "--quiet", "-b", "linked", str(linked)],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return primary, linked


def test_http_lease_routes_resolve_namespace_and_isolate_linked_worktrees(tmp_path: Path) -> None:
    worktree_a, worktree_b = _linked_worktrees(tmp_path, "http-linked")
    unrelated, _ = _linked_worktrees(tmp_path, "http-unrelated")
    malformed, _ = _linked_worktrees(tmp_path, "http-malformed")
    (malformed / ".local-ai.toml").write_text("shared_namespace = [\n", encoding="utf-8")
    state_dir = tmp_path / "http-state"
    state_dir.mkdir()
    app = SimpleNamespace(
        config={
            "server": {"state_dir": str(state_dir)},
            "security": {"api_token": "lease-test-token"},
            "observability": {
                "exclude_http_paths": [
                    "/api/leases", "/api/leases/claim", "/api/leases/claim_batch",
                    "/api/leases/renew", "/api/leases/release",
                ]
            },
        },
        leases=ScopeLeaseStore(state_dir),
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(method: str, path: str, *, tenant: str = "owner-a", payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={
                "X-LocalAI-Token": "lease-test-token",
                "X-LocalAI-Tenant": tenant,
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        forged_id = "client-selected-namespace"
        claim_a = request("POST", "/api/leases/claim", payload={
            "root": str(worktree_a), "paths": ["src/shared.py"], "coordination_id": forged_id,
        })
        claim_b = request("POST", "/api/leases/claim_batch", tenant="owner-b", payload={
            "root": str(worktree_b), "paths": ["src/shared.py"], "coordination_id": forged_id,
        })
        claim_c = request("POST", "/api/leases/claim", tenant="owner-c", payload={
            "root": str(unrelated), "paths": ["src/shared.py"], "coordination_id": forged_id,
        })
        assert claim_a["success"] is True
        assert claim_b["success"] is False
        assert claim_b["conflicts"]
        assert claim_c["success"] is True
        assert request("POST", "/api/leases/claim", tenant="owner-malformed", payload={
            "root": str(malformed), "paths": ["src/shared.py"], "coordination_id": forged_id,
        })["success"] is False

        url_a = "/api/leases?" + urllib.parse.urlencode({"root": str(worktree_a)})
        url_c = "/api/leases?" + urllib.parse.urlencode({"root": str(unrelated)})
        state_a = request("GET", url_a)
        state_c = request("GET", url_c)
        assert [lease["lease_id"] for lease in state_a["leases"]] == [claim_a["lease_id"]]
        assert [wait["tenant"] for wait in state_a["waits"]] == ["owner-b"]
        assert [lease["lease_id"] for lease in state_c["leases"]] == [claim_c["lease_id"]]
        assert state_c["waits"] == []

        app.leases = ScopeLeaseStore(state_dir)
        assert request("GET", url_a)["leases"] == state_a["leases"]
        assert request("POST", "/api/leases/release", tenant="owner-b", payload={
            "lease_id": claim_a["lease_id"],
        })["released_rows"] == 0
        assert request("GET", url_a)["leases"]
        assert request("POST", "/api/leases/renew", tenant="owner-b", payload={
            "lease_id": claim_a["lease_id"], "ttl_seconds": 1200,
        })["success"] is False
        assert request("POST", "/api/leases/renew", tenant="owner-a", payload={
            "lease_id": claim_a["lease_id"], "ttl_seconds": 1200,
        })["success"] is True
        assert request("POST", "/api/leases/release", tenant="owner-a", payload={
            "lease_id": claim_a["lease_id"],
        })["released_rows"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
