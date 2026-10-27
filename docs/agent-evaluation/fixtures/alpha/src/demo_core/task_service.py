from .task_store import TaskStore


class TaskService:
    def __init__(self, store: TaskStore):
        self.store = store

    def create_task(self, payload: dict[str, object]) -> dict[str, object]:
        task = {"id": str(payload["name"]), "state": "planned"}
        return self.store.save(task)
