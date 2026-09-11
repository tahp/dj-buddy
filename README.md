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

Create your first invite with `.venv/bin/flask --app app invite`, then open
http://127.0.0.1:5000/join and choose a username and password.
Once signed in, search for a track, preview a result inside the app,
and click **Prepare MP3** on the version you want. When conversion finishes,
click **Save to device** and check your browser downloads. Conversion alone
does not save the file locally.

Run API checks with:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Render deployment preparation

Use the **Docker** runtime with the repository root left blank. Render builds
`Dockerfile` and uses its default command; no separate build or start command
is needed. The image includes FFmpeg, yt-dlp, and Gunicorn.

For stored files to survive redeploys, attach a persistent disk at `/var/data`
and set `DATA_DIR=/var/data`. Without a disk, downloads are temporary.

This configuration must run **one Gunicorn worker and one service instance**.
That process runs a serial queue, while SQLite persists jobs on the disk.
Queued jobs resume after restart; interrupted running jobs are marked failed
with a retry message. The page restores your latest job after refresh.

Beta defaults: 3 queued/active jobs per account, 20 globally, one conversion
at a time, tracks up to 15 minutes, a 10-minute processing timeout, 200 MB
maximum source audio, and 500 MB of temporary MP3s per account. Temporary server MP3s expire after one hour; finished job records expire after
seven days. Saving a file does not immediately delete the server copy, allowing
transfer retries within the hour. The browser does not report whether the user
actually saved the file, so the app never claims it is saved. Legacy unowned files are
left untouched. Limits are enforced by the server, not just the interface.


## Beta accounts

Accounts require a single-use invite code, valid for seven days. Generate one
in the same environment and with the same `DATA_DIR` as the running app:

```bash
.venv/bin/flask --app app invite
```

On Render, use `flask --app app invite` in the service shell. Share the code
privately along with the app's `/join` page. Each tester chooses their own
username and password. No email service is required.

Set a random `SECRET_KEY` environment variable in Render before starting the
service. The app refuses to start on Render without it. Use a password manager
to generate a long random value. Keep it stable across deployments; changing
it signs everyone out. Render sessions use HTTPS-only cookies.

Accounts and invite records live in `DATA_DIR/accounts.sqlite3`, alongside
user-specific download folders. Attach the persistent disk before creating
accounts. Keep the database and session secret out of Git and Docker images.

Revoke an account and its existing sessions with:

```bash
.venv/bin/flask --app app disable-user USERNAME
```

Existing files directly under `downloads/` are retained but not exposed to
new accounts. They have no recorded owner and are not automatically assigned.
The beta does not yet have a self-service password reset flow.

Files saved to a device play offline without this server. Server storage is only
for conversion and short transfer retries. On ephemeral hosting, a restart may
remove temporary files earlier than the one-hour expiry; persistent account
storage is still needed to retain users and invitations.
