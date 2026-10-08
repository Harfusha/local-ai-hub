def symbol_2(value: int = 1) -> int:
    return value + 2

def benchmarkcase000002(value: int = 1) -> int:
    return value + 2

def graph_target_case_2() -> int:
    return 2

def graph_caller_case_2() -> int:
    return graph_target_case_2()

INPUT_SEED = 42
