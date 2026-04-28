FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# Pre-install CPU-only torch so sentence-transformers does not pull ~2GB of
# nvidia CUDA libs (cudnn, nccl, cublas, ...) as transitive deps. The CPU
# wheel is ~200MB and the rest of pip resolution sees torch already satisfied.
RUN pip install --no-cache-dir --timeout=300 --retries=5 \
    --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir --timeout=300 --retries=5 -r requirements.txt
COPY . .
RUN mkdir -p /data/faiss
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD curl -f http://localhost:8001/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
