import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import app


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_search_returns_choices_without_starting_download(self):
        result = Mock(stdout=json.dumps({"entries": [
            {"id": "abcdefghijk", "title": "Track", "uploader": "Artist", "duration": 123},
            None, {"id": "bad"}
        ]}))
        with patch("app.subprocess.run", return_value=result), patch("app.threading.Thread") as worker:
            response = self.client.post("/search", json={"song_title": "Track"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["results"]), 1)
        self.assertEqual(response.json["results"][0]["duration"], 123)
        worker.assert_not_called()

    def test_download_uses_selected_video(self):
        with patch("app.threading.Thread"):
            response = self.client.post("/jobs", json={"song_title": "Track", "video_id": "abcdefghijk"})
        self.assertEqual(response.status_code, 200)
        job = app.jobs.pop(response.json["job_id"])
        self.assertEqual(job["source_url"], "https://www.youtube.com/watch?v=abcdefghijk")

    def test_invalid_inputs(self):
        for payload in [[], {}, {"song_title": 42}, {"song_title": " "}]:
            self.assertEqual(self.client.post("/search", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/jobs", json={"song_title": "Track", "video_id": "https://example.com"}).status_code, 400)

    def test_search_errors(self):
        for error, status in [(FileNotFoundError(), 503),
                              (subprocess.TimeoutExpired("yt-dlp", 40), 504),
                              (subprocess.CalledProcessError(1, "yt-dlp"), 502)]:
            with patch("app.subprocess.run", side_effect=error):
                self.assertEqual(self.client.post("/search", json={"song_title": "Track"}).status_code, status)
