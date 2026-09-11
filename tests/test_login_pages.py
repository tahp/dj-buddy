"""Smoke-test the public entry pages using a fresh, isolated account database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LoginPageTests(unittest.TestCase):
    def test_login_and_join_render_in_clean_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-c', '''
import app
app.app.config['TESTING'] = True
client = app.app.test_client()
for path in ('/login', '/join'):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    assert b'name="csrf_token"' in response.data
    assert b'name="password"' in response.data
assert client.get('/').status_code == 302
assert client.get('/static/css/style.css').status_code == 200
'''],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, 'DATA_DIR': directory, 'DATABASE_URL': '', 'OWNER_INVITE_CODE': ''},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
