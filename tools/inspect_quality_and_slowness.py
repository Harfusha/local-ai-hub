import sqlite3

with sqlite3.connect("file:state/telemetry.sqlite3?mode=ro", uri=True) as con:
    cur = con.cursor()
    rows = cur.execute("SELECT id, created_at, component, operation, error_type, safe_message FROM errors WHERE error_type='MCPSoftTimeoutError'").fetchall()
    print("MCPSoftTimeoutError records:", len(rows))
    for r in rows:
        print(r)
