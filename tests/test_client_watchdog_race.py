import threading

from local_ai_hub.client import HubClient


def test_completed_request_is_not_closed_by_late_cancellation():
    entered = threading.Event()
    release = threading.Event()
    interrupted = threading.Event()

    class Cancellation:
        def is_set(self):
            return False

        def wait(self, _timeout):
            entered.set()
            release.wait(2)
            return True

    class Response:
        will_close = False
        status = 200

        def read(self):
            return b"ok"

    class Connection:
        sock = object()

        def send(self, _data):
            pass

        def request(self, *args, **kwargs):
            assert entered.wait(2)

        def getresponse(self):
            return Response()

        def close(self):
            interrupted.set()

    client = object.__new__(HubClient)
    connection = Connection()
    client._connection = lambda _timeout: connection
    assert client._pooled_open("POST", "/", b"", {}, 5, cancel_event=Cancellation()) == b"ok"
    release.set()
    assert not interrupted.wait(0.2)
