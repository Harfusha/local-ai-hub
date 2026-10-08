def symbol_12(value: int = 1) -> int:
    return value + 12

def benchmarkcase000012(value: int = 1) -> int:
    return value + 12

def graph_target_case_12() -> int:
    return 12

def graph_caller_case_12() -> int:
    return graph_target_case_12()

INPUT_SEED = 42
