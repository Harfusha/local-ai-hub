import sqlite3

for db_name in ["preprocess.sqlite3", "deterministic.sqlite3", "evidence.sqlite3", "code-index.sqlite3", "telemetry.sqlite3"]:
    print(f"\n==================== {db_name} ====================")
    try:
        con = sqlite3.connect(f"file:state/{db_name}?mode=ro", uri=True)
        cur = con.cursor()
        tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (t,) in tables:
            try:
                cnt = cur.execute(f"SELECT count(*) FROM [{t}]").fetchone()[0]
                cols = [c[1] for c in cur.execute(f"PRAGMA table_info([{t}])").fetchall()]
                print(f"  {t:<28}: {cnt:>8} rows | cols: {', '.join(cols[:6])}")
            except Exception as e:
                print(f"  {t:<28}: error {e}")
    except Exception as e:
        print(f"  Cannot open {db_name}: {e}")
