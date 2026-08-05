import sqlite3
import app as app_module
app_module.init_db()
conn = sqlite3.connect('database.db')
cur = conn.cursor()
cur.execute("DELETE FROM inventory WHERE farmer=?", ('uploaduser',))
cur.execute("DELETE FROM analytics")
cur.execute("DELETE FROM users WHERE username=?", ('uploaduser',))
conn.commit()
conn.close()

client = app_module.app.test_client()
client.post('/register', data={'username':'uploaduser','password':'Password1!'}, follow_redirects=True)
client.post('/login', data={'username':'uploaduser','password':'Password1!'}, follow_redirects=True)
with client.session_transaction() as session:
    session['user'] = 'uploaduser'
    session['role'] = 'user'

conn = sqlite3.connect('database.db')
cur = conn.cursor()
cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
conn.commit()
crop_id = cur.execute("SELECT id FROM crops WHERE crops_name=?", ('Maize',)).fetchone()[0]
conn.close()
response = client.post('/upload', data={'crop_id':crop_id,'manual_quantity':'12','manual_date':'2026-07-13'}, follow_redirects=True)
print('status', response.status_code)
conn = sqlite3.connect('database.db')
cur = conn.cursor()
print('inventory rows', cur.execute("SELECT id, crop_name, quantity, farmer, date_received, location FROM inventory ORDER BY id").fetchall())
print('analytics rows', cur.execute("SELECT id, period_type, period_value, total_harvest, top_crop, top_location FROM analytics ORDER BY period_type, period_value").fetchall())
print('latest monthly query', cur.execute("SELECT total_harvest, top_location, top_location_volume FROM analytics WHERE period_type=? ORDER BY period_value DESC LIMIT 1", ('Monthly',)).fetchone())
print('inventory total', cur.execute("SELECT SUM(quantity) FROM inventory").fetchone()[0])
conn.close()
