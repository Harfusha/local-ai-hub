import local_ai_hub.http_server as http_server

http_server._ActiveTranscriptionRegistry.enter_gaming = lambda self: None
http_server._ActiveTranscriptionRegistry.cancel_and_wait = lambda self, timeout_seconds: {"state": "cancelled", "inference_active": False, "active": 1, "cancelled": True}
