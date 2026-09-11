from flask import (
    Flask,
    request,
    send_from_directory,
    jsonify,
    render_template,
    g,
    abort
)

from auth import init_auth, database

import json
import subprocess
import os
import uuid
import threading
import re
import time
import signal
import queue
import shutil
from pathlib import Path


app = Flask(__name__)

DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", os.path.dirname(__file__)))
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")
TEMP_DIR = os.path.join(DATA_DIR, "temp")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
init_auth(app, DATA_DIR)


def user_downloads():
    path = os.path.join(DOWNLOADS_DIR, g.user["id"])
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------
# JOB STORAGE
# ---------------------------------------------------------

jobs = {}

jobs_lock = threading.RLock()
queue_wakeup = threading.Event()
worker_started = False
app.config.update(
    MAX_USER_JOBS=3, MAX_QUEUE_JOBS=20, MAX_TRACK_SECONDS=900,
    MAX_STORED_BYTES=500 * 1024 * 1024, MAX_TEMP_BYTES=200 * 1024 * 1024,
    JOB_TIMEOUT_SECONDS=600, FILE_RETENTION_SECONDS=7 * 86400,
)


def save_job(job):
    payload = {key: value for key, value in job.items() if key != "process"}
    with database() as db:
        db.execute("INSERT OR REPLACE INTO download_jobs VALUES (?, ?)",
                   (job["id"], json.dumps(payload)))


def recover_jobs():
    with jobs_lock:
        with database() as db:
            rows = db.execute("SELECT payload FROM download_jobs").fetchall()
        jobs.clear()
        for row in rows:
            job = json.loads(row["payload"])
            job["process"] = None
            if job["status"] == "running":
                job.update(status="error", stage="error", progress=0,
                           error="Server restarted during this download. Please try again.",
                           message="Server restarted during this download. Please try again.")
                cleanup_job(job)
                save_job(job)
            jobs[job["id"]] = job


def cleanup_job(job):
    shutil.rmtree(os.path.join(TEMP_DIR, job["id"]), ignore_errors=True)
    if job["status"] != "completed":
        Path(job["final_path"]).unlink(missing_ok=True)


def stored_bytes(owner_id):
    directory = Path(DOWNLOADS_DIR) / owner_id
    return sum(path.stat().st_size for path in directory.glob("*.mp3")
               if path.is_file() and not path.is_symlink())


def expire_files():
    cutoff = time.time() - app.config["FILE_RETENTION_SECONDS"]
    with jobs_lock:
        protected = {job["final_path"] for job in jobs.values()
                     if job["status"] in ("queued", "running")}
        for path in Path(DOWNLOADS_DIR).glob("*/*.mp3"):
            if str(path) not in protected and path.is_file() and not path.is_symlink():
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
        expired = [job_id for job_id, job in jobs.items()
                   if job["created_at"] < cutoff and job["status"] not in ("queued", "running")]
        for job_id in expired:
            with database() as db:
                db.execute("DELETE FROM download_jobs WHERE id=?", (job_id,))
            del jobs[job_id]


def queue_worker():
    with app.app_context():
        while True:
            try:
                expire_files()
                with jobs_lock:
                    pending = sorted((job for job in jobs.values() if job["status"] == "queued"),
                                     key=lambda job: job["created_at"])
                    job = pending[0] if pending else None
                    if job:
                        update_job(job, status="running", stage="searching", message="Checking track…")
                if job:
                    download_worker(job)
                    continue
            except Exception:
                app.logger.exception("Download queue error")
            queue_wakeup.wait(30)
            queue_wakeup.clear()


@app.before_request
def ensure_worker():
    global worker_started
    if app.testing:
        return
    with jobs_lock:
        if not worker_started:
            recover_jobs()
            threading.Thread(target=queue_worker, daemon=True).start()
            worker_started = True


def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def create_job(song_title, video_id):
    job_id = uuid.uuid4().hex
    owner_id = g.user["id"]
    downloads_dir = user_downloads()

    clean_title = sanitize_filename(song_title)[:100] or "Track"
    filename = f"{clean_title}_{job_id[:8]}.mp3"
    final_path = os.path.join(downloads_dir, filename)
    temp_template = os.path.join(TEMP_DIR, job_id, "audio.%(ext)s")

    job = {
        "id": job_id,
        "owner_id": owner_id,
        "title": song_title,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "filename": filename,
        "final_path": final_path,
        "temp_template": temp_template,
        "temp_file": None,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "Waiting...",
        "log": [],
        "process": None,
        "cancelled": False,
        "error": None,
        "created_at": time.time()
    }

    with jobs_lock:
        save_job(job)
        jobs[job_id] = job

    return job


def add_log(job, text):
    if not text:
        return
    text = text.rstrip()
    if not text:
        return
    with jobs_lock:
        job["log"].append(text)
        job["log"] = job["log"][-200:]


def update_job(
    job,
    *,
    status=None,
    stage=None,
    progress=None,
    message=None
):
    with jobs_lock:
        if status is not None:
            job["status"] = status
        if stage is not None:
            job["stage"] = stage
        if progress is not None:
            job["progress"] = progress
        if message is not None:
            job["message"] = message
        save_job(job)


def stop_process(process):
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(job, command):
    if job["cancelled"]:
        raise RuntimeError("Download cancelled.")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1, start_new_session=True)
    with jobs_lock:
        job["process"] = process
    output = queue.Queue(maxsize=100)

    def read_output():
        for line in process.stdout:
            try:
                output.put_nowait(line.rstrip()[:2000])
            except queue.Full:
                pass

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while True:
            if job["cancelled"]:
                raise RuntimeError("Download cancelled.")
            if time.monotonic() > job["deadline"]:
                raise RuntimeError("Download exceeded the 10-minute processing limit.")
            temp_size = sum(path.stat().st_size for path in (Path(TEMP_DIR) / job["id"]).glob("*")
                            if path.is_file())
            if temp_size > app.config["MAX_TEMP_BYTES"]:
                raise RuntimeError("Source audio exceeds the 200 MB beta limit.")
            try:
                add_log(job, output.get(timeout=0.2))
            except queue.Empty:
                pass
            if process.poll() is not None and not reader.is_alive() and output.empty():
                break
        if process.returncode:
            raise RuntimeError("Track processing failed. See the technical log for details.")
    finally:
        stop_process(process)
        process.wait()
        reader.join(timeout=2)
        process.stdout.close()
        with jobs_lock:
            job["process"] = None


def download_worker(job):
    with app.app_context():
        temp_dir = Path(TEMP_DIR) / job["id"]
        try:
            with database() as db:
                owner = db.execute("SELECT id FROM users WHERE id=? AND active=1", (job["owner_id"],)).fetchone()
            if not owner:
                raise RuntimeError("Account is no longer active.")
            if stored_bytes(job["owner_id"]) >= app.config["MAX_STORED_BYTES"]:
                raise RuntimeError("Storage limit reached. Delete some downloads and try again.")
            job["deadline"] = time.monotonic() + app.config["JOB_TIMEOUT_SECONDS"]
            temp_dir.mkdir(parents=True, exist_ok=True)
            update_job(job, status="running", stage="searching", progress=10, message="Checking track…")
            run_process(job, ["yt-dlp", "--ignore-config", "--no-playlist", "--skip-download",
                              "--write-info-json", "--socket-timeout", "15", "--retries", "2",
                              "-o", str(temp_dir / "audio.%(ext)s"), job["source_url"]])
            metadata = json.loads((temp_dir / "audio.info.json").read_text())
            duration = metadata.get("duration")
            if (metadata.get("is_live") or metadata.get("live_status") == "is_upcoming"
                    or not isinstance(duration, (int, float)) or duration <= 0
                    or duration > app.config["MAX_TRACK_SECONDS"]):
                raise RuntimeError("Beta downloads require a known duration of 15 minutes or less; live streams are not supported.")
            if stored_bytes(job["owner_id"]) + duration * 40000 + 1024 * 1024 > app.config["MAX_STORED_BYTES"]:
                raise RuntimeError("This track would exceed your 500 MB storage limit. Delete some downloads first.")
            update_job(job, stage="downloading", progress=25, message="Downloading selected track…")
            run_process(job, ["yt-dlp", "--ignore-config", "--no-playlist", "--socket-timeout", "15",
                              "--retries", "2", "--max-filesize", str(app.config["MAX_TEMP_BYTES"]),
                              "-f", "bestaudio/best", "-o", job["temp_template"], job["source_url"]])
            files = [path for path in temp_dir.glob("audio.*")
                     if path.is_file() and path.suffix not in (".json", ".part", ".ytdl")]
            if len(files) != 1:
                raise RuntimeError("Audio could not be downloaded within the beta limits.")
            update_job(job, stage="converting", progress=75, message="Converting to MP3…")
            run_process(job, ["ffmpeg", "-y", "-i", str(files[0]), "-vn", "-t", str(app.config["MAX_TRACK_SECONDS"]),
                              "-codec:a", "libmp3lame", "-b:a", "320k", job["final_path"]])
            with jobs_lock:
                if job["cancelled"]:
                    raise RuntimeError("Download cancelled.")
                update_job(job, status="completed", stage="completed", progress=100, message="Download complete.")
        except Exception as error:
            add_log(job, str(error))
            job["error"] = None if job["cancelled"] else str(error)
            state = "cancelled" if job["cancelled"] else "error"
            update_job(job, status=state, stage=state, progress=0,
                       message="Download cancelled." if job["cancelled"] else str(error))
        finally:
            cleanup_job(job)


# ---------------------------------------------------------
# API ROUTES
# ---------------------------------------------------------

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(silent=True)
    title = data.get("song_title") if isinstance(data, dict) else None
    if not isinstance(title, str) or not title.strip() or len(title) > 300:
        return jsonify({"error": "Enter an artist or track name (up to 300 characters)."}), 400
    try:
        result = subprocess.run(
            ["yt-dlp", "--ignore-config", "--flat-playlist", "--dump-single-json",
             "--no-warnings", "--socket-timeout", "15", f"ytsearch5:{title.strip()}"],
            capture_output=True, text=True, timeout=40, check=True
        )
        entries = json.loads(result.stdout).get("entries", [])
        tracks = []
        for entry in entries:
            if not entry or not re.fullmatch(r"[A-Za-z0-9_-]{11}", entry.get("id", "")):
                continue
            tracks.append({
                "id": entry["id"], "title": entry.get("title") or "Untitled track",
                "uploader": entry.get("uploader") or entry.get("channel") or "Unknown uploader",
                "duration": entry.get("duration")
            })
        return jsonify({"results": tracks})
    except FileNotFoundError:
        return jsonify({"error": "yt-dlp is missing. Install it before searching."}), 503
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Search timed out. Please try again."}), 504
    except (subprocess.CalledProcessError, ValueError):
        return jsonify({"error": "Search is unavailable right now. Please try again."}), 502


@app.route("/jobs", methods=["POST"])
def start_download():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Choose a search result first."}), 400
    song_title = data.get("song_title")
    video_id = data.get("video_id")
    if (not isinstance(song_title, str) or not song_title.strip() or len(song_title) > 300
            or not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)):
        return jsonify({"error": "Choose a valid search result."}), 400
    with jobs_lock:
        active = [job for job in jobs.values() if job["status"] in ("queued", "running")]
        if sum(job["owner_id"] == g.user["id"] for job in active) >= app.config["MAX_USER_JOBS"]:
            return jsonify(error="You already have 3 queued or active downloads."), 429
        if len(active) >= app.config["MAX_QUEUE_JOBS"]:
            return jsonify(error="The beta queue is full. Please try again shortly."), 429
        if stored_bytes(g.user["id"]) >= app.config["MAX_STORED_BYTES"]:
            return jsonify(error="Your 500 MB storage is full. Delete some downloads first."), 429
        job = create_job(song_title.strip(), video_id)
    queue_wakeup.set()

    return jsonify({
        "job_id": job["id"]
    })


@app.get("/jobs/current")
def current_job():
    with jobs_lock:
        owned = [job for job in jobs.values() if job["owner_id"] == g.user["id"]]
        active = [job for job in owned if job["status"] in ("queued", "running")]
        latest = max(active or owned, key=lambda job: job["created_at"], default=None)
    return jsonify(job_id=latest["id"] if latest else None)


@app.route("/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job or job.get("owner_id") != g.user["id"]:
        return jsonify({
            "error": "Job not found"
        }), 404

    return jsonify({
        "id": job["id"],
        "title": job["title"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job["message"],
        "filename": job["filename"],
        "error": job["error"],
        "log": job["log"][-30:],
        "file_available": job["status"] == "completed" and os.path.isfile(job["final_path"])
    })


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    job = jobs.get(job_id)
    if not job or job.get("owner_id") != g.user["id"]:
        return jsonify({
            "error": "Job not found"
        }), 404

    with jobs_lock:
        if job["status"] not in ("queued", "running"):
            return jsonify(error="This job has already finished."), 409
        job["cancelled"] = True
        process = job.get("process")
        if job["status"] == "queued":
            update_job(job, status="cancelled", stage="cancelled", progress=0, message="Cancelled.")
        else:
            update_job(job, message="Cancelling…")
        stop_process(process)

    return jsonify({
        "success": True
    })


@app.route("/download/<filename>")
def download_file(filename):
    if os.path.islink(os.path.join(user_downloads(), filename)):
        abort(404)
    return send_from_directory(
        user_downloads(),
        filename,
        as_attachment=True
    )


@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    if (
        filename != os.path.basename(filename)
        or "\\" in filename
        or not filename.lower().endswith(".mp3")
    ):
        return jsonify({"error": "Invalid filename"}), 400

    path = os.path.join(user_downloads(), filename)
    with jobs_lock:
        if any(
            job["filename"] == filename
            and job.get("owner_id") == g.user["id"]
            and (job["status"] in ("queued", "running") or job.get("process"))
            for job in jobs.values()
        ):
            return jsonify({"error": "This track is still being processed."}), 409

        if os.path.islink(path) or not os.path.isfile(path):
            return jsonify({"error": "Download not found"}), 404

        try:
            os.remove(path)
        except FileNotFoundError:
            return jsonify({"error": "Download not found"}), 404
        except OSError:
            return jsonify({"error": "Unable to delete download."}), 500

    return jsonify({"success": True})


@app.route("/history")
def history():
    files = []
    for filename in os.listdir(user_downloads()):
        if not filename.lower().endswith(".mp3"):
            continue

        path = os.path.join(user_downloads(), filename)
        if os.path.islink(path) or not os.path.isfile(path):
            continue

        files.append({
            "filename": filename,
            "size": os.path.getsize(path),
            "modified": os.path.getmtime(path)
        })

    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files[:20])


# ---------------------------------------------------------
# WEB UI
# ---------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        host="127.0.0.1",
        port=5000
    )