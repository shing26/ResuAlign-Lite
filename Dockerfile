FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY .env.example ./.env.example

ENV PYTHONPATH=/app/src
ENV RESUALIGN_PERSONAL_MODE=1
ENV RESUALIGN_JOB_DB=/app/data/jobs.db
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "resualign.api:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src"]
