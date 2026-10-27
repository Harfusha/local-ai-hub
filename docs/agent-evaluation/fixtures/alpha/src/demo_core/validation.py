def validate_mode(value: str) -> bool:
    return value in {"safe", "strict"}
