class HubClient:
    def checkpoint_task(self, task_id: str, checkpoint: dict[str, object]) -> dict[str, object]:
        """Send one nested checkpoint object."""
        return {"task_id": task_id, "checkpoint": checkpoint}
