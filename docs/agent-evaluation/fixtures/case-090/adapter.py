"""Legacy tool adapter."""
from sdk import checkpoint

def checkpoint_task(base_url, **fields):
    return checkpoint(base_url, **fields)
