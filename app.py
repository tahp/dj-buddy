from flask import (
    Flask,
    request,
    send_from_directory,
    jsonify,
    render_template
)

import json
import subprocess
import os
import uuid
import threading
import re
import time


app = Flask(__name__)

DOWNLOADS_DIR = os.path.abspath("downloads")
TEMP_DIR = os.path.abspath("temp")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# ---------------------------------------------------------
# JOB STORAGE
# ---------------------------------------------------------

jobs = {}

jobs_lock = threading.Lock()


def sanitize_filename(name):
    """
    Remove characters that can cause filesystem problems.
    """
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def create_job(song_title, video_id):
    job_id = str(uuid.uuid4())[:8]

    clean_title = sanitize_filename(song_title)

    filename = f"{clean_title}.mp3"

    # Avoid overwriting an existing file
    final_path = os.path.join(
        DOWNLOADS_DIR,
        filename
    )

    if os.path.exists(final_path):
        filename = f"{clean_title}_{job_id}.mp3"
        final_path = os.path.join(
            DOWNLOADS_DIR,
            filename
        )

    temp_template = os.path.join(
        TEMP_DIR,
        f"{job_id}.%(ext)s"
    )

    job = {
        "id": job_id,
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

        # Keep logs from growing forever
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


def run_process(job, command):
    """
    Run a process while capturing its output.
    """

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        bufsize=1
    )

    with jobs_lock:
        job["process"] = process

    for line in process.stdout:

        if job["cancelled"]:
            try:
                process.terminate()
            except Exception:
                pass

            return False

        add_log(job, line)

    process.wait()

    with jobs_lock:
        job["process"] = None

    return process.returncode == 0


# ---------------------------------------------------------
# DOWNLOAD WORKER
# ---------------------------------------------------------

def download_worker(job):
    try:

        # -------------------------------------------------
        # FIND / DOWNLOAD
        # -------------------------------------------------

        update_job(
            job,
            status="running",
            stage="searching",
            progress=10,
            message="Searching for track..."
        )

        yt_command = [
            "yt-dlp",

            # Download the exact selected result
            job["source_url"],
            "--ignore-config",
            "--no-playlist",

            # Extract best available audio
            "-f",
            "bestaudio/best",

            # Output unique temp filename
            "-o",
            job["temp_template"],

            # Print resulting filename
            "--print",
            "after_move:filepath",

            "--newline"
        ]

        process = subprocess.Popen(
            yt_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            bufsize=1
        )

        with jobs_lock:
            job["process"] = process

        update_job(
            job,
            stage="downloading",
            progress=25,
            message="Downloading audio..."
        )

        detected_file = None

        for line in process.stdout:

            if job["cancelled"]:
                process.terminate()

                update_job(
                    job,
                    status="cancelled",
                    stage="cancelled",
                    progress=0,
                    message="Download cancelled."
                )

                return

            line = line.rstrip()

            add_log(job, line)

            # Try to extract yt-dlp percentage
            match = re.search(
                r"(\d+(?:\.\d+)?)%",
                line
            )

            if match:
                try:
                    percent = float(match.group(1))

                    # Download occupies 20-70%
                    mapped_progress = int(
                        20 + (percent * 0.5)
                    )

                    update_job(
                        job,
                        progress=min(
                            mapped_progress,
                            70
                        )
                    )

                except ValueError:
                    pass

            # Detect actual downloaded file
            if os.path.exists(line):
                detected_file = line

        process.wait()

        with jobs_lock:
            job["process"] = None

        if process.returncode != 0:
            raise RuntimeError(
                "yt-dlp failed."
            )

        # Fallback search for temp file
        if not detected_file:

            prefix = f"{job['id']}."

            possible_files = [
                os.path.join(
                    TEMP_DIR,
                    filename
                )
                for filename in os.listdir(TEMP_DIR)
                if filename.startswith(prefix)
            ]

            if possible_files:
                detected_file = possible_files[0]

        if not detected_file:
            raise RuntimeError(
                "Downloaded audio file could not be found."
            )

        job["temp_file"] = detected_file


        # -------------------------------------------------
        # CONVERT
        # -------------------------------------------------

        update_job(
            job,
            stage="converting",
            progress=75,
            message="Converting to MP3..."
        )

        ffmpeg_command = [
            "ffmpeg",

            "-y",

            "-i",
            detected_file,

            "-vn",

            "-codec:a",
            "libmp3lame",

            "-b:a",
            "320k",

            job["final_path"]
        ]

        success = run_process(
            job,
            ffmpeg_command
        )

        if job["cancelled"]:

            update_job(
                job,
                status="cancelled",
                stage="cancelled",
                progress=0,
                message="Conversion cancelled."
            )

            return

        if not success:
            raise RuntimeError(
                "FFmpeg conversion failed."
            )


        # -------------------------------------------------
        # CLEANUP
        # -------------------------------------------------

        update_job(
            job,
            stage="finishing",
            progress=95,
            message="Finishing..."
        )

        if (
            detected_file
            and os.path.exists(detected_file)
        ):
            try:
                os.remove(detected_file)
            except Exception:
                pass


        # -------------------------------------------------
        # DONE
        # -------------------------------------------------

        update_job(
            job,
            status="completed",
            stage="completed",
            progress=100,
            message="Download complete."
        )


    except Exception as e:

        add_log(
            job,
            f"ERROR: {str(e)}"
        )

        with jobs_lock:
            job["error"] = str(e)

        update_job(
            job,
            status="error",
            stage="error",
            progress=0,
            message=str(e)
        )


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
    job = create_job(song_title.strip(), video_id)

    thread = threading.Thread(
        target=download_worker,
        args=(job,),
        daemon=True
    )

    thread.start()

    return jsonify({
        "job_id": job["id"]
    })


@app.route("/status/<job_id>")
def job_status(job_id):

    job = jobs.get(job_id)

    if not job:
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
        "log": job["log"][-30:]
    })


@app.route(
    "/cancel/<job_id>",
    methods=["POST"]
)
def cancel_job(job_id):

    job = jobs.get(job_id)

    if not job:
        return jsonify({
            "error": "Job not found"
        }), 404

    with jobs_lock:
        job["cancelled"] = True

        process = job.get(
            "process"
        )

    if process:
        try:
            process.terminate()
        except Exception:
            pass

    update_job(
        job,
        status="cancelled",
        stage="cancelled",
        progress=0,
        message="Cancelled."
    )

    return jsonify({
        "success": True
    })


@app.route(
    "/download/<filename>"
)
def download_file(filename):

    return send_from_directory(
        DOWNLOADS_DIR,
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

    path = os.path.join(DOWNLOADS_DIR, filename)
    with jobs_lock:
        if any(
            job["filename"] == filename
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

    for filename in os.listdir(
        DOWNLOADS_DIR
    ):

        if not filename.lower().endswith(
            ".mp3"
        ):
            continue

        path = os.path.join(
            DOWNLOADS_DIR,
            filename
        )

        files.append({
            "filename": filename,
            "size": os.path.getsize(
                path
            ),
            "modified":
            os.path.getmtime(path)
        })

    files.sort(
        key=lambda x: x["modified"],
        reverse=True
    )

    return jsonify(
        files[:20]
    )


# ---------------------------------------------------------
# WEB UI
# ---------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )
