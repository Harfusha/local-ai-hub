from demo_core.task_service import TaskService


def post_task(request, service: TaskService):
    payload = request.json
    return service.create_task(payload)


def checkpoint_task(task_id: str, checkpoint: dict[str, object]) -> dict[str, object]:
    """Canonical nested checkpoint API."""
    return {"task_id": task_id, "checkpoint": checkpoint}
