# Build from the repository root:  docker build -f service/Dockerfile -t parser-service:0.1.0 .
# No model weights are copied: the model is downloaded from object storage at start-up.
FROM python:3.11.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HUB_OFFLINE=1 \
    MODEL_DIR=/tmp/model

WORKDIR /srv
COPY service/requirements.txt .
RUN pip install -r requirements.txt && \
    find /usr/local/lib/python3.11 -name '__pycache__' -prune -exec rm -rf {} + && \
    rm -rf /usr/local/lib/python3.11/site-packages/torch/include /root/.cache

COPY service/app/ app/
COPY data/schema.json app/schema.json

RUN useradd --uid 1000 --create-home appuser
USER 1000
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "20"]
