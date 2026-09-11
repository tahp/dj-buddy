# RequestAssistant

RequestAssistant is a lightweight Flask-based track downloader with a modern, DJ-focused web interface.

It uses `yt-dlp` to locate and download audio and FFmpeg to convert tracks to 320 kbps MP3 files. Output quality depends on the source; conversion does not restore missing audio detail.

## Features

- Modern dark DJ-style interface
- Search by artist and track name, compare five results, and choose the exact version
- Preview each result in an embedded YouTube player before downloading
- Downloads audio using yt-dlp
- Converts audio to 320 kbps MP3
- Real-time download progress
- Download and conversion status indicators
- Cancel active downloads
- Recent download history with per-track deletion
- Expandable technical log
- Mobile-friendly interface
- Unique temporary files for concurrent downloads

## Requirements

- Python 3
- Flask
- yt-dlp
- FFmpeg

## Installation

Clone the repository:

```bash
git clone https://github.com/tahp/dj-buddy.git
cd dj-buddy

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Install the audio tools on macOS with Homebrew:

```bash
brew install yt-dlp ffmpeg
```

Start from the project folder:

```bash
.venv/bin/python app.py
```

Open http://127.0.0.1:5000, search for a track, preview a result inside the app,
and click **Download MP3** on the version you want.

Run API checks with:

```bash
.venv/bin/python -m unittest discover -s tests
```
