import app as app_module

client = app_module.app.test_client()
with client.session_transaction() as session:
    session['user'] = 'admin'
    session['role'] = 'admin'

resp = client.get('/dashboard')
print('status', resp.status_code)
html = resp.get_data(as_text=True)
print('contains total', '2214' in html)
print('contains card', 'Total Harvest' in html)
print('contains value', '2214' in html)
