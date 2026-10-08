def symbol_5(value: int = 1) -> int:
    return value + 5

def benchmarkcase000005(value: int = 1) -> int:
    return value + 5

def graph_target_case_5() -> int:
    return 5

def graph_caller_case_5() -> int:
    return graph_target_case_5()

INPUT_SEED = 42
