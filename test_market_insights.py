import app as app_module


def test_market_insights_endpoint_returns_analysis():
    app_module.init_db()
    client = app_module.app.test_client()

    client.post('/register', data={'username': 'insightuser', 'password': 'Password1!'}, follow_redirects=True)
    login_resp = client.post('/login', data={'username': 'insightuser', 'password': 'Password1!'}, follow_redirects=True)
    assert login_resp.status_code == 200

    with client.session_transaction() as session:
        session['user'] = 'insightuser'
        session['role'] = 'user'

    response = client.get('/api/market-insights')
    assert response.status_code == 200
    payload = response.get_json()
    assert 'summary' in payload
    assert 'recommendations' in payload
    assert 'risk_alerts' in payload


def test_forecast_endpoint_returns_projection():
    app_module.init_db()
    client = app_module.app.test_client()

    client.post('/register', data={'username': 'forecastuser', 'password': 'Password1!'}, follow_redirects=True)
    with client.session_transaction() as session:
        session['user'] = 'forecastuser'
        session['role'] = 'user'

    response = client.get('/api/forecast')
    assert response.status_code == 200
    payload = response.get_json()
    assert 'forecast' in payload


def test_analytics_history_is_stored_per_month_and_populates_top_crop_id():
    app_module.init_db()
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM analytics")
    cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
    crop_id = cur.execute("SELECT id FROM crops WHERE crops_name=?", ('Maize',)).fetchone()[0]
    cur.execute("INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)", ('Maize', 15, 'historyuser', '2026-06-10 10:00:00', 'North'))
    cur.execute("INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)", ('Maize', 25, 'historyuser', '2026-07-10 10:00:00', 'South'))
    conn.commit()
    conn.close()

    app_module.update_analytics()

    conn = app_module.get_db()
    cur = conn.cursor()
    analytics_rows = cur.execute(
        "SELECT period_value, total_harvest, top_crop, top_crop_volume, top_crop_id FROM analytics ORDER BY period_value"
    ).fetchall()
    conn.close()

    assert len(analytics_rows) >= 2
    latest_row = [row for row in analytics_rows if row[0] == '2026-07']
    assert latest_row
    assert latest_row[0][1] == 25
    assert latest_row[0][2] == 'Maize'
    assert latest_row[0][3] == 25
    assert latest_row[0][4] == crop_id


def test_analytics_history_preserves_previous_monthly_rows():
    app_module.init_db()
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM analytics")
    cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
    crop_id = cur.execute("SELECT id FROM crops WHERE crops_name=?", ('Maize',)).fetchone()[0]
    cur.execute(
        "INSERT INTO analytics(period_type, period_value, total_harvest, top_crop, top_crop_volume, top_crop_id, top_location, top_location_volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('Monthly', '2026-06', 10, 'Maize', 10, crop_id, 'North', 10)
    )
    cur.execute("INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)", ('Maize', 25, 'historyuser', '2026-07-10 10:00:00', 'South'))
    conn.commit()
    conn.close()

    app_module.update_analytics()

    conn = app_module.get_db()
    cur = conn.cursor()
    analytics_rows = cur.execute(
        "SELECT period_value, total_harvest FROM analytics WHERE period_type=? ORDER BY period_value",
        ('Monthly',)
    ).fetchall()
    conn.close()

    assert ('2026-06', 10) in analytics_rows
    assert ('2026-07', 25) in analytics_rows


def test_dashboard_renders_monthly_analytics_history():
    app_module.init_db()
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM analytics")
    cur.execute("DELETE FROM inventory")
    cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
    crop_id = cur.execute("SELECT id FROM crops WHERE crops_name=?", ('Maize',)).fetchone()[0]
    cur.execute(
        "INSERT INTO analytics(period_type, period_value, total_harvest, top_crop, top_crop_volume, top_crop_id, top_location, top_location_volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('Monthly', '2026-06', 10, 'Maize', 10, crop_id, 'North', 10)
    )
    cur.execute(
        "INSERT INTO analytics(period_type, period_value, total_harvest, top_crop, top_crop_volume, top_crop_id, top_location, top_location_volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('Monthly', '2026-07', 25, 'Maize', 25, crop_id, 'South', 25)
    )
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post('/register', data={'username': 'historyview', 'password': 'Password1!'}, follow_redirects=True)
    client.post('/login', data={'username': 'historyview', 'password': 'Password1!'}, follow_redirects=True)

    response = client.get('/dashboard')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Monthly Analytics History' in html
    assert '2026-06' in html
    assert '2026-07' in html


def test_manual_upload_populates_inventory_for_dashboard():
    app_module.init_db()
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory WHERE farmer=?", ('uploaduser',))
    cur.execute("DELETE FROM analytics")
    cur.execute("DELETE FROM users WHERE username=?", ('uploaduser',))
    conn.commit()
    conn.close()

    client = app_module.app.test_client()

    client.post('/register', data={'username': 'uploaduser', 'password': 'Password1!'}, follow_redirects=True)
    client.post('/login', data={'username': 'uploaduser', 'password': 'Password1!'}, follow_redirects=True)

    with client.session_transaction() as session:
        session['user'] = 'uploaduser'
        session['role'] = 'user'

    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
    conn.commit()
    crop_id = cur.execute("SELECT id FROM crops WHERE crops_name=?", ('Maize',)).fetchone()[0]
    conn.close()

    response = client.post('/upload', data={
        'crop_id': crop_id,
        'manual_quantity': '12',
        'manual_date': '2026-07-13',
    }, follow_redirects=True)
    assert response.status_code == 200

    conn = app_module.get_db()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT SUM(quantity) AS total FROM inventory WHERE farmer=? AND crop_name=?",
        ('uploaduser', 'Maize')
    ).fetchone()
    conn.close()

    assert row[0] == 12

    conn = app_module.get_db()
    cur = conn.cursor()
    analytics_row = cur.execute(
        "SELECT total_harvest, top_location, top_location_volume FROM analytics WHERE period_type=? ORDER BY period_value DESC LIMIT 1",
        ('Monthly',)
    ).fetchone()
    inventory_total = cur.execute("SELECT SUM(quantity) FROM inventory").fetchone()[0]
    conn.close()

    assert analytics_row is not None
    assert analytics_row[0] == inventory_total


def test_yearly_analytics_is_created_and_preserved():
    app_module.init_db()
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM analytics")
    cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", ('Maize',))
    cur.execute(
        "INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)",
        ('Maize', 10, 'historyuser', '2025-12-31 10:00:00', 'North')
    )
    cur.execute(
        "INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)",
        ('Maize', 25, 'historyuser', '2026-01-10 10:00:00', 'South')
    )
    conn.commit()
    conn.close()

    app_module.update_analytics()

    conn = app_module.get_db()
    cur = conn.cursor()
    yearly_rows = cur.execute(
        "SELECT period_value, total_harvest FROM analytics WHERE period_type=? ORDER BY period_value",
        ('Yearly',)
    ).fetchall()
    conn.close()

    assert ('2025', 10) in yearly_rows
    assert ('2026', 25) in yearly_rows
