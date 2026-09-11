"""Local session protection, preferences, and permanent desktop downloads."""
import os
from pathlib import Path
import secrets
import shutil
import sys

from flask import abort, g, jsonify, redirect, request, session
from auth import database, initialize_database


def data_directory():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / 'DJ Buddy'


def init_desktop(app, data_dir):
    token = secrets.token_urlsafe(32)
    app.config.update(SECRET_KEY=secrets.token_hex(32), DATABASE_URL=None,
                      AUTH_DATABASE=str(Path(data_dir) / 'desktop.sqlite3'),
                      DESKTOP_TOKEN=token, MAX_CONTENT_LENGTH=16 * 1024,
                      SESSION_COOKIE_NAME='dj_buddy_desktop',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    with app.app_context():
        initialize_database()
        with database() as db:
            db.execute("INSERT INTO users(id, username, password_hash) VALUES('desktop', 'Local', '!') ON CONFLICT(id) DO NOTHING")
    app.jinja_env.globals['csrf_token'] = lambda: session.get('csrf', '')

    @app.before_request
    def local_session():
        # Host checking also prevents DNS rebinding into the loopback server.
        expected = app.config.get('DESKTOP_HOST')
        if not expected or request.host != expected:
            abort(403)
        if request.headers.get('Origin') not in (None, 'http://' + expected):
            abort(403)
        if request.endpoint == 'desktop_start':
            return
        if not secrets.compare_digest(session.get('desktop', ''), token):
            abort(403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token', '')
            if not supplied or not secrets.compare_digest(supplied, session.get('csrf', '')):
                abort(403)
        g.user = {'id': 'desktop', 'username': 'Local'}
        g.is_admin = False

    @app.after_request
    def protect_local_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    @app.get('/desktop/start')
    def desktop_start():
        supplied = request.args.get('token', '')
        if not supplied or not secrets.compare_digest(supplied, app.config.get('DESKTOP_BOOTSTRAP', token)):
            abort(403)
        app.config['DESKTOP_BOOTSTRAP'] = ''
        session.clear()
        session.update(desktop=token, csrf=secrets.token_urlsafe(32))
        return redirect('/')


def output_directory():
    with database() as db:
        row = db.execute("SELECT value FROM app_settings WHERE name='output_directory'").fetchone()
    return Path(row['value']) if row else Path.home() / 'Music' / 'DJ Buddy'


def set_output_directory(path):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError('Choose an existing folder.')
    # Verify write access without touching existing music.
    import tempfile
    with tempfile.TemporaryFile(dir=path):
        pass
    with database() as db:
        db.execute("INSERT INTO app_settings(name,value) VALUES('output_directory',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (str(path),))
    return path


def publish_download(job):
    destination = Path(job['output_directory']) / job['filename']
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an existing track, even on collision.
    with destination.open('xb') as output:
        try:
            with open(job['final_path'], 'rb') as source:
                shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            destination.unlink(missing_ok=True)
            raise
    job['saved_path'] = str(destination)


def register_desktop_routes(module, window):
    app = module.app

    @app.get('/desktop/settings')
    def settings():
        return jsonify(output_directory=str(output_directory()))

    @app.post('/desktop/folder')
    def choose_folder():
        import webview
        selection = window.create_file_dialog(webview.FileDialog.FOLDER)
        try:
            path = set_output_directory(selection[0]) if selection else output_directory()
        except (OSError, ValueError) as error:
            return jsonify(error='Could not use that folder: ' + str(error)), 400
        return jsonify(output_directory=str(path))

    @app.post('/desktop/open-folder')
    def open_folder():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get('job_id'), (str, type(None))):
            return jsonify(error='Invalid track.'), 400
        with module.jobs_lock:
            job = module.jobs.get(payload.get('job_id'))
            path = Path(job['saved_path']).parent if job and job.get('saved_path') else output_directory()
        if not path.is_dir():
            return jsonify(error='This folder is no longer available.'), 404
        import subprocess
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        return jsonify(success=True)
