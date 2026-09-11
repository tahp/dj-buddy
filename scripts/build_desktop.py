"""Build self-contained desktop bundles on the target OS (Python 3.12 recommended)."""
import hashlib
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / 'build' / 'desktop-tools'


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def prepare_tools():
    STAGING.mkdir(parents=True, exist_ok=True)
    system = {'Darwin': 'darwin', 'Windows': 'win'}[platform.system()]
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}[platform.machine()]
    extension = 'zip' if system == 'win' else 'tar.gz'
    base = 'https://nodejs.org/dist/latest-v22.x/'
    sums = fetch(base + 'SHASUMS256.txt').decode()
    checksum, filename = next(line.split() for line in sums.splitlines()
                              if line.endswith(f'-{system}-{arch}.{extension}'))
    archive = fetch(base + filename)
    if hashlib.sha256(archive).hexdigest() != checksum:
        raise RuntimeError('Node archive checksum mismatch')
    suffix = '.exe' if system == 'win' else ''
    if system == 'win':
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            member = next(name for name in bundle.namelist() if name.endswith('/node.exe'))
            node = bundle.read(member)
            license_text = bundle.read(next(name for name in bundle.namelist() if name.endswith('/LICENSE')))
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
            node = bundle.extractfile(next(member for member in bundle.getmembers() if member.name.endswith('/bin/node'))).read()
            license_text = bundle.extractfile(next(member for member in bundle.getmembers() if member.name.endswith('/LICENSE'))).read()
    (STAGING / ('node' + suffix)).write_bytes(node)
    (STAGING / ('node' + suffix)).chmod(0o755)
    (STAGING / 'NODE-LICENSE.txt').write_bytes(license_text)
    import imageio_ffmpeg
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), STAGING / ('ffmpeg' + suffix))
    (STAGING / ('ffmpeg' + suffix)).chmod(0o755)


def run(*args):
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', *args], cwd=ROOT, check=True)


def main():
    prepare_tools()
    helper_dist = ROOT / 'build' / 'helper-dist'
    run('--onedir', '--console', '--name', 'dj-downloader',
        '--distpath', str(helper_dist), '--workpath', 'build/helper-work', '--specpath', 'build',
        '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs', str(ROOT / 'downloader_cli.py'))
    run('--onedir', '--windowed', '--name', 'DJ Buddy', '--specpath', 'build',
        '--osx-bundle-identifier', 'com.djbuddy.desktop',
        '--add-data', f'{ROOT / "templates"}{os.pathsep}templates',
        '--add-data', f'{ROOT / "static"}{os.pathsep}static',
        '--add-data', f'{helper_dist / "dj-downloader"}{os.pathsep}downloader',
        '--add-data', f'{ROOT / "DESKTOP.md"}{os.pathsep}.',
        '--add-data', f'{ROOT / "THIRD_PARTY.md"}{os.pathsep}.',
        '--add-data', f'{STAGING / "NODE-LICENSE.txt"}{os.pathsep}.',
        '--add-binary', f'{STAGING / ("node.exe" if os.name == "nt" else "node")}{os.pathsep}bin',
        '--add-binary', f'{STAGING / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")}{os.pathsep}bin',
        '--exclude-module', 'psycopg', '--exclude-module', 'pytest', str(ROOT / 'desktop.py'))
    print('Built desktop app in dist/')


if __name__ == '__main__':
    main()
