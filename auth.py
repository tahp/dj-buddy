"""Invite-only beta accounts, signed sessions, and request protection."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import timedelta
from contextlib import contextmanager
from pathlib import Path

import click
from flask import g, session, request, redirect, url_for, jsonify, render_template, current_app
from werkzeug.security import generate_password_hash, check_password_hash


@contextmanager
def database():
    connection = sqlite3.connect(current_app.config['AUTH_DATABASE'], timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with database() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS download_jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS invites (
                digest TEXT PRIMARY KEY, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                username TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires REAL NOT NULL
            );
        ''')


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def init_auth(app, data_dir):
    secret = os.environ.get('SECRET_KEY')
    if os.environ.get('RENDER') and not secret:
        raise RuntimeError('Set SECRET_KEY in Render before starting the app.')
    if not secret:
        secret_file = Path(data_dir) / '.session-secret'
        try:
            with open(secret_file, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        secret = secret_file.read_text().strip()
    app.config.update(
        SECRET_KEY=secret,
        AUTH_DATABASE=os.path.join(data_dir, 'accounts.sqlite3'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    with app.app_context():
        initialize_database()
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def authenticate():
        g.user = None
        if session.get('user_id'):
            with database() as db:
                g.user = db.execute('SELECT id, username FROM users WHERE id=? AND active=1',
                                    (session['user_id'],)).fetchone()
        
        public_endpoints = ('login', 'join', 'static', 'health')
        if request.endpoint not in public_endpoints and not g.user:
            if request.is_json or request.path in ('/search', '/jobs') or request.path.startswith('/jobs/'):
                return jsonify(error='Please sign in again.'), 401
            return redirect(url_for('login'))

        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not token or not secrets.compare_digest(token, session.get('csrf', '')):
                return jsonify(error='Your session changed. Refresh the page and try again.'), 400

    @app.after_request
    def protect_response(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    @app.route('/health')
    def health():
        return jsonify(status='ok')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            username = request.form.get('username', '').strip().lower()[:80]
            password = request.form.get('password', '')
            now = time.time()
            with database() as db:
                db.execute('DELETE FROM login_attempts WHERE expires < ?', (now,))
                attempt = db.execute('SELECT * FROM login_attempts WHERE username=?', (username,)).fetchone()
                if attempt and attempt['attempts'] >= 10:
                    return render_template('auth.html', mode='login', error='Too many attempts. Try again in 15 minutes.'), 429
                db.execute('''INSERT INTO login_attempts VALUES (?, 1, ?)
                    ON CONFLICT(username) DO UPDATE SET attempts=attempts+1''', (username, now + 900))
            with database() as db:
                user = db.execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                with database() as db:
                    db.execute('DELETE FROM login_attempts WHERE username=?', (username,))
                return redirect(url_for('index'))
            error = 'Incorrect username or password.'
        return render_template('auth.html', mode='login', error=error)

    @app.route('/join', methods=['GET', 'POST'])
    def join():
        error = None
        if request.method == 'POST':
            code = request.form.get('invite', '').strip()
            username = request.form.get('username', '').strip().lower()
            password = request.form.get('password', '')
            if not re.fullmatch(r'[a-z0-9_-]{3,40}', username):
                error = 'Use 3–40 letters, numbers, underscores, or hyphens for your username.'
            elif len(password) < 12 or len(password) > 256:
                error = 'Choose a password between 12 and 256 characters.'
            else:
                digest = hashlib.sha256(code.encode()).hexdigest()
                with database() as db:
                    invite = db.execute('SELECT * FROM invites WHERE digest=? AND used=0 AND expires>?',
                                        (digest, time.time())).fetchone()
                if not invite:
                    error = 'This invite code is invalid, expired, or already used.'
                else:
                    password_hash = generate_password_hash(password)
                    user_id = secrets.token_hex(16)
                    try:
                        with database() as db:
                            claimed = db.execute('UPDATE invites SET used=1 WHERE digest=? AND used=0 AND expires>?',
                                                 (digest, time.time()))
                            if claimed.rowcount != 1:
                                error = 'This invite code is invalid, expired, or already used.'
                            else:
                                db.execute('INSERT INTO users(id, username, password_hash) VALUES(?,?,?)',
                                           (user_id, username, password_hash))
                    except sqlite3.IntegrityError:
                        error = 'That username is already taken.'
                    if not error:
                        session.clear()
                        session['user_id'] = user_id
                        session.permanent = True
                        return redirect(url_for('index'))
        return render_template('auth.html', mode='join', error=error)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.cli.command('invite')
    def invite_command():
        """Create a single-use invite code valid for seven days."""
        code = secrets.token_urlsafe(24)
        with database() as db:
            db.execute('INSERT INTO invites(digest, expires) VALUES(?,?)',
                       (hashlib.sha256(code.encode()).hexdigest(), time.time() + 7 * 86400))
        click.echo('Single-use invite code (expires in 7 days):')
        click.echo(code)

    @app.cli.command('disable-user')
    @click.argument('username')
    def disable_user(username):
        """Revoke an account, including its existing sessions."""
        with database() as db:
            result = db.execute('UPDATE users SET active=0 WHERE username=?', (username.lower(),))
        if not result.rowcount:
            raise click.ClickException('User not found.')
        click.echo('Account disabled.')