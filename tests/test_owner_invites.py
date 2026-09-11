import hashlib
import os
import re
import unittest
from unittest.mock import patch

import app
from auth import database, seed_owner_invite
from auth_support import AccountTestMixin


class OwnerInviteTests(AccountTestMixin, unittest.TestCase):
    def test_regular_user_cannot_create_invites(self):
        self.assertEqual(self.client.get('/admin/invites').status_code, 403)
        self.assertEqual(self.client.post('/admin/invites').status_code, 403)

    def test_owner_setup_and_invites(self):
        code = 'owner-setup-' + 'x' * 32
        with app.app.app_context(), patch.dict(os.environ, OWNER_INVITE_CODE=code, RENDER=''):
            seed_owner_invite()
            seed_owner_invite()
        guest = app.app.test_client()
        guest.get('/join')
        with guest.session_transaction() as session:
            token = session['csrf']
        response = guest.post('/join', data={'invite':code,'username':'owner','password':'a strong test password','csrf_token':token})
        self.assertEqual(response.status_code, 302)
        self.assertIn(b'Invite testers', guest.get('/').data)
        with guest.session_transaction() as session:
            token = session['csrf']
        self.assertEqual(guest.post('/admin/invites').status_code, 400)
        response = guest.post('/admin/invites', data={'csrf_token':token})
        self.assertEqual(response.status_code, 200)
        invite = re.search(rb'id="inviteCode"[^>]*value="([^"]+)"', response.data).group(1).decode()
        with app.app.app_context(), database() as db:
            row = db.execute('SELECT used FROM invites WHERE digest=?', (hashlib.sha256(invite.encode()).hexdigest(),)).fetchone()
            self.assertEqual(row['used'], 0)
        # Changing the environment variable cannot bootstrap a second owner.
        with app.app.app_context(), patch.dict(os.environ, OWNER_INVITE_CODE='y' * 40, RENDER=''):
            seed_owner_invite()
            with database() as db:
                self.assertIsNone(db.execute('SELECT digest FROM invites WHERE digest=?', (hashlib.sha256(('y'*40).encode()).hexdigest(),)).fetchone())
