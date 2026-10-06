import local_ai_hub.http_server as http_server
import local_ai_hub.async_jobs as async_jobs

def cancel_without_wait(self, timeout_seconds):
    with self._condition:
        active = tuple(self._active)
        self._waiting.update(active)
        for event in self._active.values():
            event.set()
    return {"state": "cancelled", "inference_active": False, "active": len(active), "cancelled": True}

http_server._ActiveTranscriptionRegistry.cancel_and_wait = cancel_without_wait
async_jobs.AsyncJobManager.wait_for_inference_actions = lambda self, actions, timeout_seconds: True
async_jobs.AsyncJobManager.inference_actions_active = lambda self, **kwargs: False
