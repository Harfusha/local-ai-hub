import local_ai_hub.operational_mode as operational_mode

def no_retry(source, target):
    operational_mode.os.replace(source, target)

operational_mode._replace_with_retry = no_retry
