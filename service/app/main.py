"""Command-parsing inference service.

Configuration (environment only): MODEL_URI, MODEL_VERSION, S3_ENDPOINT,
MAX_NEW_TOKENS, FAULT_INJECT. S3 credentials come from AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY, injected from a Kubernetes Secret.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .schema import Schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parser")

MODEL_URI = os.environ.get("MODEL_URI", "s3://models/v1/")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "v1")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "48"))
MODEL_DIR = os.environ.get("MODEL_DIR", "/tmp/model")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", str(Path(__file__).parent / "schema.json"))
SERVED_BY = os.environ.get("POD_NAME") or socket.gethostname()


def fault_inject() -> bool:
    return os.environ.get("FAULT_INJECT", "0") == "1"


class State:
    generator = None
    ready = False
    lock = threading.Lock()


state = State()
schema = Schema.load(SCHEMA_PATH)


def download_model(uri: str, dest: str) -> None:
    """Download every object under s3://bucket/prefix/ into dest (skips tarballs)."""
    import boto3

    assert uri.startswith("s3://"), f"MODEL_URI must be s3://bucket/prefix, got {uri}"
    bucket, _, prefix = uri[5:].partition("/")
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1")
    Path(dest).mkdir(parents=True, exist_ok=True)
    n = 0
    t0 = time.time()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix):].lstrip("/")
            if not rel or rel.endswith((".tar.gz", "/")):
                continue
            target = Path(dest) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(target))
            n += 1
    if n == 0:
        raise RuntimeError(f"no objects found under {uri}")
    log.info("Downloaded model %s (%d files) from %s%s in %.1fs",
             MODEL_VERSION, n, S3_ENDPOINT, "/" + bucket + "/" + prefix, time.time() - t0)


def load_model() -> None:
    """Download + load, retrying with backoff (e.g. while object storage starts up)."""
    delay = 2.0
    while not state.ready:
        try:
            download_model(MODEL_URI, MODEL_DIR)
            from .inference import Generator

            threads = int(os.environ.get("TORCH_THREADS", "1"))
            state.generator = Generator(MODEL_DIR, MAX_NEW_TOKENS, threads=threads)
            state.ready = True
            log.info("Model %s loaded; ready", MODEL_VERSION)
        except Exception:  # noqa: BLE001 - stay alive and unready, retry
            log.exception("Model load failed; retrying in %.0fs (/readyz stays 503)", delay)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("SKIP_MODEL_LOAD") != "1":
        threading.Thread(target=load_model, daemon=True).start()
    yield
    log.info("shutting down")


app = FastAPI(title="command-parser", lifespan=lifespan)


def _headers() -> dict:
    return {"X-Model-Version": MODEL_VERSION, "X-Served-By": SERVED_BY}


@app.get("/healthz")
async def healthz():
    return JSONResponse({"status": "alive"}, headers=_headers())


@app.get("/readyz")
async def readyz():
    if state.ready:
        return JSONResponse({"status": "ready"}, headers=_headers())
    return JSONResponse({"status": "loading"}, status_code=503, headers=_headers())


@app.post("/parse")
def parse(payload: dict, request: Request):  # sync: runs in threadpool, keeps /healthz responsive
    if not state.ready:
        return JSONResponse({"error": "model_not_ready"}, status_code=503, headers=_headers())
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"error": "bad_request"}, status_code=400, headers=_headers())
    with state.lock:  # one generation at a time per Pod: predictable CPU and memory
        raw = state.generator.generate(text)
    if fault_inject():
        raw = "not json"
    frame = schema.validate(raw)
    if frame is None:
        log.warning("invalid model output for %r: %r", text, raw)
        return JSONResponse({"error": "invalid_model_output"}, status_code=500, headers=_headers())
    return JSONResponse(frame, headers=_headers())
