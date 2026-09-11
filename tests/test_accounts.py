import hashlib
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from auth import database
from auth_support import AccountTestMixin


class AccountTests(AccountTestMixin, unittest.TestCase):
    def csrf(self, client):
        client.get('/login')
        with client.session_transaction() as session:
            return session['csrf']

    def test_private_endpoints_require_login(self):
        guest = app.app.test_client()
        self.assertEqual(guest.get('/').status_code, 302)
        for url in ['/history', '/status/unknown']:
            self.assertEqual(guest.get(url).status_code, 401)
        for url in ['/search', '/jobs', '/cancel/unknown']:
            self.assertEqual(guest.post(url, json={}).status_code, 401)
        self.assertEqual(guest.delete('/delete/song.mp3').status_code, 401)
        self.assertEqual(guest.get('/health').status_code, 200)

    def test_users_cannot_access_each_others_files_or_jobs(self):
        bob = self.account_client('bob')
        with patch('app.threading.Thread'):
            response = self.client.post('/jobs', json={'song_title':'Alice track', 'video_id':'abcdefghijk'})
        job = app.jobs[response.json['job_id']]
        path = Path(job['final_path'])
        path.write_bytes(b'private audio')
        job['status'] = 'completed'
        self.assertEqual(len(self.client.get('/history').json), 1)
        self.assertEqual(bob.get('/history').json, [])
        self.assertEqual(bob.get('/download/' + job['filename']).status_code, 404)
        self.assertEqual(bob.delete('/delete/' + job['filename']).status_code, 404)
        self.assertEqual(bob.get('/status/' + job['id']).status_code, 404)
        self.assertEqual(bob.post('/cancel/' + job['id']).status_code, 404)
        self.assertEqual(bob.get('/download/..%2Falice%2FAlice%20track.mp3').status_code, 404)
        self.assertTrue(path.exists())
        response = self.client.get('/download/' + job['filename'])
        self.assertEqual(response.data, b'private audio')
        response.close()
        self.assertEqual(self.client.delete('/delete/' + job['filename']).status_code, 200)
        self.assertFalse(path.exists())

    def test_csrf_and_logout(self):
        self.assertEqual(self.client.post('/jobs', headers={'X-CSRF-Token':'wrong'}, json={}).status_code, 400)
        self.assertEqual(self.client.post('/logout').status_code, 302)
        self.assertEqual(self.client.get('/history').status_code, 401)

    def test_login_and_account_revocation(self):
        guest = app.app.test_client()
        token = self.csrf(guest)
        response = guest.post('/login', data={'username':'alice', 'password':'wrong', 'csrf_token':token})
        self.assertIn(b'Incorrect username', response.data)
        response = guest.post('/login', data={'username':'alice', 'password':'correct password', 'csrf_token':token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(guest.get('/history').status_code, 200)
        with app.app.app_context(), database() as db:
            db.execute('UPDATE users SET active=0 WHERE id="alice"')
        self.assertEqual(guest.get('/history').status_code, 401)

    def test_invite_is_single_use_and_password_is_hashed(self):
        with app.app.app_context(), database() as db:
            db.execute('INSERT INTO invites(digest, expires) VALUES (?,?)',
                       (hashlib.sha256(b'invitation').hexdigest(), time.time()+3600))
        guest = app.app.test_client()
        data = {'invite':'invitation', 'username':'charlie', 'password':'a long new password', 'csrf_token':self.csrf(guest)}
        self.assertEqual(guest.post('/join', data=data).status_code, 302)
        with app.app.app_context(), database() as db:
            user = db.execute('SELECT * FROM users WHERE username="charlie"').fetchone()
        self.assertNotEqual(user['password_hash'], data['password'])
        other = app.app.test_client()
        data.update(username='david', csrf_token=self.csrf(other))
        self.assertIn(b'already used', other.post('/join', data=data).data)

    def test_login_throttle(self):
        guest = app.app.test_client()
        data = {'username':'nobody', 'password':'wrong', 'csrf_token':self.csrf(guest)}
        for _ in range(10):
            self.assertEqual(guest.post('/login', data=data).status_code, 200)
        self.assertEqual(guest.post('/login', data=data).status_code, 429)
