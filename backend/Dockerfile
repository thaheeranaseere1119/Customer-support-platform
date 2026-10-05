# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models TRANSFORMERS_CACHE=/models
WORKDIR /app

# CPU-only PyTorch keeps the image small (no CUDA wheels).
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Pre-download the local models so the container works offline.
ARG PRELOAD_MODELS=true
RUN if [ "$PRELOAD_MODELS" = "true" ]; then python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('all-MiniLM-L6-v2'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"; fi

COPY backend/app backend/app
COPY scripts scripts
COPY data data

RUN useradd --create-home appuser && chown -R appuser /app /models
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
# The app waits for the database (DB_CONNECT_RETRIES), creates tables, enables pgvector and auto-seeds on first start.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
