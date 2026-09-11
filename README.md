# RequestAssistant

RequestAssistant is a lightweight Flask-based track downloader with a modern, DJ-focused web interface.

It uses `yt-dlp` to locate and download audio and FFmpeg to convert tracks to high-quality 320 kbps MP3 files.

## Features

- Modern dark DJ-style interface
- Search by artist and track name
- Downloads audio using yt-dlp
- Converts audio to 320 kbps MP3
- Real-time download progress
- Download and conversion status indicators
- Cancel active downloads
- Recent download history
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
