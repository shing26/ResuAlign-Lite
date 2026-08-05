FROM python:3.11-slim

WORKDIR /app

# --- Non-root runtime user -------------------------------------------------
# Fixed UID 1000 so host-side volume permissions are predictable. The image
# runs the web server as `resualign`, never as root.
# Host bind mount note: `./data` is mounted at /app/data by compose.yaml. On
# Linux hosts the directory must be writable by UID 1000:
#   sudo chown -R 1000:1000 ./data
# (Docker Desktop on Windows/macOS maps host permissions automatically.)
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin resualign

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY .env.example ./.env.example

ENV PYTHONPATH=/app/src
ENV RESUALIGN_PERSONAL_MODE=1
ENV RESUALIGN_JOB_DB=/app/data/jobs.db
ENV RESUALIGN_DATA_DIR=/app/data
EXPOSE 8000

# /app/data may be empty for named volumes: pre-create it owned by resualign.
RUN mkdir -p /app/data && chown -R resualign:resualign /app
USER resualign

# HEALTHCHECK uses the bundled Python stdlib (urllib) instead of curl to keep
# the image dependency-free. The API serves GET /health (see src/resualign/api).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# Single process only: the analysis job queue runs in a process-internal
# daemon thread. NEVER pass --workers > 1 (see docs/deployment-security.md).
CMD ["python", "-m", "uvicorn", "resualign.api:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src"]
