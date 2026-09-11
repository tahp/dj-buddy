"""DJ Buddy desktop entry point. Run from source or the packaged application."""
import argparse
import logging
import multiprocessing
import os
from pathlib import Path
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true', help='Verify startup without opening a window')
    args = parser.parse_args()
    from desktop_support import data_directory, register_desktop_routes
    data_dir = Path(os.environ.get('DJ_BUDDY_DATA_DIR', data_directory()))
    data_dir.mkdir(parents=True, exist_ok=True)
    from filelock import FileLock, Timeout
    lock = FileLock(str(data_dir / 'desktop.lock'))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise SystemExit('DJ Buddy is already running. Close the other window first.')
    os.environ['DJ_BUDDY_DESKTOP'] = '1'
    os.environ['DATA_DIR'] = str(data_dir)
    logging.basicConfig(filename=str(data_dir / 'desktop.log'), level=logging.INFO)
    # The bootstrap URL contains a one-use credential. Do not log HTTP URLs.
    logging.getLogger('werkzeug').disabled = True
    import app as module
    from runtime_tools import tool_path, downloader_command
    from werkzeug.serving import make_server
    import subprocess
    from runtime_tools import process_options
    for command in [downloader_command() + ['--version'], [tool_path('node'), '--version'],
                    [tool_path('ffmpeg'), '-version']]:
        subprocess.run(command, check=True, capture_output=True, timeout=30, **process_options())
    server = make_server('127.0.0.1', 0, module.app, threaded=True)
    module.app.config['DESKTOP_HOST'] = f'127.0.0.1:{server.server_port}'
    url = f"http://127.0.0.1:{server.server_port}/desktop/start?token={module.app.config['DESKTOP_TOKEN']}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if args.smoke_test:
            import urllib.request
            import http.cookiejar
            client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with client.open(url, timeout=10) as response:
                assert b'Choose folder' in response.read()
            with client.open(f'http://127.0.0.1:{server.server_port}/history', timeout=10) as response:
                assert response.status == 200
            print('Desktop startup, bundled tools, local session and history: OK')
            return
        import webview
        window = webview.create_window('DJ Buddy', url, width=960, height=840, min_size=(560, 640))
        register_desktop_routes(module, window)
        webview.settings['ALLOW_FILE_URLS'] = False
        webview.start(private_mode=True)
    finally:
        module.worker_shutdown.set()
        module.queue_wakeup.set()
        with module.app.app_context(), module.jobs_lock:
            for job in module.jobs.values():
                if job['status'] == 'running':
                    job['cancelled'] = True
                    module.stop_process(job.get('process'))
        if module.worker_thread:
            module.worker_thread.join(timeout=10)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        lock.release()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        logging.exception('Desktop startup failed')
        if getattr(sys, 'frozen', False) and '--smoke-test' not in sys.argv:
            import webview
            webview.create_window('DJ Buddy — Unable to start', html='<h2>DJ Buddy could not start</h2><p>Restart the app. If this continues, check desktop.log in the DJ Buddy application data folder.</p>')
            webview.start()
        else:
            raise
