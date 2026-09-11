from flask import (
    Flask,
    request,
    Response,
    send_from_directory,
    jsonify
)

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


def create_job(song_title):
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

            # First search result
            f"ytsearch1:{job['title']}",

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

    data = request.get_json(
        silent=True
    ) or {}

    song_title = data.get(
        "song_title",
        ""
    ).strip()

    if not song_title:
        return jsonify({
            "error":
            "No song title provided"
        }), 400

    job = create_job(
        song_title
    )

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

    return r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>DJ Buddy</title>

<style>

* {
    box-sizing: border-box;
}

:root {
    --bg: #08090d;
    --panel: #11131a;
    --panel-hover: #171a23;
    --border: #242733;
    --text: #f5f6fa;
    --muted: #8d93a5;
    --accent: #7c5cff;
    --accent-hover: #927cff;
    --success: #36d399;
    --danger: #ff5470;
}

body {
    margin: 0;
    min-height: 100vh;

    background:
        radial-gradient(
            circle at top,
            #17142c 0%,
            var(--bg) 35%
        );

    color: var(--text);

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Helvetica,
        Arial,
        sans-serif;
}

.page {
    width: 100%;
    max-width: 850px;

    margin: auto;

    padding:
        60px 20px 100px;
}


/* --------------------------------
   HEADER
-------------------------------- */

.logo {
    display: flex;
    align-items: center;
    gap: 12px;

    margin-bottom: 45px;
}

.logo-icon {
    display: flex;
    align-items: center;
    justify-content: center;

    width: 45px;
    height: 45px;

    border-radius: 12px;

    background: var(--accent);

    font-size: 22px;
}

.logo-text {
    font-size: 21px;
    font-weight: 700;
}

.logo-subtitle {
    color: var(--muted);

    font-size: 12px;

    margin-top: 2px;
}


/* --------------------------------
   HERO
-------------------------------- */

.hero {
    margin-bottom: 28px;
}

.hero h1 {
    font-size: clamp(
        32px,
        7vw,
        52px
    );

    line-height: 1.05;

    letter-spacing: -2px;

    margin:
        0 0 12px;
}

.hero p {
    color: var(--muted);

    font-size: 16px;

    margin: 0;
}


/* --------------------------------
   SEARCH
-------------------------------- */

.search-panel {
    background:
        rgba(
            17,
            19,
            26,
            0.92
        );

    border:
        1px solid
        var(--border);

    border-radius: 18px;

    padding: 18px;

    backdrop-filter:
        blur(14px);
}

.search-row {
    display: flex;
    gap: 10px;
}

.search-input {
    flex: 1;

    min-width: 0;

    height: 52px;

    border:
        1px solid
        var(--border);

    border-radius: 12px;

    outline: none;

    background: #0b0d12;

    color: var(--text);

    padding: 0 17px;

    font-size: 16px;

    transition: 0.2s;
}

.search-input:focus {
    border-color:
        var(--accent);

    box-shadow:
        0 0 0 3px
        rgba(
            124,
            92,
            255,
            0.12
        );
}

.search-button {
    height: 52px;

    padding:
        0 25px;

    border: 0;

    border-radius: 12px;

    background:
        var(--accent);

    color: white;

    font-weight: 650;

    font-size: 15px;

    cursor: pointer;

    transition: 0.2s;
}

.search-button:hover {
    background:
        var(--accent-hover);

    transform:
        translateY(-1px);
}

.search-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
}


/* --------------------------------
   CURRENT JOB
-------------------------------- */

.job-card {
    display: none;

    margin-top: 22px;

    background:
        var(--panel);

    border:
        1px solid
        var(--border);

    border-radius: 18px;

    padding: 24px;
}

.track-title {
    font-size: 19px;

    font-weight: 650;

    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    margin-bottom: 8px;
}

.job-message {
    color:
        var(--muted);

    font-size: 14px;

    margin-bottom: 20px;
}


/* --------------------------------
   PROGRESS
-------------------------------- */

.progress-wrapper {
    width: 100%;

    height: 8px;

    background: #262936;

    border-radius: 99px;

    overflow: hidden;
}

.progress-bar {
    height: 100%;

    width: 0%;

    background:
        linear-gradient(
            90deg,
            #6647ff,
            #967cff
        );

    border-radius: inherit;

    transition:
        width 0.3s ease;
}

.progress-info {
    display: flex;

    justify-content:
        space-between;

    margin-top: 9px;

    font-size: 12px;

    color:
        var(--muted);
}


/* --------------------------------
   STEPS
-------------------------------- */

.steps {
    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 8px;

    margin-top: 28px;
}

.step {
    text-align: center;

    font-size: 12px;

    color:
        #5f6473;
}

.step-dot {
    width: 9px;
    height: 9px;

    border-radius: 50%;

    background:
        #404453;

    margin:
        0 auto 8px;
}

.step.active {
    color:
        var(--text);
}

.step.active
.step-dot {
    background:
        var(--accent);

    box-shadow:
        0 0 0 5px
        rgba(
            124,
            92,
            255,
            0.12
        );
}

.step.complete {
    color:
        var(--success);
}

.step.complete
.step-dot {
    background:
        var(--success);
}


/* --------------------------------
   ACTIONS
-------------------------------- */

.actions {
    display: flex;

    gap: 10px;

    margin-top: 25px;
}

.action-button {
    flex: 1;

    height: 45px;

    border-radius: 10px;

    border:
        1px solid
        var(--border);

    color:
        var(--text);

    background:
        #171921;

    cursor: pointer;

    font-weight: 600;
}

.action-button:hover {
    background:
        var(--panel-hover);
}

.cancel-button {
    color:
        var(--danger);
}


/* --------------------------------
   COMPLETE
-------------------------------- */

.complete-box {
    display: none;

    margin-top: 22px;

    border:
        1px solid
        rgba(
            54,
            211,
            153,
            0.25
        );

    background:
        rgba(
            54,
            211,
            153,
            0.06
        );

    border-radius: 14px;

    padding: 18px;
}

.complete-title {
    color:
        var(--success);

    font-weight: 700;

    margin-bottom: 8px;
}

.filename {
    color:
        var(--muted);

    font-size: 13px;

    overflow-wrap:
        anywhere;
}

.download-button {
    display: inline-flex;

    align-items:
        center;

    justify-content:
        center;

    text-decoration:
        none;

    height: 44px;

    padding:
        0 20px;

    background:
        var(--success);

    color:
        #07110d;

    border-radius:
        10px;

    font-weight:
        700;

    margin-top:
        15px;
}


/* --------------------------------
   LOG
-------------------------------- */

.log-toggle {
    margin-top:
        20px;

    background:
        transparent;

    border: 0;

    padding: 0;

    color:
        var(--muted);

    cursor: pointer;
}

.log {
    display: none;

    margin-top:
        15px;

    background:
        #050608;

    border:
        1px solid
        var(--border);

    border-radius:
        10px;

    padding:
        15px;

    max-height:
        280px;

    overflow-y:
        auto;

    white-space:
        pre-wrap;

    word-break:
        break-word;

    font-family:
        "SFMono-Regular",
        Consolas,
        monospace;

    font-size:
        11px;

    line-height:
        1.55;

    color:
        #9ea4b6;
}


/* --------------------------------
   HISTORY
-------------------------------- */

.history {
    margin-top:
        50px;
}

.section-title {
    font-size:
        13px;

    letter-spacing:
        0.7px;

    text-transform:
        uppercase;

    color:
        var(--muted);

    margin-bottom:
        12px;
}

.history-list {
    border:
        1px solid
        var(--border);

    border-radius:
        14px;

    overflow:
        hidden;
}

.history-item {
    display:
        flex;

    align-items:
        center;

    gap:
        13px;

    padding:
        14px 16px;

    border-bottom:
        1px solid
        var(--border);

    background:
        rgba(
            17,
            19,
            26,
            0.8
        );
}

.history-item:last-child {
    border-bottom: 0;
}

.history-icon {
    width:
        35px;

    height:
        35px;

    display:
        flex;

    align-items:
        center;

    justify-content:
        center;

    border-radius:
        8px;

    background:
        #1d202a;
}

.history-info {
    min-width:
        0;

    flex: 1;
}

.history-name {
    font-size:
        14px;

    overflow:
        hidden;

    text-overflow:
        ellipsis;

    white-space:
        nowrap;
}

.history-size {
    margin-top:
        3px;

    color:
        var(--muted);

    font-size:
        11px;
}

.history-download {
    color:
        var(--accent-hover);

    text-decoration:
        none;

    font-size:
        13px;
}


/* --------------------------------
   ERROR
-------------------------------- */

.error-box {
    display:
        none;

    margin-top:
        20px;

    padding:
        15px;

    border:
        1px solid
        rgba(
            255,
            84,
            112,
            0.3
        );

    background:
        rgba(
            255,
            84,
            112,
            0.07
        );

    color:
        #ff7c91;

    border-radius:
        10px;

    font-size:
        13px;
}


/* --------------------------------
   MOBILE
-------------------------------- */

@media (
    max-width: 600px
) {

    .page {
        padding:
            35px 15px
            80px;
    }

    .search-row {
        flex-direction:
            column;
    }

    .search-button {
        width:
            100%;
    }

    .steps {
        font-size:
            10px;
    }

    .step {
        font-size:
            10px;
    }

}

</style>

</head>


<body>

<div class="page">


    <div class="logo">

        <div class="logo-icon">
            ♫
        </div>

        <div>

            <div class="logo-text">
                DJ Buddy
            </div>

            <div class="logo-subtitle">
                Track downloader
            </div>

        </div>

    </div>


    <div class="hero">

        <h1>
            Grab your next track.
        </h1>

        <p>
            Search a track and convert it
            to a high-quality MP3.
        </p>

    </div>


    <div class="search-panel">

        <div class="search-row">

            <input
                id="songInput"
                class="search-input"
                type="text"
                autocomplete="off"
                placeholder="Artist - Track"
            >

            <button
                id="searchBtn"
                class="search-button"
                onclick="startSearch()"
            >
                Download
            </button>

        </div>

    </div>


    <div
        id="errorBox"
        class="error-box"
    ></div>


    <div
        id="jobCard"
        class="job-card"
    >

        <div
            id="trackTitle"
            class="track-title"
        ></div>

        <div
            id="jobMessage"
            class="job-message"
        >
            Preparing...
        </div>


        <div class="progress-wrapper">

            <div
                id="progressBar"
                class="progress-bar"
            ></div>

        </div>


        <div class="progress-info">

            <span id="stageText">
                Starting
            </span>

            <span id="progressText">
                0%
            </span>

        </div>


        <div class="steps">

            <div
                id="step-search"
                class="step"
            >

                <div
                    class="step-dot"
                ></div>

                Find

            </div>


            <div
                id="step-download"
                class="step"
            >

                <div
                    class="step-dot"
                ></div>

                Download

            </div>


            <div
                id="step-convert"
                class="step"
            >

                <div
                    class="step-dot"
                ></div>

                Convert

            </div>


            <div
                id="step-finish"
                class="step"
            >

                <div
                    class="step-dot"
                ></div>

                Done

            </div>

        </div>


        <div
            id="completeBox"
            class="complete-box"
        >

            <div class="complete-title">
                ✓ Download complete
            </div>

            <div
                id="filename"
                class="filename"
            ></div>

            <a
                id="downloadLink"
                class="download-button"
            >
                Download MP3
            </a>

        </div>


        <div class="actions">

            <button
                id="cancelBtn"
                class="
                    action-button
                    cancel-button
                "
                onclick="cancelJob()"
            >
                Cancel
            </button>

            <button
                class="action-button"
                onclick="resetSearch()"
            >
                New Search
            </button>

        </div>


        <button
            class="log-toggle"
            onclick="toggleLog()"
        >
            ▸ Technical log
        </button>


        <div
            id="log"
            class="log"
        ></div>

    </div>


    <div class="history">

        <div class="section-title">
            Recent Downloads
        </div>

        <div
            id="historyList"
            class="history-list"
        >

            <div class="history-item">

                <div class="history-info">

                    <div
                        class="history-size"
                    >
                        No downloads yet
                    </div>

                </div>

            </div>

        </div>

    </div>

</div>


<script>

let currentJobId = null;

let pollingTimer = null;


/* --------------------------------
   ENTER KEY
-------------------------------- */

document
    .getElementById(
        "songInput"
    )
    .addEventListener(
        "keydown",
        function(event) {

            if (
                event.key ===
                "Enter"
            ) {
                startSearch();
            }

        }
    );


/* --------------------------------
   START SEARCH
-------------------------------- */

async function startSearch() {

    const input =
        document.getElementById(
            "songInput"
        );

    const title =
        input.value.trim();

    if (!title) {
        showError(
            "Enter an artist or track name."
        );

        return;
    }

    hideError();

    document.getElementById(
        "searchBtn"
    ).disabled = true;

    document.getElementById(
        "jobCard"
    ).style.display =
        "block";

    document.getElementById(
        "trackTitle"
    ).textContent =
        title;

    document.getElementById(
        "completeBox"
    ).style.display =
        "none";

    document.getElementById(
        "cancelBtn"
    ).style.display =
        "block";

    document.getElementById(
        "log"
    ).textContent =
        "";

    setProgress(0);

    resetSteps();


    try {

        const response =
            await fetch(
                "/search",
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            song_title:
                                title
                        })
                }
            );


        const data =
            await response.json();


        if (!response.ok) {
            throw new Error(
                data.error ||
                "Unable to start download."
            );
        }


        currentJobId =
            data.job_id;


        pollStatus();


    } catch (error) {

        showError(
            error.message
        );

        document.getElementById(
            "searchBtn"
        ).disabled = false;

    }

}


/* --------------------------------
   POLL STATUS
-------------------------------- */

async function pollStatus() {

    if (!currentJobId) {
        return;
    }


    try {

        const response =
            await fetch(
                "/status/" +
                currentJobId
            );


        const job =
            await response.json();


        if (!response.ok) {
            throw new Error(
                job.error ||
                "Unable to read job status."
            );
        }


        updateJobUI(job);


        if (
            job.status ===
            "completed"
        ) {

            finishJob(job);

            return;
        }


        if (
            job.status ===
            "error"
        ) {

            showError(
                job.error ||
                "Download failed."
            );

            document.getElementById(
                "searchBtn"
            ).disabled = false;

            return;
        }


        if (
            job.status ===
            "cancelled"
        ) {

            document.getElementById(
                "jobMessage"
            ).textContent =
                "Cancelled.";

            document.getElementById(
                "searchBtn"
            ).disabled = false;

            return;
        }


        pollingTimer =
            setTimeout(
                pollStatus,
                700
            );


    } catch (error) {

        showError(
            error.message
        );

        document.getElementById(
            "searchBtn"
        ).disabled = false;

    }

}


/* --------------------------------
   UPDATE UI
-------------------------------- */

function updateJobUI(job) {

    setProgress(
        job.progress
    );


    document.getElementById(
        "jobMessage"
    ).textContent =
        job.message;


    document.getElementById(
        "stageText"
    ).textContent =
        formatStage(
            job.stage
        );


    document.getElementById(
        "log"
    ).textContent =
        job.log.join(
            "\n"
        );


    updateSteps(
        job.stage
    );

}


/* --------------------------------
   PROGRESS
-------------------------------- */

function setProgress(value) {

    value =
        Math.max(
            0,
            Math.min(
                100,
                value
            )
        );


    document.getElementById(
        "progressBar"
    ).style.width =
        value + "%";


    document.getElementById(
        "progressText"
    ).textContent =
        value + "%";

}


/* --------------------------------
   STEPS
-------------------------------- */

function resetSteps() {

    [
        "step-search",
        "step-download",
        "step-convert",
        "step-finish"
    ].forEach(
        id => {

            document.getElementById(
                id
            ).className =
                "step";

        }
    );

}


function updateSteps(stage) {

    resetSteps();


    const search =
        document.getElementById(
            "step-search"
        );

    const download =
        document.getElementById(
            "step-download"
        );

    const convert =
        document.getElementById(
            "step-convert"
        );

    const finish =
        document.getElementById(
            "step-finish"
        );


    if (
        stage ===
        "searching"
    ) {

        search.classList.add(
            "active"
        );

    }


    if (
        stage ===
        "downloading"
    ) {

        search.classList.add(
            "complete"
        );

        download.classList.add(
            "active"
        );

    }


    if (
        stage ===
        "converting"
    ) {

        search.classList.add(
            "complete"
        );

        download.classList.add(
            "complete"
        );

        convert.classList.add(
            "active"
        );

    }


    if (
        stage ===
        "finishing"
    ) {

        search.classList.add(
            "complete"
        );

        download.classList.add(
            "complete"
        );

        convert.classList.add(
            "complete"
        );

        finish.classList.add(
            "active"
        );

    }


    if (
        stage ===
        "completed"
    ) {

        search.classList.add(
            "complete"
        );

        download.classList.add(
            "complete"
        );

        convert.classList.add(
            "complete"
        );

        finish.classList.add(
            "complete"
        );

    }

}


/* --------------------------------
   FINISH
-------------------------------- */

function finishJob(job) {

    setProgress(100);

    updateSteps(
        "completed"
    );


    document.getElementById(
        "completeBox"
    ).style.display =
        "block";


    document.getElementById(
        "filename"
    ).textContent =
        job.filename;


    document.getElementById(
        "downloadLink"
    ).href =
        "/download/" +
        encodeURIComponent(
            job.filename
        );


    document.getElementById(
        "cancelBtn"
    ).style.display =
        "none";


    document.getElementById(
        "searchBtn"
    ).disabled = false;


    loadHistory();

}


/* --------------------------------
   CANCEL
-------------------------------- */

async function cancelJob() {

    if (!currentJobId) {
        return;
    }


    try {

        await fetch(
            "/cancel/" +
            currentJobId,
            {
                method:
                    "POST"
            }
        );


        clearTimeout(
            pollingTimer
        );


        document.getElementById(
            "jobMessage"
        ).textContent =
            "Cancelled.";


        document.getElementById(
            "cancelBtn"
        ).style.display =
            "none";


        document.getElementById(
            "searchBtn"
        ).disabled = false;


    } catch (error) {

        showError(
            "Unable to cancel job."
        );

    }

}


/* --------------------------------
   RESET
-------------------------------- */

function resetSearch() {

    clearTimeout(
        pollingTimer
    );


    currentJobId = null;


    document.getElementById(
        "jobCard"
    ).style.display =
        "none";


    document.getElementById(
        "songInput"
    ).value =
        "";


    document.getElementById(
        "searchBtn"
    ).disabled =
        false;


    document.getElementById(
        "songInput"
    ).focus();


    hideError();

}


/* --------------------------------
   TECH LOG
-------------------------------- */

function toggleLog() {

    const log =
        document.getElementById(
            "log"
        );


    if (
        log.style.display ===
        "block"
    ) {

        log.style.display =
            "none";

    } else {

        log.style.display =
            "block";

    }

}


/* --------------------------------
   HISTORY
-------------------------------- */

async function loadHistory() {

    try {

        const response =
            await fetch(
                "/history"
            );


        const files =
            await response.json();


        const list =
            document.getElementById(
                "historyList"
            );


        if (!files.length) {

            list.innerHTML =
                `
                <div class="history-item">

                    <div class="history-info">

                        <div class="history-size">
                            No downloads yet
                        </div>

                    </div>

                </div>
                `;

            return;
        }


        list.innerHTML =
            files.map(
                file => {

                    return `
                    <div class="history-item">

                        <div class="history-icon">
                            ♫
                        </div>

                        <div class="history-info">

                            <div class="history-name">
                                ${escapeHtml(
                                    file.filename
                                )}
                            </div>

                            <div class="history-size">
                                ${formatBytes(
                                    file.size
                                )}
                            </div>

                        </div>

                        <a
                            class="history-download"
                            href="/download/${encodeURIComponent(
                                file.filename
                            )}"
                        >
                            Download
                        </a>

                    </div>
                    `;

                }
            ).join(
                ""
            );


    } catch (error) {

        console.error(
            error
        );

    }

}


/* --------------------------------
   HELPERS
-------------------------------- */

function formatStage(stage) {

    const names = {
        queued:
            "Queued",

        searching:
            "Finding track",

        downloading:
            "Downloading",

        converting:
            "Converting",

        finishing:
            "Finishing",

        completed:
            "Complete",

        cancelled:
            "Cancelled",

        error:
            "Error"
    };


    return (
        names[stage] ||
        stage
    );

}


function formatBytes(bytes) {

    if (!bytes) {
        return "0 MB";
    }


    return (
        bytes /
        1024 /
        1024
    ).toFixed(1) +
        " MB";

}


function escapeHtml(text) {

    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        text;

    return div.innerHTML;

}


function showError(message) {

    const box =
        document.getElementById(
            "errorBox"
        );

    box.textContent =
        message;

    box.style.display =
        "block";

}


function hideError() {

    document.getElementById(
        "errorBox"
    ).style.display =
        "none";

}


/* --------------------------------
   LOAD
-------------------------------- */

loadHistory();

document.getElementById(
    "songInput"
).focus();

</script>

</body>

</html>
"""


# ---------------------------------------------------------
# START SERVER
# ---------------------------------------------------------

if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=5000
    )
