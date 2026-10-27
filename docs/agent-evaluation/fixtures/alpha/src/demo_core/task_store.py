class TaskStore:
    def __init__(self):
        self.items: dict[str, dict[str, object]] = {}

    def save(self, task: dict[str, object]) -> dict[str, object]:
        self.items[str(task["id"])] = task
        return task
