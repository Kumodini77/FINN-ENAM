# FINN backend — production image for Northflank (or any container host).
#
# Base: python:3.14-slim-bookworm, matching the exact interpreter this project is
# developed and tested against (confirmed via `python --version` in the dev
# venv) — not an older LTS chosen for convenience. All of this project's direct
# dependencies (sentence-transformers, torch, pdfplumber, pydantic, pandas,
# pillow, supabase) were confirmed to publish either a cp314 wheel or a
# pure-Python/universal wheel on PyPI before this base was chosen — this was
# NOT assumed, it was checked (see docs/FINN_NORTHFLANK_DEPLOYMENT_AUDIT.md).
# No compiler toolchain is installed, since nothing in requirements.txt needed
# to be built from source for this interpreter at the time of writing.

FROM python:3.14-slim-bookworm

WORKDIR /app

# libgomp1: torch's OpenMP runtime dependency — a well-known requirement on
# slim Debian images that is otherwise missing, surfacing only at import time
# as "libgomp.so.1: cannot open shared object file", not at pip-install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download and cache the pinned local embedding model INTO THE IMAGE at
# build time, using the exact same call app/services/embeddings/local_minilm.py
# makes at runtime (same model name, same pinned revision) — so the first real
# request never pays a multi-second Hugging Face download, and the container
# does not depend on outbound internet access to huggingface.co at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41')"

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

# Ephemeral by design: this is ONLY the JSON-fallback/local-cache directory
# (app.core.config.Settings.data_dir) used when Supabase isn't configured or
# briefly unreachable. It is not a substitute for a persistent volume and is
# not expected to survive a restart — Supabase is the real store in production.
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

EXPOSE 8000

# Northflank (like most PaaS hosts) injects $PORT at runtime and expects the
# process to bind to it, not to a fixed port baked into the image — the shell
# form is used specifically so ${PORT} is expanded at container start, with
# 8000 as a safe local-dev fallback if it's ever unset. 0.0.0.0 is required:
# binding to 127.0.0.1 would make the app unreachable from outside the container.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
