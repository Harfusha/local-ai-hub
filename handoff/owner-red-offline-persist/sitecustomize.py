import local_ai_hub.operational_mode as operational_mode

def no_persist(state_dir, mode):
    return operational_mode.OperationalModeSnapshot(mode, 0)

operational_mode.set_operational_mode = no_persist
