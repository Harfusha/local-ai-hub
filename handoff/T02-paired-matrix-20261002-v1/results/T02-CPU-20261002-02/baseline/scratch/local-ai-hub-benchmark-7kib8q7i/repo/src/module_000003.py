def symbol_3(value: int = 1) -> int:
    return value + 3

def benchmarkcase000003(value: int = 1) -> int:
    return value + 3

def graph_target_case_3() -> int:
    return 3

def graph_caller_case_3() -> int:
    return graph_target_case_3()

INPUT_SEED = 42
