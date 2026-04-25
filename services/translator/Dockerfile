FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Build context is the repo root (see docker-compose.yml) so the shared/
# package is available alongside services/translator/.
COPY services/translator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/translator/ .
COPY shared/ /app/shared/
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD curl -f http://localhost:8005/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
