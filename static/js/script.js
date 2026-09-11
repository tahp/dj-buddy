let currentJobId = null;
let pollingTimer = null;


/* --------------------------------
   ENTER KEY
-------------------------------- */

document
    .getElementById("songInput")
    .addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
            startSearch();
        }
    });


/* --------------------------------
   START SEARCH
-------------------------------- */

let searchPending = false;
let downloadPending = false;
let activePreview = null;

function closePreview() {
    if (!activePreview) return;
    activePreview.container.remove();
    activePreview.button.textContent = "Preview";
    activePreview.button.setAttribute("aria-expanded", "false");
    activePreview = null;
}

function togglePreview(track, card, button) {
    const isOpen = activePreview && activePreview.button === button;
    closePreview();
    if (isOpen) return;
    const container = document.createElement("div");
    container.className = "track-preview";
    const player = document.createElement("iframe");
    player.src = `https://www.youtube.com/embed/${encodeURIComponent(track.id)}?autoplay=1&playsinline=1`;
    player.title = "Preview: " + track.title;
    player.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    player.allowFullscreen = true;
    player.referrerPolicy = "strict-origin-when-cross-origin";
    container.append(player);
    const note = document.createElement("p");
    note.className = "results-message";
    note.textContent = "If this video cannot be played here, try another version.";
    container.append(note);
    card.append(container);
    button.textContent = "Close preview";
    button.setAttribute("aria-expanded", "true");
    activePreview = {container, button};
}

async function startSearch() {
    if (searchPending || downloadPending) return;
    const title = document.getElementById("songInput").value.trim();
    if (!title) {
        showError("Enter an artist or track name.");
        return;
    }
    hideError();
    searchPending = true;
    const button = document.getElementById("searchBtn");
    const results = document.getElementById("searchResults");
    button.disabled = true;
    button.textContent = "Searching…";
    closePreview();
    results.replaceChildren();
    document.getElementById("resultsPanel").hidden = false;
    document.getElementById("resultsMessage").textContent = "Finding tracks…";
    try {
        const response = await fetch("/search", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({song_title: title})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to search.");
        document.getElementById("resultsMessage").textContent = data.results.length
            ? "Compare versions, preview, then choose a track."
            : "No tracks found. Try another artist or title.";
        data.results.forEach(track => {
            const card = document.createElement("div");
            card.className = "result-card";
            const name = document.createElement("div");
            name.className = "result-title";
            name.textContent = track.title;
            const details = document.createElement("div");
            details.className = "history-size";
            const seconds = Math.floor(track.duration);
            const duration = track.duration == null ? "Duration unavailable"
                : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
            details.textContent = `${track.uploader} · ${duration}`;
            const actions = document.createElement("div");
            actions.className = "result-actions";
            const preview = document.createElement("button");
            preview.type = "button";
            preview.className = "action-button";
            preview.textContent = "Preview";
            preview.setAttribute("aria-expanded", "false");
            preview.addEventListener("click", () => togglePreview(track, card, preview));
            const download = document.createElement("button");
            download.className = "action-button";
            download.textContent = "Download MP3";
            download.addEventListener("click", () => startDownload(track));
            actions.append(preview, download);
            card.append(name, details, actions);
            results.append(card);
        });
    } catch (error) {
        document.getElementById("resultsMessage").textContent = "Search could not finish.";
        showError(error.message);
    } finally {
        searchPending = false;
        button.disabled = false;
        button.textContent = "Search";
    }
}

async function startDownload(track) {
    if (downloadPending || searchPending) return;
    closePreview();
    downloadPending = true;
    const title = track.title;
    clearTimeout(pollingTimer);
    document.getElementById("resultsPanel").hidden = true;
    hideError();

    document.getElementById("searchBtn").disabled = true;
    document.getElementById("jobCard").style.display = "block";
    document.getElementById("trackTitle").textContent = title;
    document.getElementById("completeBox").style.display = "none";
    document.getElementById("cancelBtn").style.display = "block";
    document.getElementById("log").textContent = "";

    setProgress(0);
    resetSteps();

    try {
        const response = await fetch("/jobs", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                song_title: title,
                video_id: track.id
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error || "Unable to start download."
            );
        }

        currentJobId = data.job_id;

        pollStatus();

    } catch (error) {
        downloadPending = false;
        showError(error.message);

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
        const response = await fetch(
            "/status/" + currentJobId
        );

        const job = await response.json();

        if (!response.ok) {
            throw new Error(
                job.error ||
                "Unable to read job status."
            );
        }

        updateJobUI(job);

        if (job.status === "completed") {
            finishJob(job);
            return;
        }

        if (job.status === "error") {
            downloadPending = false;
            showError(
                job.error || "Download failed."
            );

            document.getElementById(
                "searchBtn"
            ).disabled = false;

            return;
        }

        if (job.status === "cancelled") {
            downloadPending = false;
            document.getElementById(
                "jobMessage"
            ).textContent = "Cancelled.";

            document.getElementById(
                "searchBtn"
            ).disabled = false;

            return;
        }

        pollingTimer = setTimeout(
            pollStatus,
            700
        );

    } catch (error) {
        downloadPending = false;
        showError(error.message);

        document.getElementById(
            "searchBtn"
        ).disabled = false;
    }
}


/* --------------------------------
   UPDATE UI
-------------------------------- */

function updateJobUI(job) {
    setProgress(job.progress);

    document.getElementById(
        "jobMessage"
    ).textContent = job.message;

    document.getElementById(
        "stageText"
    ).textContent = formatStage(job.stage);

    document.getElementById(
        "log"
    ).textContent = job.log.join("\n");

    updateSteps(job.stage);
}


/* --------------------------------
   PROGRESS
-------------------------------- */

function setProgress(value) {
    value = Math.max(
        0,
        Math.min(
            100,
            value
        )
    );

    document.getElementById(
        "progressBar"
    ).style.width = value + "%";

    document.getElementById(
        "progressText"
    ).textContent = value + "%";
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
    ].forEach(id => {
        document.getElementById(
            id
        ).className = "step";
    });
}


function updateSteps(stage) {
    resetSteps();

    const search = document.getElementById(
        "step-search"
    );

    const download = document.getElementById(
        "step-download"
    );

    const convert = document.getElementById(
        "step-convert"
    );

    const finish = document.getElementById(
        "step-finish"
    );

    if (stage === "searching") {
        search.classList.add("active");
    }

    if (stage === "downloading") {
        search.classList.add("complete");
        download.classList.add("active");
    }

    if (stage === "converting") {
        search.classList.add("complete");
        download.classList.add("complete");
        convert.classList.add("active");
    }

    if (stage === "finishing") {
        search.classList.add("complete");
        download.classList.add("complete");
        convert.classList.add("complete");
        finish.classList.add("active");
    }

    if (stage === "completed") {
        search.classList.add("complete");
        download.classList.add("complete");
        convert.classList.add("complete");
        finish.classList.add("complete");
    }
}


/* --------------------------------
   FINISH
-------------------------------- */

function finishJob(job) {
    downloadPending = false;
    setProgress(100);

    updateSteps("completed");

    document.getElementById(
        "completeBox"
    ).style.display = "block";

    document.getElementById(
        "filename"
    ).textContent = job.filename;

    document.getElementById(
        "downloadLink"
    ).href =
        "/download/" +
        encodeURIComponent(
            job.filename
        );

    document.getElementById(
        "cancelBtn"
    ).style.display = "none";

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
            "/cancel/" + currentJobId,
            {
                method: "POST"
            }
        );

        downloadPending = false;
        clearTimeout(
            pollingTimer
        );

        document.getElementById(
            "jobMessage"
        ).textContent = "Cancelled.";

        document.getElementById(
            "cancelBtn"
        ).style.display = "none";

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
    if (downloadPending) return;
    clearTimeout(
        pollingTimer
    );

    currentJobId = null;

    document.getElementById(
        "jobCard"
    ).style.display = "none";

    document.getElementById(
        "songInput"
    ).value = "";

    document.getElementById(
        "searchBtn"
    ).disabled = false;

    document.getElementById(
        "songInput"
    ).focus();

    hideError();
}


/* --------------------------------
   TECH LOG
-------------------------------- */

function toggleLog() {
    const log = document.getElementById(
        "log"
    );

    if (
        log.style.display === "block"
    ) {
        log.style.display = "none";
    } else {
        log.style.display = "block";
    }
}


/* --------------------------------
   HISTORY
-------------------------------- */

async function loadHistory() {
    try {
        const response = await fetch(
            "/history"
        );

        const files = await response.json();

        if (!response.ok) {
            throw new Error(files.error || "Unable to load downloads.");
        }

        const list = document.getElementById(
            "historyList"
        );

        if (!files.length) {
            list.innerHTML = `
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

        list.innerHTML = files.map(file => {
            return `
                <div class="history-item">
                    <div class="history-icon">
                        ♫
                    </div>

                    <div class="history-info">
                        <div class="history-name">
                            ${escapeHtml(file.filename)}
                        </div>

                        <div class="history-size">
                            ${formatBytes(file.size)}
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
                    <button type="button" class="history-delete">
                        Delete
                    </button>
                </div>
            `;
        }).join("");

        list.querySelectorAll(".history-delete").forEach((button, index) => {
            const filename = files[index].filename;
            button.setAttribute("aria-label", "Delete " + filename);
            button.addEventListener("click", () => deleteDownload(filename, button));
        });

    } catch (error) {
        console.error(error);
        showError(error.message);
    }
}


async function deleteDownload(filename, button) {
    if (!window.confirm(`Delete "${filename}" from downloads? This cannot be undone.`)) {
        return;
    }

    hideError();
    button.disabled = true;
    button.textContent = "Deleting…";

    try {
        const response = await fetch("/delete/" + encodeURIComponent(filename), {
            method: "DELETE"
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || "Unable to delete download.");
        }

        if (document.getElementById("filename").textContent === filename) {
            document.getElementById("completeBox").style.display = "none";
            document.getElementById("downloadLink").removeAttribute("href");
            document.getElementById("jobMessage").textContent = "Downloaded file deleted.";
        }
        await loadHistory();
    } catch (error) {
        downloadPending = false;
        showError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Delete";
    }
}


/* --------------------------------
   HELPERS
-------------------------------- */

function formatStage(stage) {
    const names = {
        queued: "Queued",
        searching: "Finding track",
        downloading: "Downloading",
        converting: "Converting",
        finishing: "Finishing",
        completed: "Complete",
        cancelled: "Cancelled",
        error: "Error"
    };

    return names[stage] || stage;
}


function formatBytes(bytes) {
    if (!bytes) {
        return "0 MB";
    }

    return (
        bytes /
        1024 /
        1024
    ).toFixed(1) + " MB";
}


function escapeHtml(text) {
    const div = document.createElement(
        "div"
    );

    div.textContent = text;

    return div.innerHTML;
}


function showError(message) {
    const box = document.getElementById(
        "errorBox"
    );

    box.textContent = message;

    box.style.display = "block";
}


function hideError() {
    document.getElementById(
        "errorBox"
    ).style.display = "none";
}


/* --------------------------------
   LOAD
-------------------------------- */

loadHistory();

document.getElementById(
    "songInput"
).focus();
