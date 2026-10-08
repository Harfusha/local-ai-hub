from pathlib import Path
import sys, time
Path(sys.argv[1]).write_text('started', encoding='utf-8')
time.sleep(5)
