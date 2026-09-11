import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from auth_support import AccountTestMixin


class QueueTests(AccountTestMixin, unittest.TestCase):
    def enqueue(self):
        response = self.client.post('/jobs', json={'song_title':'Track', 'video_id':'abcdefghijk'})
        self.assertEqual(response.status_code, 200)
        return app.jobs[response.json['job_id']]

    def test_queue_persists_and_interruption_is_visible(self):
        queued = self.enqueue()
        running = self.enqueue()
        with app.app.app_context():
            app.update_job(running, status='running')
            Path(running['final_path']).write_bytes(b'partial')
            app.recover_jobs()
        self.assertEqual(app.jobs[queued['id']]['status'], 'queued')
        self.assertEqual(app.jobs[running['id']]['status'], 'error')
        self.assertFalse(Path(running['final_path']).exists())
        self.assertEqual(self.client.get('/jobs/current').json['job_id'], queued['id'])

    def test_user_and_global_queue_limits(self):
        for _ in range(3):
            self.enqueue()
        self.assertEqual(self.client.post('/jobs', json={'song_title':'Extra', 'video_id':'abcdefghijk'}).status_code, 429)
        with patch.dict(app.app.config, MAX_QUEUE_JOBS=3):
            bob = self.account_client('bob')
            self.assertEqual(bob.post('/jobs', json={'song_title':'Extra', 'video_id':'abcdefghijk'}).status_code, 429)

    def test_cancelled_queue_job_does_not_resume(self):
        job = self.enqueue()
        self.assertEqual(self.client.post('/cancel/' + job['id']).status_code, 200)
        with app.app.app_context():
            app.recover_jobs()
        self.assertEqual(app.jobs[job['id']]['status'], 'cancelled')
        self.assertEqual(self.client.post('/cancel/' + job['id']).status_code, 409)

    def test_storage_limit_and_expiry(self):
        job = self.enqueue()
        output = Path(job['final_path'])
        output.write_bytes(b'audio')
        job['status'] = 'completed'
        with patch.dict(app.app.config, MAX_STORED_BYTES=4):
            self.assertEqual(self.client.post('/jobs', json={'song_title':'Extra', 'video_id':'abcdefghijk'}).status_code, 429)
        old = time.time() - 8 * 86400
        os.utime(output, (old, old))
        with app.app.app_context():
            app.expire_files()
        self.assertFalse(output.exists())
        self.assertFalse(self.client.get('/status/' + job['id']).json['file_available'])

    def test_duplicate_titles_get_separate_files(self):
        self.assertNotEqual(self.enqueue()['final_path'], self.enqueue()['final_path'])

    def test_timeout_kills_process_and_removes_partial_files(self):
        job = self.enqueue()
        job['deadline'] = time.monotonic() - 1
        with app.app.app_context():
            with self.assertRaisesRegex(RuntimeError, 'processing limit'):
                app.run_process(job, ['python3', '-c', 'import time; time.sleep(60)'])
        self.assertIsNone(job['process'])

    def test_failed_worker_cleans_up(self):
        job = self.enqueue()
        temp = Path(app.TEMP_DIR) / job['id']
        temp.mkdir(parents=True)
        (temp / 'audio.part').write_bytes(b'incomplete')
        Path(job['final_path']).write_bytes(b'incomplete')
        with app.app.app_context(), patch('app.run_process', side_effect=RuntimeError('Source unavailable')):
            app.download_worker(job)
        self.assertEqual(job['status'], 'error')
        self.assertFalse(temp.exists())
        self.assertFalse(Path(job['final_path']).exists())
