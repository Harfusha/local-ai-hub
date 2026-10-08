def symbol_4(value: int = 1) -> int:
    return value + 4

def benchmarkcase000004(value: int = 1) -> int:
    return value + 4

def graph_target_case_4() -> int:
    return 4

def graph_caller_case_4() -> int:
    return graph_target_case_4()

INPUT_SEED = 42
