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

For Render Free, set `DATABASE_URL` to an external Postgres connection string
(for example Neon). Account, invitation, and job records persist there; music
stays temporary in `/tmp/data` and is saved to users’ devices. No persistent
music disk is required. Without `DATABASE_URL`, local SQLite is used and will
not survive an ephemeral server restart.

This configuration must run **one Gunicorn worker and one service instance**.
That process runs a serial queue, while the configured database persists jobs.
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

For Render Free, use the owner setup below instead of Shell. After setup,
click **Invite testers** in the app to generate codes. Share each code privately
with the `/join` page. Each tester chooses their own username and password.
No email service is required.

Set a random `SECRET_KEY` environment variable in Render before starting the
service. The app refuses to start on Render without it. Use a password manager
to generate a long random value. Keep it stable across deployments; changing
it signs everyone out. Render sessions use HTTPS-only cookies.

With `DATABASE_URL`, accounts, invites, and job records live in Postgres.
Without it, they live in `DATA_DIR/accounts.sqlite3`. Connecting a new database
does not migrate existing SQLite accounts; use owner setup to create the first
account in the new database. Keep credentials out of Git and Docker images.

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

## First owner account on Render Free (no Shell needed)

1. Create an external Postgres database such as a Neon Free project. Copy its
   connection string, keeping its TLS parameters (including `sslmode`).
2. In Render → service → Environment, add `DATABASE_URL` with that connection
   string. Keep your existing `SECRET_KEY` stable.
3. Add `OWNER_INVITE_CODE`: use a password manager to generate a unique random
   string of at least 32 characters. Save it privately. This code grants owner
   access to the first account that redeems it; do not share it with testers.
4. Save the environment changes and deploy. Open `/join`, use that code, and
   choose your owner username and password. Then remove `OWNER_INVITE_CODE`
   from Render's environment. The owner account remains in the database.
5. Sign in and choose **Invite testers** to generate ordinary single-use codes.

Owner setup is recorded once in the database. Restarting or changing the
setup-code variable cannot create another owner. The owner code expires in
seven days, like regular invites. Store it securely and complete setup promptly.
On Render, owner setup requires `DATABASE_URL` to prevent ephemeral storage
from resetting the bootstrap protection.

The app still requires one service instance/worker. A shared Postgres database
does not make the in-memory queue safe for multiple instances. This beta does
not include a browser password-reset or account-revocation interface yet.
