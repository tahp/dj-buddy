import tempfile
from pathlib import Path
from unittest.mock import patch

import app
from auth import database, initialize_database
from werkzeug.security import generate_password_hash


class AccountTestMixin:
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch_config = patch.dict(app.app.config, TESTING=True, DATABASE_URL=None, AUTH_DATABASE=str(Path(tmp.name) / 'accounts.sqlite3'))
        self.patch_config.start()
        self.addCleanup(self.patch_config.stop)
        self.patch_downloads = patch.object(app, 'DOWNLOADS_DIR', str(Path(tmp.name) / 'downloads'))
        self.patch_downloads.start()
        self.addCleanup(self.patch_downloads.stop)
        temp_patch = patch.object(app, "TEMP_DIR", str(Path(tmp.name) / "temp"))
        temp_patch.start()
        self.addCleanup(temp_patch.stop)
        self.addCleanup(app.jobs.clear)
        with app.app.app_context():
            initialize_database()
            with database() as db:
                for uid in ['alice', 'bob']:
                    db.execute('INSERT INTO users(id, username, password_hash) VALUES (?,?,?)',
                               (uid, uid, generate_password_hash('correct password')))
        self.client = self.account_client('alice')

    def account_client(self, uid):
        client = app.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = uid
            session['csrf'] = 'test-token'
        client.environ_base['HTTP_X_CSRF_TOKEN'] = 'test-token'
        return client
