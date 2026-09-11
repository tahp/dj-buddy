import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_support import register_desktop_routes, set_output_directory


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, DJ_BUDDY_DESKTOP='1', DATA_DIR=self.tmp.name):
            spec = importlib.util.spec_from_file_location('desktop_test_app', Path(__file__).resolve().parents[1] / 'app.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.app = self.module.app
        self.app.config.update(TESTING=True, DESKTOP_HOST='localhost')
        self.window = Mock()
        register_desktop_routes(self.module, self.window)
        self.client = self.app.test_client()
        self.client.get('/desktop/start?token=' + self.app.config['DESKTOP_TOKEN'])
        with self.client.session_transaction() as session:
            self.csrf = session['csrf']
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = self.csrf
        self.output = Path(self.tmp.name).resolve() / 'Music'
        self.output.mkdir()
        with self.app.app_context():
            set_output_directory(self.output)

    def enqueue(self):
        response = self.client.post('/jobs', json={'song_title': 'A track', 'video_id': 'abcdefghijk'})
        self.assertEqual(response.status_code, 200)
        return self.module.jobs[response.json['job_id']]

    def complete(self, job):
        def tools(current, command):
            temp = Path(self.module.TEMP_DIR) / job['id']
            if '--write-info-json' in command:
                (temp / 'audio.info.json').write_text(json.dumps({'duration': 2000}))
            elif '-f' in command:
                (temp / 'audio.webm').write_bytes(b'audio')
            else:
                Path(job['final_path']).write_bytes(b'converted MP3')
        with patch.object(self.module, 'run_process', side_effect=tools):
            self.module.download_worker(job)

    def test_local_session_csrf_host_and_origin_required(self):
        stranger = self.app.test_client()
        self.assertEqual(stranger.get('/').status_code, 403)
        self.assertEqual(stranger.get('/desktop/start?token=wrong').status_code, 403)
        self.assertEqual(stranger.get('/desktop/start?token=' + self.app.config['DESKTOP_TOKEN']).status_code, 403)
        self.assertEqual(self.client.get('/history', headers={'Host': 'attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/jobs', json={}, headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/jobs', json={}, headers={'X-CSRF-Token': ''}).status_code, 403)
        page = self.client.get('/').data
        self.assertIn(b'Choose folder', page)
        self.assertNotIn(b'Sign out', page)
        self.assertNotIn(b'not saved to this device yet', page)
        self.assertNotIn(b'Private beta', page)

    def test_download_saved_permanently_and_survives_restart(self):
        job = self.enqueue()
        self.complete(job)
        self.assertEqual(job['status'], 'completed', job['error'])
        saved = self.output / job['filename']
        self.assertEqual(saved.read_bytes(), b'converted MP3')
        self.assertFalse(Path(job['final_path']).exists())
        os.utime(saved, (1, 1))
        with self.app.app_context():
            self.module.expire_files()
            self.module.recover_jobs()
        self.assertTrue(saved.exists())
        self.assertEqual(self.client.get('/history').json[0]['saved_path'], str(saved))
        self.assertTrue(self.client.get('/status/' + job['id']).json['file_available'])
        self.assertEqual(self.client.delete('/delete/' + job['filename']).status_code, 404)
        self.assertTrue(saved.exists())

    def test_collision_does_not_overwrite_existing_music(self):
        job = self.enqueue()
        saved = self.output / job['filename']
        saved.write_bytes(b'existing music')
        self.complete(job)
        self.assertEqual(job['status'], 'error')
        self.assertEqual(saved.read_bytes(), b'existing music')
        self.assertEqual(self.client.get('/history').json, [])

    def test_job_remembers_destination_and_folder_dialog_cancellation(self):
        job = self.enqueue()
        other = Path(self.tmp.name).resolve() / 'Other'
        other.mkdir()
        self.window.create_file_dialog.return_value = [str(other)]
        self.assertEqual(self.client.post('/desktop/folder').json['output_directory'], str(other))
        self.window.create_file_dialog.return_value = None
        self.assertEqual(self.client.post('/desktop/folder').json['output_directory'], str(other))
        self.complete(job)
        self.assertTrue((self.output / job['filename']).exists())
        self.assertEqual(self.enqueue()['output_directory'], str(other))

    def test_failed_conversion_never_publishes_a_file(self):
        job = self.enqueue()
        with patch.object(self.module, 'run_process', side_effect=RuntimeError('Unavailable')):
            self.module.download_worker(job)
        self.assertEqual(job['status'], 'error')
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(self.client.get('/status/' + job['id']).json['file_available'])
