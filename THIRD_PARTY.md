# Bundled components

Desktop builds include third-party software with its own licenses:

- Python: PSF License — https://docs.python.org/3/license.html
- Flask / Werkzeug / Jinja: BSD-3-Clause — https://palletsprojects.com/
- pywebview: BSD-3-Clause — https://github.com/r0x0r/pywebview
- yt-dlp and yt-dlp-ejs: see bundled package licenses and https://github.com/yt-dlp/yt-dlp
- Node.js: MIT and bundled third-party notices, included as NODE-LICENSE.txt.
- imageio-ffmpeg: BSD-2-Clause for its wrapper; the bundled FFmpeg binary has
  separate licensing — https://github.com/imageio/imageio-ffmpeg
- FFmpeg: LGPL/GPL depending on the exact build configuration — https://ffmpeg.org/legal.html

The app uses FFmpeg as a separate executable. Inspect its `-version` and `-L`
output to identify the included build and its configuration. Before distributing
builds publicly, include the corresponding notices and satisfy applicable source
availability requirements for that exact FFmpeg build. CI artifacts are unsigned
engineering builds; this file alone does not fulfill source distribution obligations.
