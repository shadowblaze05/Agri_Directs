import sqlite3
import os
import app as app_module

print('db path', app_module.DB_PATH)
print('db exists', os.path.exists(app_module.DB_PATH))
conn = sqlite3.connect(app_module.DB_PATH)
cur = conn.cursor()
print('tables', cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
for table in ['inventory', 'harvest', 'crops', 'users', 'analytics']:
    try:
        count = cur.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(table, count)
    except Exception as exc:
        print(table, 'ERR', exc)
cur.execute("SELECT * FROM analytics LIMIT 5")
print('analytics sample', cur.fetchall())
conn.close()
