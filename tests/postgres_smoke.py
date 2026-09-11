"""Run against a disposable local Postgres database, never a production database."""
import os
import re
import tempfile
from urllib.parse import urlparse

assert urlparse(os.environ['DATABASE_URL']).hostname in ('127.0.0.1', 'localhost')
os.environ['OWNER_INVITE_CODE'] = 'temporary-owner-test-code-' + 'x' * 32
with tempfile.TemporaryDirectory() as directory:
    os.environ['DATA_DIR'] = directory
    import app
    from auth import database, seed_owner_invite
    app.app.config['TESTING'] = True
    client = app.app.test_client()
    client.get('/join')
    with client.session_transaction() as session:
        token = session['csrf']
    r = client.post('/join', data={'invite':os.environ['OWNER_INVITE_CODE'], 'username':'owner', 'password':'a test password here', 'csrf_token':token})
    assert r.status_code == 302, r.data
    assert b'Invite testers' in client.get('/').data
    with client.session_transaction() as session:
        token = session['csrf']
    client.environ_base['HTTP_X_CSRF_TOKEN'] = token
    r = client.post('/admin/invites')
    assert r.status_code == 200
    code = re.search(rb'id="inviteCode"[^>]*value="([^"]+)"', r.data).group(1).decode()
    guest = app.app.test_client()
    guest.get('/join')
    with guest.session_transaction() as session:
        guest_token = session['csrf']
    # Duplicate username rolls back the invite claim so it can still be used.
    data = {'invite':code, 'username':'owner', 'password':'another test password', 'csrf_token':guest_token}
    assert b'already taken' in guest.post('/join', data=data).data
    data['username'] = 'tester'
    assert guest.post('/join', data=data).status_code == 302
    assert guest.get('/admin/invites').status_code == 403
    r = client.post('/jobs', json={'song_title':'Test', 'video_id':'abcdefghijk'})
    assert r.status_code == 200
    job_id = r.json['job_id']
    with app.app.app_context():
        app.recover_jobs()
        seed_owner_invite()
    assert client.get('/status/' + job_id).status_code == 200
    assert guest.get('/status/' + job_id).status_code == 404
    assert client.post('/cancel/' + job_id).status_code == 200
    client.post('/logout')
    client.get('/login')
    with client.session_transaction() as session:
        token = session['csrf']
    client.environ_base['HTTP_X_CSRF_TOKEN'] = token
    for password in ('wrong', 'a test password here'):
        response = client.post('/login', data={'username':'owner', 'password':password})
        assert response.status_code == (302 if password != 'wrong' else 200)
    print('Postgres schema, owner setup, signup rollback, invites, login, job persistence, and account isolation passed.')
