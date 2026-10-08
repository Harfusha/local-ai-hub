def symbol_13(value: int = 1) -> int:
    return value + 13

def benchmarkcase000013(value: int = 1) -> int:
    return value + 13

def graph_target_case_13() -> int:
    return 13

def graph_caller_case_13() -> int:
    return graph_target_case_13()

INPUT_SEED = 42
