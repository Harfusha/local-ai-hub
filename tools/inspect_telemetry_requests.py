import sqlite3
import json

with sqlite3.connect("file:state/debug_traces.sqlite3?mode=ro", uri=True) as con:
    cur = con.cursor()
    row = cur.execute("SELECT * FROM traces WHERE request_id='req_9fcb9a02b8cf' OR trace_id='req_9fcb9a02b8cf'").fetchone()
    print("Trace for req_9fcb9a02b8cf:", row)

with sqlite3.connect("file:state/telemetry.sqlite3?mode=ro", uri=True) as con:
    cur = con.cursor()
    rows = cur.execute("SELECT safe_message, error_type FROM errors WHERE request_id='req_9fcb9a02b8cf'").fetchall()
    print("Errors for req_9fcb9a02b8cf:", rows)

    evs = cur.execute("SELECT id, action, event_type, stage, error_type, duration_ms FROM events WHERE request_id='req_9fcb9a02b8cf'").fetchall()
    print("Events for req_9fcb9a02b8cf:")
    for ev in evs:
        print(ev)
