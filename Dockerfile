FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm

COPY --from=javascript /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && node --version \
    && python -c "import yt_dlp, yt_dlp_ejs"
COPY app.py auth.py runtime_tools.py .
COPY templates ./templates
COPY static ./static

ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["sh", "-c", "exec gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:${PORT:-10000} --access-logfile - --error-logfile -"]
