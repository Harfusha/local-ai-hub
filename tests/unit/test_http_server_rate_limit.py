from collections import deque
from contextlib import contextmanager
from types import SimpleNamespace

from local_ai_hub import http_server


def test_rate_limit_records_admissions_in_lock_order(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(http_server, "time", SimpleNamespace(monotonic=lambda: clock.now))
    window = deque()
    first = True

    @contextmanager
    def lock():
        nonlocal first
        if first:
            first = False
            # A different request obtains the lock before the waiting request.
            window.append(2.0)
            clock.now = 2.25
        yield

    limiter = SimpleNamespace(
        _rate_lock=lock(),
        _rate_limit_requests=2,
        _rate_limit_window=1.0,
        _rate_window=window,
    )
    check = http_server.LocalAIHTTPServer.check_rate_limit

    assert check(limiter)
    assert list(window) == [2.0, 2.25]

    clock.now = 3.1
    limiter._rate_lock = lock()
    assert check(limiter)
    limiter._rate_lock = lock()
    assert not check(limiter)
