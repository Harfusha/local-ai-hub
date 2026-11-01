"""Conservative name validation for the experimental local OpenCode path."""
import re

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")


def validate_local_model_name(model: str) -> str:
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("invalid model name")
    component = model.rsplit("/", 1)[-1].casefold()
    if component.count(":") > 1:
        raise ValueError("explicit source suffixes are not accepted in model names")
    name, _, tag = component.partition(":")
    if tag == "local":
        raise ValueError("explicit source suffixes are not accepted in model names")
    if name.endswith("-cloud") or tag == "cloud" or tag.endswith("-cloud"):
        raise ValueError("explicit Ollama cloud models are not allowed in the local profile")
    return model
