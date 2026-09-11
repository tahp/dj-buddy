FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py auth.py .
COPY templates ./templates
COPY static ./static

ENV PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["sh", "-c", "exec gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:${PORT:-10000} --access-logfile - --error-logfile -"]
