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

async function startSearch() {
    const input = document.getElementById("songInput");
    const title = input.value.trim();

    if (!title) {
        showError("Enter an artist or track name.");
        return;
    }

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
        const response = await fetch("/search", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                song_title: title
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
            showError(
                job.error || "Download failed."
            );

            document.getElementById(
                "searchBtn"
            ).disabled = false;

            return;
        }

        if (job.status === "cancelled") {
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
                </div>
            `;
        }).join("");

    } catch (error) {
        console.error(error);
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
