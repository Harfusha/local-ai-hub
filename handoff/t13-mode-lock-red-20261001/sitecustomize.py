import importlib.util
import os
import sys

root_src = r'C:\Users\Adam\.local-ai-hub\src'
sys.path.insert(0, root_src)
import local_ai_hub
module_path = os.environ['T13_OPMODE_PATH']
spec = importlib.util.spec_from_file_location('local_ai_hub.operational_mode', module_path)
module = importlib.util.module_from_spec(spec)
sys.modules['local_ai_hub.operational_mode'] = module
setattr(local_ai_hub, 'operational_mode', module)
spec.loader.exec_module(module)
