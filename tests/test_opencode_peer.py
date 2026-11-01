import json
import os
import socket

import pytest

from local_ai_hub.opencode_peer import PeerIdentityError, verify_supervised_peer
from local_ai_hub.process_utils import process_owner_record


@pytest.mark.skipif(os.name != "nt", reason="Windows socket-owner lookup")
def test_real_loopback_peer_matches_exact_owner_and_creation_identity(tmp_path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname(), timeout=3)
    accepted, _ = listener.accept()
    try:
        owner = process_owner_record(os.getpid(), tmp_path, "ollama")
        assert owner is not None
        marker = tmp_path / "ollama.owner.json"
        marker.write_text(json.dumps(owner), encoding="utf-8")
        verify_supervised_peer(client, tmp_path)
        owner["creation_identity"] = str(owner["creation_identity"]) + "0"
        marker.write_text(json.dumps(owner), encoding="utf-8")
        with pytest.raises(PeerIdentityError):
            verify_supervised_peer(client, tmp_path)
    finally:
        accepted.close()
        client.close()
        listener.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows socket-owner lookup")
def test_missing_owner_never_accepts_peer(tmp_path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname(), timeout=3)
    accepted, _ = listener.accept()
    try:
        with pytest.raises(PeerIdentityError):
            verify_supervised_peer(client, tmp_path)
    finally:
        accepted.close()
        client.close()
        listener.close()
