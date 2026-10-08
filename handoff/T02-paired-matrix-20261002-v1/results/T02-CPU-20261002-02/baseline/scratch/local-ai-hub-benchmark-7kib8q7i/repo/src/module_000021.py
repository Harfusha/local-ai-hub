def symbol_21(value: int = 1) -> int:
    return value + 21

def benchmarkcase000021(value: int = 1) -> int:
    return value + 21

def graph_target_case_21() -> int:
    return 21

def graph_caller_case_21() -> int:
    return graph_target_case_21()

INPUT_SEED = 42
