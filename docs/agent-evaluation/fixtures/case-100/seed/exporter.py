"""Deliberately broken encoding and cancellation behavior."""
import csv
from pathlib import Path

class ExportCancelled(Exception):
    pass

def export(path, rows, cancelled=lambda: False):
    path = Path(path)
    if cancelled():
        path.with_name(path.name + '.duplicate').write_bytes(b'partial')
        raise ExportCancelled()
    with path.open('w', encoding='ascii', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['id', 'name'])
        for row in rows:
            writer.writerow([row['id'], row['name']])
