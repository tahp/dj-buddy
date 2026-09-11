import os
import time
import unittest
from pathlib import Path

import app
from auth_support import AccountTestMixin


class DeviceDownloadTests(AccountTestMixin, unittest.TestCase):
    def ready_job(self):
        response = self.client.post('/jobs', json={'song_title': 'Track', 'video_id': 'abcdefghijk'})
        job = app.jobs[response.json['job_id']]
        Path(job['final_path']).write_bytes(b'mp3 test content')
        with app.app.app_context():
            app.update_job(job, status='completed', stage='completed')
        return job

    def test_save_is_attachment_and_can_be_retried(self):
        job = self.ready_job()
        for _ in range(2):
            response = self.client.get('/download/' + job['filename'])
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.data, b'mp3 test content')
            response.close()
        self.assertTrue(Path(job['final_path']).exists())
        self.assertIn('expires_at', self.client.get('/history').json[0])

    def test_expiry_hides_file_before_cleanup_and_preserves_job(self):
        job = self.ready_job()
        path = Path(job['final_path'])
        old = time.time() - 3601
        os.utime(path, (old, old))
        self.assertEqual(self.client.get('/history').json, [])
        self.assertFalse(self.client.get('/status/' + job['id']).json['file_available'])
        self.assertEqual(self.client.get('/download/' + job['filename']).status_code, 404)
        with app.app.app_context():
            app.expire_files()
        self.assertFalse(path.exists())
        self.assertIn(job['id'], app.jobs)

    def test_active_file_cannot_be_saved_or_expired(self):
        job = self.ready_job()
        job['status'] = 'running'
        path = Path(job['final_path'])
        old = time.time() - 3601
        os.utime(path, (old, old))
        self.assertEqual(self.client.get('/history').json, [])
        self.assertEqual(self.client.get('/download/' + job['filename']).status_code, 404)
        with app.app.app_context():
            app.expire_files()
        self.assertTrue(path.exists())

    def test_interface_separates_preparation_from_saving(self):
        page = self.client.get('/').data
        self.assertIn(b'MP3 ready to save', page)
        self.assertIn(b'Save to device', page)
        self.assertIn(b'not saved to this device yet', page)
