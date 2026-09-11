"""Resolve bundled tools without relying on a user's Python installation."""
import os
from pathlib import Path
import subprocess
import sys


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def downloader_command():
    if getattr(sys, 'frozen', False):
        suffix = '.exe' if os.name == 'nt' else ''
        return [str(resource_root() / 'downloader' / ('dj-downloader' + suffix))]
    return [sys.executable, '-m', 'yt_dlp']


def tool_path(name):
    if getattr(sys, 'frozen', False):
        return str(resource_root() / 'bin' / (name + ('.exe' if os.name == 'nt' else '')))
    return name


def process_options():
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {'start_new_session': True}


def youtube_command():
    return downloader_command() + ['--js-runtimes', 'node:' + tool_path('node'), '--ignore-config']
