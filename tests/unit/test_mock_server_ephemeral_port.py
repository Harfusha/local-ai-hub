from __future__ import annotations

import json
import socketserver
import threading
from pathlib import Path
from urllib.request import urlopen
import pytest

from local_ai_hub.commands import CommandBroker


def _broker(tmp_path):
    return CommandBroker({'server': {'state_dir': str(tmp_path / 'state')}, 'commands': {'enabled': True}})


def _spec(tmp_path):
    path = tmp_path / 'openapi.json'
    path.write_text(json.dumps({'paths': {'/health': {'get': {'responses': {}}}}}), encoding='utf-8')
    return str(path)


def test_zero_port_returns_bound_ephemeral_port_and_registers_it(tmp_path, monkeypatch):
    bound = []
    class Server:
        def __init__(self, address, handler):
            bound.append(address)
            self.server_address = ('127.0.0.1', 40123)
            self.done = threading.Event()
        def serve_forever(self):
            self.done.wait(2)
        def shutdown(self):
            self.done.set()
        def server_close(self):
            pass
    monkeypatch.setattr(socketserver, 'TCPServer', Server)
    broker = _broker(tmp_path)
    result = broker.mock_server_start(str(tmp_path), spec_path=_spec(tmp_path), port=0)
    try:
        assert result['success'], result
        assert bound == [('127.0.0.1', 0)]
        assert result['port'] == 40123
        assert broker.mock_server_status(40123)['running'] is True
    finally:
        for port in list(getattr(broker, '_mock_servers', {})):
            broker.mock_server_stop(port)


def test_recorded_cassette_drops_authentication_and_cookie_headers(tmp_path, monkeypatch):
    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, 'http_probe', lambda *args, **kw: {
        'success': True, 'status_code': 200, 'body_preview': '{}', 'body_length': 2,
        'headers': {'Authorization': 'Bearer secret', 'Cookie': 'private=1',
                    'Set-Cookie': 'private=2', 'Content-Type': 'application/json'},
    })
    result = broker.record_mock('http://127.0.0.1/health', 'safe-cassette')
    assert result['success'], result
    data = json.loads(Path(result['cassette']).read_text(encoding='utf-8'))
    assert data['headers'] == {'content-type': 'application/json'}


def test_two_real_ephemeral_servers_are_reachable_and_stop_cleanly(tmp_path):
    broker = _broker(tmp_path)
    spec = _spec(tmp_path)
    ports = []
    try:
        for arguments in ({}, {'port': 0}):
            result = broker.mock_server_start(str(tmp_path), spec_path=spec, **arguments)
            assert result['success'], result
            ports.append(result['port'])
            assert 0 < result['port'] <= 65535
            with urlopen(f"http://127.0.0.1:{result['port']}/health", timeout=2) as response:
                assert json.loads(response.read(4096))['mock'] is True
        assert ports[0] != ports[1]
    finally:
        for port in ports:
            assert broker.mock_server_stop(port)['success']
            thread = broker._mock_servers[port]['thread']
            thread.join(timeout=2)
            assert not thread.is_alive()


@pytest.mark.parametrize('port', [-1, 65536, True, 1.5])
def test_invalid_port_is_rejected_before_server_creation(tmp_path, port):
    assert _broker(tmp_path).mock_server_start(str(tmp_path), port=port)['success'] is False
