# DJ Buddy desktop

A local desktop app for macOS (Apple Silicon and Intel) and Windows x64.
Search, preview, and download an MP3 directly into your music folder. No account,
invitation, Python installation, or Render connection is needed in packaged builds.
Internet access is required for search, previews, and new downloads.

## Use the app

Extract the matching ZIP. On macOS, move **DJ Buddy.app** into Applications.
On Windows, keep the entire **DJ Buddy** folder together and open **DJ Buddy.exe**.
Windows uses Microsoft Edge WebView2; install Microsoft's WebView2 Evergreen Runtime
if it is missing from your system.

The initial destination is **Music/DJ Buddy** in your home folder. Choose another
folder with **Choose folder**. Each queued track remembers the folder selected when
you started it. **Download MP3** downloads, converts, and saves automatically.
**Open folder** shows the saved location in Finder or Explorer. Files do not expire.
Remove music using Finder or Explorer; the app does not delete your saved tracks.

Keep the app open until downloading finishes. Closing stops the active download;
queued tracks resume next time. An interrupted track can be retried. One copy of the
app can run at a time. Conversion is serial to avoid competing downloads.
No 15-minute track cap or 500 MB storage quota applies to the desktop app. Live
streams are unsupported; a stalled job stops after two hours.

YouTube can still block requests from a user's network. Local processing removes
Render's shared server IP from the path but does not guarantee availability.
MP3 encoding is 320 kbps; the source still determines audio quality.

## Run from source

Use Python 3.12 or newer, Node 22 or newer, and FFmpeg on your PATH.

```sh
python -m venv .venv
# macOS: .venv/bin/python; Windows: .venv\Scripts\python.exe
python -m pip install -r requirements-desktop.txt
python desktop.py
```

Run the commands with the virtual environment's Python (or activate it first).

## Build

Build on each target OS and architecture. Python 3.12 is used in CI.

```sh
python -m pip install -r requirements-build.txt
python scripts/build_desktop.py
```

The build bundles Python, the interface, a separate yt-dlp helper and challenge
scripts, an official Node 22 binary verified against its published SHA-256, and
FFmpeg from imageio-ffmpeg's platform wheel. Build output is in `dist/`.
The **Desktop builds** GitHub Actions workflow creates downloadable ZIP artifacts
for Apple Silicon, Intel macOS, and Windows x64. It runs tests and packaged startup
checks on each OS. These are unsigned test builds, not signed/notarized installers.
Signing, notarization and automatic updating are not configured. For now, rebuild
with current dependencies and replace the app to update yt-dlp.

Before public distribution, complete signing and review the bundled FFmpeg build's
license/source distribution requirements in THIRD_PARTY.md.

## Data and troubleshooting

Settings and job history are in a local SQLite database:

- macOS: `~/Library/Application Support/DJ Buddy`
- Windows: `%LOCALAPPDATA%\DJ Buddy`

`desktop.log` is stored there. Saved music is separate from this directory.
For isolated testing, set `DJ_BUDDY_DATA_DIR` to a temporary directory.
`python desktop.py --smoke-test` verifies tools, startup, session, and history without
opening a window. The application binds only to `127.0.0.1` on a random port, requires
a per-launch private session, checks Host/Origin, and protects mutations with CSRF.

The existing hosted mode (`app.py`, Dockerfile) remains available separately.
