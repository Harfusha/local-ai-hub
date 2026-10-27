# Old checkpoint example

The example below uses the retired flat keyword shape:

    client.checkpoint_task(task_id="job-1", phase="running", next_action="save")

The current HubClient method expects one nested checkpoint object.
